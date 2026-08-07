from __future__ import annotations

from collections.abc import Iterable
import sys

from weather_alert_bot.start_handler import START_COMMANDS
from weather_alert_bot.storage import (
    SQLiteSettingsStore,
    StorageError,
    normalize_daily_send_time,
)
from weather_alert_bot.telegram_api import TelegramClient, TelegramUpdate


DAILY_TIME_PROMPT = (
    "Во сколько отправлять ежедневную сводку? Введите время в формате ЧЧ:ММ. "
    "По умолчанию — 07:00."
)
INVALID_DAILY_TIME_TEXT = "Некорректное время. Введите его в формате ЧЧ:ММ, например 07:00."
NO_SAVED_CITY_TEXT = "Сначала сохраните подтверждённый город."
DAILY_TIME_SAVED_TEXT = "Время ежедневной отправки сохранено: {daily_send_time}."
DAILY_TIME_STORAGE_ERROR_TEXT = "Сохранить время ежедневной отправки не удалось. Попробуйте позже."


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


def run_until_daily_time(
    telegram_client: TelegramClient,
    storage: SQLiteSettingsStore,
) -> int:
    """Wait for one existing user and save one local daily send time."""
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
                            text=DAILY_TIME_STORAGE_ERROR_TEXT,
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
                        text=DAILY_TIME_PROMPT,
                    )
                    print("Ожидание времени ежедневной отправки...")
                    continue

                if message.chat_id != started_chat_id or message.text is None:
                    continue

                try:
                    normalized_time = normalize_daily_send_time(message.text)
                except ValueError:
                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=INVALID_DAILY_TIME_TEXT,
                    )
                    continue

                try:
                    storage.save_daily_send_time(started_chat_id, normalized_time)
                except StorageError:
                    print("Не удалось сохранить время ежедневной отправки.", file=sys.stderr)
                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=DAILY_TIME_STORAGE_ERROR_TEXT,
                    )
                    return 1

                telegram_client.send_message(
                    chat_id=started_chat_id,
                    text=DAILY_TIME_SAVED_TEXT.format(daily_send_time=normalized_time),
                )
                print("Время ежедневной отправки сохранено.")
                return 0
    except KeyboardInterrupt:
        print("Ожидание времени ежедневной отправки остановлено.")
        return 130
