from __future__ import annotations

from collections.abc import Iterable
import re
import sys

from weather_alert_bot.start_handler import START_COMMANDS
from weather_alert_bot.storage import (
    SQLiteSettingsStore,
    StorageError,
    WARNING_CATEGORY_KEYS,
)
from weather_alert_bot.telegram_api import TelegramClient, TelegramUpdate


WARNING_CATEGORIES_PROMPT = (
    "Какие категории предупреждений включить? Введите номера через запятую: "
    "1=Магнитная буря, 2=Жара, 3=Холод, 4=Гололёд, 5=Сильный дождь, "
    "6=Гроза, 7=Сильный ветер, 8=Шторм. Чтобы отключить все категории, введите 0."
)
INVALID_WARNING_CATEGORIES_TEXT = (
    "Некорректные категории. Введите уникальные номера от 1 до 8 через запятую "
    "или 0, чтобы отключить все."
)
NO_SAVED_CITY_TEXT = "Сначала сохраните подтверждённый город."
WARNING_CATEGORIES_STORAGE_ERROR_TEXT = (
    "Сохранить категории предупреждений не удалось. Попробуйте позже."
)
WARNING_CATEGORIES_SAVED_TEXT = "Категории предупреждений сохранены."
ALL_WARNING_CATEGORIES_DISABLED_TEXT = "Все категории предупреждений отключены."
WARNING_CATEGORY_LABELS = {
    "magnetic_storm": "Магнитная буря",
    "heat": "Жара",
    "cold": "Холод",
    "icing": "Гололёд",
    "heavy_rain": "Сильный дождь",
    "thunderstorm": "Гроза",
    "strong_wind": "Сильный ветер",
    "storm": "Шторм",
}
_WARNING_CATEGORY_NUMBER_PATTERN = re.compile(r"[1-8]\Z")


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


def parse_warning_categories(text: str) -> frozenset[str] | None:
    """Parse category numbers into stable internal keys in canonical form."""
    if not isinstance(text, str):
        return None

    normalized = text.strip()
    if normalized == "0":
        return frozenset()
    if not normalized:
        return None

    parts = normalized.split(",")
    if any(not part.strip() for part in parts):
        return None

    numbers = [part.strip() for part in parts]
    if any(_WARNING_CATEGORY_NUMBER_PATTERN.fullmatch(number) is None for number in numbers):
        return None
    if len(numbers) != len(set(numbers)):
        return None

    return frozenset(WARNING_CATEGORY_KEYS[int(number) - 1] for number in numbers)


def _format_warning_categories(enabled_categories: frozenset[str]) -> str:
    return ", ".join(
        WARNING_CATEGORY_LABELS[key]
        for key in WARNING_CATEGORY_KEYS
        if key in enabled_categories
    )


def run_until_warning_categories(
    telegram_client: TelegramClient,
    storage: SQLiteSettingsStore,
) -> int:
    """Wait for one existing user and save all warning-category states."""
    offset: int | None = None
    seen_update_ids: set[int] = set()
    started_chat_id: int | None = None

    try:
        while True:
            old_updates = telegram_client.get_updates(offset=offset, timeout=0, limit=100)
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

                if started_chat_id is None:
                    if message.text not in START_COMMANDS:
                        continue

                    started_chat_id = message.chat_id
                    try:
                        user_settings = storage.get_user_settings(started_chat_id)
                    except StorageError:
                        telegram_client.send_message(
                            chat_id=started_chat_id,
                            text=WARNING_CATEGORIES_STORAGE_ERROR_TEXT,
                        )
                        return 1

                    print("Команда /start получена.")
                    if user_settings is None:
                        telegram_client.send_message(
                            chat_id=started_chat_id,
                            text=NO_SAVED_CITY_TEXT,
                        )
                        print("Сохранённый город не найден.")
                        return 1

                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=WARNING_CATEGORIES_PROMPT,
                    )
                    print("Ожидание категорий предупреждений...")
                    continue

                if message.chat_id != started_chat_id or message.text is None:
                    continue

                enabled_categories = parse_warning_categories(message.text)
                if enabled_categories is None:
                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=INVALID_WARNING_CATEGORIES_TEXT,
                    )
                    continue

                try:
                    storage.save_warning_categories(
                        started_chat_id,
                        enabled_categories,
                    )
                except StorageError:
                    print(
                        "Не удалось сохранить категории предупреждений.",
                        file=sys.stderr,
                    )
                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=WARNING_CATEGORIES_STORAGE_ERROR_TEXT,
                    )
                    return 1

                if enabled_categories:
                    telegram_text = (
                        "Категории предупреждений сохранены: "
                        f"{_format_warning_categories(enabled_categories)}."
                    )
                else:
                    telegram_text = ALL_WARNING_CATEGORIES_DISABLED_TEXT
                telegram_client.send_message(
                    chat_id=started_chat_id,
                    text=telegram_text,
                )
                print(WARNING_CATEGORIES_SAVED_TEXT)
                return 0
    except KeyboardInterrupt:
        print("Ожидание категорий предупреждений остановлено.")
        return 130
