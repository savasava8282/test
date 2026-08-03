from __future__ import annotations

from collections.abc import Iterable

from weather_alert_bot.telegram_api import TelegramClient, TelegramUpdate


WELCOME_TEXT = (
    "Здравствуйте! Я бот «Погода и магнитные бури».\n\n"
    "Подключение к Telegram работает. Настройка города и погодные функции будут "
    "добавлены на следующих этапах."
)
START_COMMANDS = {"/start", "/start@weather_storm_alert_bot"}


def _next_offset(current_offset: int | None, updates: Iterable[TelegramUpdate]) -> int | None:
    update_ids = [update.update_id for update in updates]
    if not update_ids:
        return current_offset
    candidate = max(update_ids) + 1
    if current_offset is None:
        return candidate
    return max(current_offset, candidate)


def run_until_start(client: TelegramClient) -> int:
    """Discard queued updates, then answer one new private /start command."""
    offset: int | None = None
    seen_update_ids: set[int] = set()

    try:
        while True:
            old_updates = client.get_updates(offset=offset, timeout=0, limit=100)
            offset = _next_offset(offset, old_updates)
            seen_update_ids.update(update.update_id for update in old_updates)
            if not old_updates:
                break

        print("Ожидание новой команды /start...")

        while True:
            updates = client.get_updates(offset=offset, timeout=30, limit=100)
            for update in updates:
                offset = _next_offset(offset, (update,))
                if update.update_id in seen_update_ids:
                    continue
                seen_update_ids.add(update.update_id)

                message = update.message
                if message is None:
                    continue
                if message.chat_type != "private":
                    continue
                if message.text not in START_COMMANDS:
                    continue

                client.send_message(chat_id=message.chat_id, text=WELCOME_TEXT)
                print("Команда /start получена.")
                print("Приветственное сообщение отправлено.")
                return 0
    except KeyboardInterrupt:
        print("Ожидание /start остановлено.")
        return 130
