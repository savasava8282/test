from __future__ import annotations

from collections.abc import Iterable
import unicodedata

from weather_alert_bot.telegram_api import TelegramClient, TelegramUpdate


CITY_PROMPT = "Здравствуйте! Я бот «Погода и магнитные бури».\n\nНапишите название вашего города одним сообщением."
INVALID_CITY_TEXT = "Не удалось принять название города. Напишите его обычным текстом, например: Москва."
CITY_CONFIRMATION_TEMPLATE = (
    "Город принят: {city}\n\n"
    "Проверка города и сохранение настроек будут добавлены на следующих этапах."
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


def _has_forbidden_characters(text: str) -> bool:
    return any(
        character in "\r\n\t\u2028\u2029"
        or unicodedata.category(character).startswith("C")
        for character in text
    )


def is_valid_city(text: str) -> bool:
    """Validate a city name locally without checking external sources."""
    city = text.strip()
    if not city or not 2 <= len(city) <= 100:
        return False
    if _has_forbidden_characters(text):
        return False
    if city.startswith("/"):
        return False
    return any(character.isalpha() for character in city)


def run_until_city(client: TelegramClient) -> int:
    """Wait for one new private /start and one valid city from that chat."""
    offset: int | None = None
    seen_update_ids: set[int] = set()
    started_chat_id: int | None = None

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

                    client.send_message(chat_id=message.chat_id, text=CITY_PROMPT)
                    started_chat_id = message.chat_id
                    print("Команда /start получена.")
                    print("Ожидание названия города...")
                    continue

                if message.chat_id != started_chat_id or message.text is None:
                    continue

                city = message.text.strip()
                if not is_valid_city(message.text):
                    client.send_message(chat_id=started_chat_id, text=INVALID_CITY_TEXT)
                    continue

                client.send_message(
                    chat_id=started_chat_id,
                    text=CITY_CONFIRMATION_TEMPLATE.format(city=city),
                )
                print("Название города получено.")
                print("Подтверждение отправлено.")
                return 0
    except KeyboardInterrupt:
        print("Ожидание города остановлено.")
        return 130
