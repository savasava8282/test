from __future__ import annotations

from collections.abc import Iterable
import sys

from weather_alert_bot.start_handler import START_COMMANDS
from weather_alert_bot.storage import SQLiteSettingsStore, StorageError
from weather_alert_bot.telegram_api import TelegramClient, TelegramUpdate


DAILY_SENDING_PROMPT = (
    "Включить ежедневную рассылку? По умолчанию — включена. Ответьте: Да или Нет."
)
INVALID_DAILY_SENDING_TEXT = "Некорректный ответ. Введите: Да или Нет."
NO_SAVED_CITY_TEXT = "Сначала сохраните подтверждённый город."
DAILY_SENDING_ENABLED_TEXT = "Ежедневная рассылка включена."
DAILY_SENDING_DISABLED_TEXT = "Ежедневная рассылка выключена."
DAILY_SENDING_SAVED_TEXT = "Настройка ежедневной рассылки сохранена."
DAILY_SENDING_STORAGE_ERROR_TEXT = (
    "Сохранить настройку ежедневной рассылки не удалось. Попробуйте позже."
)


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


def _parse_daily_sending_answer(text: str) -> bool | None:
    normalized = text.strip().casefold()
    if normalized == "да":
        return True
    if normalized == "нет":
        return False
    return None


def run_until_daily_sending(
    telegram_client: TelegramClient,
    storage: SQLiteSettingsStore,
) -> int:
    """Wait for one existing user and save the daily-sending preference."""
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
                            text=DAILY_SENDING_STORAGE_ERROR_TEXT,
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
                        text=DAILY_SENDING_PROMPT,
                    )
                    print("Ожидание настройки ежедневной рассылки...")
                    continue

                if message.chat_id != started_chat_id or message.text is None:
                    continue

                enabled = _parse_daily_sending_answer(message.text)
                if enabled is None:
                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=INVALID_DAILY_SENDING_TEXT,
                    )
                    continue

                try:
                    storage.save_daily_sending_enabled(started_chat_id, enabled)
                except StorageError:
                    print(
                        "Не удалось сохранить настройку ежедневной рассылки.",
                        file=sys.stderr,
                    )
                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=DAILY_SENDING_STORAGE_ERROR_TEXT,
                    )
                    return 1

                telegram_client.send_message(
                    chat_id=started_chat_id,
                    text=(
                        DAILY_SENDING_ENABLED_TEXT
                        if enabled
                        else DAILY_SENDING_DISABLED_TEXT
                    ),
                )
                print(DAILY_SENDING_SAVED_TEXT)
                return 0
    except KeyboardInterrupt:
        print("Ожидание настройки ежедневной рассылки остановлено.")
        return 130
