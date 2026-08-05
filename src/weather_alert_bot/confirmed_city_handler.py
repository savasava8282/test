from __future__ import annotations

from collections.abc import Iterable
import sys

from weather_alert_bot.city_handler import (
    CITY_PROMPT,
    INVALID_CITY_TEXT,
    START_COMMANDS,
    is_valid_city,
)
from weather_alert_bot.geocoding import (
    GeocodingError,
    GeocodingLocation,
    OpenMeteoGeocodingClient,
)
from weather_alert_bot.telegram_api import TelegramClient, TelegramUpdate


NO_MATCHES_TEXT = "Подходящие города не найдены. Проверьте название и отправьте город ещё раз."
GEOCODING_ERROR_TEXT = "Не удалось проверить город через сервис геокодирования. Попробуйте позже."
CONFIRMATION_TEXT = "Город подтверждён."
REJECTED_TEXT = "Хорошо. Напишите название другого города."
UNRECOGNIZED_ANSWER_TEXT = "Не удалось распознать ответ. Напишите «Да» или «Нет»."


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


def _format_location(location: GeocodingLocation) -> str:
    place_parts = [location.name]
    if location.admin1:
        place_parts.append(location.admin1)
    place_parts.append(location.country)
    return (
        "Найден первый подходящий вариант:\n\n"
        f"{', '.join(place_parts)}\n"
        f"Координаты: {location.latitude:.6f}, {location.longitude:.6f}\n"
        f"Часовой пояс: {location.timezone}\n\n"
        "Источник геокодирования: Open-Meteo; данные о локациях: GeoNames.\n\n"
        "Это ваш город? Ответьте «Да» или «Нет».\n\n"
        "Город пока не сохранён."
    )


def run_until_confirmed_city(
    telegram_client: TelegramClient,
    geocoding_client: OpenMeteoGeocodingClient,
) -> int:
    """Wait for a city, ask for confirmation, and finish after one confirmation."""
    offset: int | None = None
    seen_update_ids: set[int] = set()
    started_chat_id: int | None = None
    candidate: GeocodingLocation | None = None

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

                    telegram_client.send_message(chat_id=message.chat_id, text=CITY_PROMPT)
                    started_chat_id = message.chat_id
                    print("Команда /start получена.")
                    print("Ожидание названия города...")
                    continue

                if message.chat_id != started_chat_id or message.text is None:
                    continue

                if candidate is None:
                    city = message.text.strip()
                    if not is_valid_city(message.text):
                        telegram_client.send_message(
                            chat_id=started_chat_id,
                            text=INVALID_CITY_TEXT,
                        )
                        continue

                    try:
                        locations = geocoding_client.search(city, count=5, language="ru")
                    except GeocodingError:
                        print("Ошибка геокодирования города.", file=sys.stderr)
                        telegram_client.send_message(
                            chat_id=started_chat_id,
                            text=GEOCODING_ERROR_TEXT,
                        )
                        return 1

                    if not locations:
                        telegram_client.send_message(
                            chat_id=started_chat_id,
                            text=NO_MATCHES_TEXT,
                        )
                        print("Совпадения не найдены. Ожидание другого названия города...")
                        continue

                    candidate = locations[0]
                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=_format_location(candidate),
                    )
                    print("Название города получено.")
                    print("Геокодирование выполнено.")
                    print("Ожидание подтверждения города...")
                    continue

                answer = message.text.strip().casefold()
                if answer == "да":
                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=CONFIRMATION_TEXT,
                    )
                    print("Город подтверждён.")
                    print("Подтверждение отправлено.")
                    return 0
                if answer == "нет":
                    telegram_client.send_message(
                        chat_id=started_chat_id,
                        text=REJECTED_TEXT,
                    )
                    candidate = None
                    print("Город отклонён. Ожидание другого названия города...")
                    continue

                telegram_client.send_message(
                    chat_id=started_chat_id,
                    text=UNRECOGNIZED_ANSWER_TEXT,
                )
    except KeyboardInterrupt:
        print("Ожидание подтверждения города остановлено.")
        return 130
