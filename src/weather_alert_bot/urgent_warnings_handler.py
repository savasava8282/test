from __future__ import annotations

from collections.abc import Iterable
import sys

from weather_alert_bot.start_handler import START_COMMANDS
from weather_alert_bot.storage import SQLiteSettingsStore, StorageError
from weather_alert_bot.telegram_api import TelegramClient, TelegramUpdate


URGENT_WARNINGS_PROMPT = (
    "Включить срочные предупреждения? По умолчанию — включены. Ответьте: Да или Нет."
)
INVALID_URGENT_WARNINGS_TEXT = "Некорректный ответ. Введите: Да или Нет."
NO_SAVED_CITY_TEXT = "Сначала сохраните подтверждённый город."
URGENT_WARNINGS_ENABLED_TEXT = "Срочные предупреждения включены."
URGENT_WARNINGS_DISABLED_TEXT = "Срочные предупреждения выключены."
URGENT_WARNINGS_SAVED_TEXT = "Настройка срочных предупреждений сохранена."
URGENT_WARNINGS_STORAGE_ERROR_TEXT = (
    "Сохранить настройку срочных предупреждений не удалось. Попробуйте позже."
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


def _parse_urgent_warnings_answer(text: str) -> bool | None:
    normalized = text.strip().casefold()
    if normalized == "да":
        return True
    if normalized == "нет":
        return False
    return None


def run_until_urgent_warnings(
    telegram_client: TelegramClient,
    storage: SQLiteSettingsStore,
) -> int:
    """Wait for one existing user and save the urgent-warning preference."""
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
                            text=URGENT_WARNINGS_STORAGE_ERROR_TEXT,
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
                        text=URGENT_WARNINGS_PROMPT,
                    )
                    print("Ожидание настройки срочных предупреждений...")
                    continue

                if message.chat_id != started_chat_id or message.text is None:
                    continue

                enabled = _parse_urgent_warnings_answer(message.text)
                if enabled is None:
                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=INVALID_URGENT_WARNINGS_TEXT,
                    )
                    continue

                try:
                    storage.save_urgent_warnings_enabled(started_chat_id, enabled)
                except StorageError:
                    print(
                        "Не удалось сохранить настройку срочных предупреждений.",
                        file=sys.stderr,
                    )
                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=URGENT_WARNINGS_STORAGE_ERROR_TEXT,
                    )
                    return 1

                telegram_client.send_message(
                    chat_id=started_chat_id,
                    text=(
                        URGENT_WARNINGS_ENABLED_TEXT
                        if enabled
                        else URGENT_WARNINGS_DISABLED_TEXT
                    ),
                )
                print(URGENT_WARNINGS_SAVED_TEXT)
                return 0
    except KeyboardInterrupt:
        print("Ожидание настройки срочных предупреждений остановлено.")
        return 130
