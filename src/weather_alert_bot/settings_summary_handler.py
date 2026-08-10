from __future__ import annotations

from collections.abc import Iterable

from weather_alert_bot.start_handler import START_COMMANDS
from weather_alert_bot.storage import (
    SQLiteSettingsStore,
    StorageError,
    UserSettings,
    WARNING_CATEGORY_KEYS,
)
from weather_alert_bot.telegram_api import TelegramClient, TelegramUpdate


SETTINGS_SUMMARY_STORAGE_ERROR_TEXT = (
    "Показать итоговые настройки не удалось. Попробуйте позже."
)
NO_SAVED_CITY_TEXT = "Сначала сохраните подтверждённый город."
SETTINGS_SUMMARY_PREFIX = "Итоговые настройки:"
_DAY_NAMES = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
_WARNING_CATEGORY_LABELS = {
    "magnetic_storm": "Магнитная буря",
    "heat": "Жара",
    "cold": "Холод",
    "icing": "Гололёд",
    "heavy_rain": "Сильный дождь",
    "thunderstorm": "Гроза",
    "strong_wind": "Сильный ветер",
    "storm": "Шторм",
}


def _next_offset(
    current_offset: int | None,
    updates: Iterable[TelegramUpdate],
) -> int | None:
    update_ids = [update.update_id for update in updates]
    if not update_ids:
        return current_offset
    candidate = max(update_ids) + 1
    if current_offset is None:
        return candidate
    return max(current_offset, candidate)


def format_daily_send_days(daily_send_days: str) -> str:
    """Format canonical stored weekday numbers as Russian abbreviations."""
    return ", ".join(
        _DAY_NAMES[int(day) - 1] for day in daily_send_days.split(",")
    )


def _enabled_warning_categories(settings: UserSettings) -> list[str]:
    return [
        key
        for key in WARNING_CATEGORY_KEYS
        if getattr(settings, f"warning_{key}_enabled")
    ]


def format_warning_categories(settings: UserSettings) -> str:
    """Format enabled warning categories in their established user-facing order."""
    enabled_categories = _enabled_warning_categories(settings)
    if not enabled_categories:
        return "отключены"
    return ", ".join(_WARNING_CATEGORY_LABELS[key] for key in enabled_categories)


def format_settings_summary(settings: UserSettings) -> str:
    """Build the stable read-only summary sent to the user."""
    daily_sending = "включена" if settings.daily_sending_enabled else "выключена"
    urgent_warnings = "включены" if settings.urgent_warnings_enabled else "выключены"
    return (
        f"{SETTINGS_SUMMARY_PREFIX}\n\n"
        f"Город: {settings.city_name}\n"
        f"Время ежедневной отправки: {settings.daily_send_time}\n"
        f"Дни отправки: {format_daily_send_days(settings.daily_send_days)}\n"
        f"Ежедневная рассылка: {daily_sending}\n"
        f"Срочные предупреждения: {urgent_warnings}\n"
        f"Категории предупреждений: {format_warning_categories(settings)}"
    )


def run_until_settings_summary(
    telegram_client: TelegramClient,
    storage: SQLiteSettingsStore,
) -> int:
    """Wait for one private /start and send the saved settings without writing them."""
    offset: int | None = None
    seen_update_ids: set[int] = set()

    try:
        while True:
            old_updates = telegram_client.get_updates(
                offset=offset,
                timeout=0,
                limit=100,
            )
            offset = _next_offset(offset, old_updates)
            seen_update_ids.update(update.update_id for update in old_updates)
            if not old_updates:
                break

        print("Ожидание новой команды /start...")

        while True:
            updates = telegram_client.get_updates(offset=offset, timeout=30, limit=100)
            offset = _next_offset(offset, updates)

            for update in updates:
                if update.update_id in seen_update_ids:
                    continue
                seen_update_ids.add(update.update_id)

                message = update.message
                if message is None or message.chat_type != "private":
                    continue
                if message.text not in START_COMMANDS:
                    continue

                try:
                    settings = storage.get_user_settings(message.chat_id)
                except StorageError:
                    telegram_client.send_message(
                        chat_id=message.chat_id,
                        text=SETTINGS_SUMMARY_STORAGE_ERROR_TEXT,
                    )
                    return 1

                print("Команда /start получена.")
                if settings is None:
                    telegram_client.send_message(
                        chat_id=message.chat_id,
                        text=NO_SAVED_CITY_TEXT,
                    )
                    print("Сохранённый город не найден.")
                    return 1

                telegram_client.send_message(
                    chat_id=message.chat_id,
                    text=format_settings_summary(settings),
                )
                print("Итоговая сводка настроек отправлена.")
                return 0
    except KeyboardInterrupt:
        print("Ожидание итоговой сводки настроек остановлено.")
        return 130
