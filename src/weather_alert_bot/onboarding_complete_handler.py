from __future__ import annotations

from collections.abc import Iterable
import sys

from weather_alert_bot.settings_summary_handler import format_settings_summary
from weather_alert_bot.start_handler import START_COMMANDS
from weather_alert_bot.storage import SQLiteSettingsStore, StorageError
from weather_alert_bot.telegram_api import TelegramClient, TelegramUpdate


ONBOARDING_COMPLETE_PROMPT = (
    "Сохранить эти настройки и завершить первоначальную настройку? Ответьте: Да или Нет."
)
INVALID_ONBOARDING_COMPLETE_TEXT = "Некорректный ответ. Введите: Да или Нет."
NO_SAVED_CITY_TEXT = "Сначала сохраните подтверждённый город."
ONBOARDING_NOT_COMPLETED_TEXT = "Первоначальная настройка не завершена."
ONBOARDING_COMPLETED_TEXT = (
    "Настройки сохранены. Первоначальная настройка завершена."
)
ONBOARDING_COMPLETE_STORAGE_ERROR_TEXT = (
    "Завершить первоначальную настройку не удалось. Попробуйте позже."
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


def _parse_confirmation_answer(text: str) -> bool | None:
    normalized = text.strip().casefold()
    if normalized == "да":
        return True
    if normalized == "нет":
        return False
    return None


def run_until_onboarding_complete(
    telegram_client: TelegramClient,
    storage: SQLiteSettingsStore,
) -> int:
    """Wait for one private /start and explicitly finish onboarding."""
    offset: int | None = None
    seen_update_ids: set[int] = set()
    started_chat_id: int | None = None

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

                if started_chat_id is None:
                    if message.text not in START_COMMANDS:
                        continue

                    started_chat_id = message.chat_id
                    try:
                        settings = storage.get_user_settings(started_chat_id)
                    except StorageError:
                        telegram_client.send_message(
                            chat_id=started_chat_id,
                            text=ONBOARDING_COMPLETE_STORAGE_ERROR_TEXT,
                        )
                        return 1

                    print("Команда /start получена.")
                    if settings is None:
                        telegram_client.send_message(
                            chat_id=started_chat_id,
                            text=NO_SAVED_CITY_TEXT,
                        )
                        print("Сохранённый город не найден.")
                        return 1

                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=format_settings_summary(settings),
                    )
                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=ONBOARDING_COMPLETE_PROMPT,
                    )
                    print("Ожидание подтверждения завершения первоначальной настройки...")
                    continue

                if message.chat_id != started_chat_id or message.text is None:
                    continue

                completed = _parse_confirmation_answer(message.text)
                if completed is None:
                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=INVALID_ONBOARDING_COMPLETE_TEXT,
                    )
                    continue

                if not completed:
                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=ONBOARDING_NOT_COMPLETED_TEXT,
                    )
                    return 0

                try:
                    storage.mark_onboarding_completed(started_chat_id)
                except StorageError:
                    print(
                        "Не удалось завершить первоначальную настройку.",
                        file=sys.stderr,
                    )
                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=ONBOARDING_COMPLETE_STORAGE_ERROR_TEXT,
                    )
                    return 1

                telegram_client.send_message(
                    chat_id=started_chat_id,
                    text=ONBOARDING_COMPLETED_TEXT,
                )
                print("Первоначальная настройка завершена.")
                return 0
    except KeyboardInterrupt:
        print("Ожидание завершения первоначальной настройки остановлено.")
        return 130
