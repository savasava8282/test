from __future__ import annotations

from collections.abc import Iterable
import sys

from weather_alert_bot.start_handler import START_COMMANDS
from weather_alert_bot.storage import (
    SQLiteSettingsStore,
    StorageError,
    normalize_daily_send_days,
)
from weather_alert_bot.telegram_api import TelegramClient, TelegramUpdate


DAILY_DAYS_PROMPT = (
    "В какие дни отправлять ежедневную сводку? Введите номера дней через запятую: "
    "1=Пн, 2=Вт, 3=Ср, 4=Чт, 5=Пт, 6=Сб, 7=Вс. По умолчанию — каждый день."
)
INVALID_DAILY_DAYS_TEXT = (
    "Некорректные дни. Введите номера от 1 до 7 через запятую, "
    "например: 1,2,3,4,5."
)
NO_SAVED_CITY_TEXT = "Сначала сохраните подтверждённый город."
DAILY_DAYS_SAVED_TEXT = "Дни ежедневной отправки сохранены: {daily_send_days}."
DAILY_DAYS_STORAGE_ERROR_TEXT = (
    "Сохранить дни ежедневной отправки не удалось. Попробуйте позже."
)
_DAY_NAMES = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


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


def _format_daily_send_days(normalized_days: str) -> str:
    return ", ".join(_DAY_NAMES[int(day) - 1] for day in normalized_days.split(","))


def run_until_daily_days(
    telegram_client: TelegramClient,
    storage: SQLiteSettingsStore,
) -> int:
    """Wait for one existing user and save one canonical weekday selection."""
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
                            text=DAILY_DAYS_STORAGE_ERROR_TEXT,
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
                        text=DAILY_DAYS_PROMPT,
                    )
                    print("Ожидание дней ежедневной отправки...")
                    continue

                if message.chat_id != started_chat_id or message.text is None:
                    continue

                try:
                    normalized_days = normalize_daily_send_days(message.text)
                except ValueError:
                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=INVALID_DAILY_DAYS_TEXT,
                    )
                    continue

                try:
                    storage.save_daily_send_days(started_chat_id, normalized_days)
                except StorageError:
                    print("Не удалось сохранить дни ежедневной отправки.", file=sys.stderr)
                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=DAILY_DAYS_STORAGE_ERROR_TEXT,
                    )
                    return 1

                telegram_client.send_message(
                    chat_id=started_chat_id,
                    text=DAILY_DAYS_SAVED_TEXT.format(
                        daily_send_days=_format_daily_send_days(normalized_days)
                    ),
                )
                print("Дни ежедневной отправки сохранены.")
                return 0
    except KeyboardInterrupt:
        print("Ожидание дней ежедневной отправки остановлено.")
        return 130
