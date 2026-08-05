import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import ANY, Mock, call

from weather_alert_bot.city_handler import CITY_PROMPT, INVALID_CITY_TEXT
from weather_alert_bot.geocoded_city_handler import (
    GEOCODING_ERROR_TEXT,
    NO_MATCHES_TEXT,
    run_until_geocoded_city,
)
from weather_alert_bot.geocoding import GeocodingError, GeocodingLocation
from weather_alert_bot.telegram_api import TelegramMessage, TelegramUpdate


def update(
    update_id: int,
    text: str | None,
    *,
    chat_id: int = 42,
    chat_type: str = "private",
) -> TelegramUpdate:
    return TelegramUpdate(
        update_id=update_id,
        message=TelegramMessage(chat_id=chat_id, chat_type=chat_type, text=text),
    )


class FakeTelegramClient:
    def __init__(self, responses: list[object]) -> None:
        self.responses = iter(responses)
        self.get_updates_calls: list[dict[str, object]] = []
        self.send_message = Mock()

    def get_updates(self, **kwargs: object) -> list[TelegramUpdate]:
        self.get_updates_calls.append(kwargs)
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return response


def location(**overrides: object) -> GeocodingLocation:
    values: dict[str, object] = {
        "id": 1,
        "name": "Москва",
        "latitude": 55.752220123,
        "longitude": 37.615560987,
        "timezone": "Europe/Moscow",
        "country_code": "RU",
        "country": "Россия",
        "admin1": "Москва",
        "population": 100,
    }
    values.update(overrides)
    return GeocodingLocation(**values)


class GeocodedCityHandlerTest(unittest.TestCase):
    def test_old_updates_are_discarded_without_reply_or_geocoding(self) -> None:
        client = FakeTelegramClient(
            [
                [update(10, "/start", chat_id=900), update(11, "СтарыйГород", chat_id=900)],
                [],
                [update(10, "/start", chat_id=900), update(12, "/start"), update(13, " Москва ")],
            ]
        )
        geocoder = Mock()
        geocoder.search.return_value = (location(),)
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_geocoded_city(client, geocoder)

        self.assertEqual(result, 0)
        geocoder.search.assert_called_once_with("Москва", count=5, language="ru")
        self.assertEqual(client.send_message.call_count, 2)
        self.assertEqual(client.send_message.call_args_list[0], call(chat_id=42, text=CITY_PROMPT))
        self.assertNotIn("СтарыйГород", output.getvalue())
        self.assertNotIn("Москва", output.getvalue())
        self.assertEqual(
            client.get_updates_calls,
            [
                {"offset": None, "timeout": 0, "limit": 100},
                {"offset": 12, "timeout": 0, "limit": 100},
                {"offset": 12, "timeout": 30, "limit": 100},
            ],
        )

    def test_only_new_private_start_and_same_chat_text_are_used(self) -> None:
        client = FakeTelegramClient(
            [
                [],
                [
                    update(20, "обычный текст", chat_id=100),
                    update(21, "/start", chat_id=101, chat_type="group"),
                    TelegramUpdate(update_id=22, message=None),
                    update(23, "/start@weather_storm_alert_bot"),
                ],
                [
                    update(24, "Москва", chat_id=100),
                    update(25, None),
                    update(26, "Санкт-Петербург"),
                ],
            ]
        )
        geocoder = Mock()
        geocoder.search.return_value = (location(name="Санкт-Петербург"),)

        result = run_until_geocoded_city(client, geocoder)

        self.assertEqual(result, 0)
        geocoder.search.assert_called_once_with("Санкт-Петербург", count=5, language="ru")
        self.assertEqual(client.send_message.call_count, 2)
        self.assertEqual(client.get_updates_calls[1]["offset"], None)
        self.assertEqual(client.get_updates_calls[2]["offset"], 24)

    def test_duplicate_update_id_is_not_processed_twice(self) -> None:
        client = FakeTelegramClient(
            [[], [update(30, "/start")], [update(30, "/start"), update(31, "Москва")]]
        )
        geocoder = Mock()
        geocoder.search.return_value = (location(),)

        result = run_until_geocoded_city(client, geocoder)

        self.assertEqual(result, 0)
        geocoder.search.assert_called_once()
        self.assertEqual(client.get_updates_calls[2]["offset"], 31)

    def test_invalid_city_uses_existing_error_and_then_continues(self) -> None:
        client = FakeTelegramClient(
            [[], [update(40, "/start")], [update(41, "/help"), update(42, "12345"), update(43, " New York ")]]
        )
        geocoder = Mock()
        geocoder.search.return_value = (location(name="New York", admin1=None, country="США"),)

        result = run_until_geocoded_city(client, geocoder)

        self.assertEqual(result, 0)
        geocoder.search.assert_called_once_with("New York", count=5, language="ru")
        self.assertEqual(
            client.send_message.call_args_list,
            [
                call(chat_id=42, text=CITY_PROMPT),
                call(chat_id=42, text=INVALID_CITY_TEXT),
                call(chat_id=42, text=INVALID_CITY_TEXT),
                call(chat_id=42, text=ANY),
            ],
        )

    def test_empty_result_allows_another_city(self) -> None:
        client = FakeTelegramClient(
            [[], [update(50, "/start")], [update(51, "Пусто")], [update(52, "Москва")]]
        )
        geocoder = Mock()
        geocoder.search.side_effect = [(), (location(),)]
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_geocoded_city(client, geocoder)

        self.assertEqual(result, 0)
        self.assertEqual(
            geocoder.search.call_args_list,
            [
                call("Пусто", count=5, language="ru"),
                call("Москва", count=5, language="ru"),
            ],
        )
        self.assertEqual(client.send_message.call_args_list[1], call(chat_id=42, text=NO_MATCHES_TEXT))
        self.assertIn("Совпадения не найдены. Ожидание другого названия города...", output.getvalue())
        self.assertNotIn("Пусто", output.getvalue())

    def test_geocoding_error_is_safe_and_returns_one(self) -> None:
        client = FakeTelegramClient([[], [update(60, "/start")], [update(61, "Москва")]])
        geocoder = Mock()
        geocoder.search.side_effect = GeocodingError("https://internal.example/city Москва {\"x\":1}")
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = run_until_geocoded_city(client, geocoder)

        self.assertEqual(result, 1)
        self.assertEqual(client.send_message.call_args_list[-1], call(chat_id=42, text=GEOCODING_ERROR_TEXT))
        self.assertEqual(stderr.getvalue(), "Ошибка геокодирования города.\n")
        self.assertNotIn("Москва", stderr.getvalue())
        self.assertNotIn("https://", stderr.getvalue())
        self.assertNotIn("{", stderr.getvalue())
        self.assertNotIn("Traceback", stdout.getvalue() + stderr.getvalue())

    def test_success_uses_first_location_and_hides_internal_fields(self) -> None:
        client = FakeTelegramClient([[], [update(70, "/start")], [update(71, "Москва")]])
        geocoder = Mock()
        geocoder.search.return_value = (
            location(),
            location(id=2, name="Другой вариант", population=999),
        )
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            result = run_until_geocoded_city(client, geocoder)

        self.assertEqual(result, 0)
        sent_text = client.send_message.call_args_list[-1].kwargs["text"]
        self.assertIn("Москва, Москва, Россия", sent_text)
        self.assertIn("Координаты: 55.752220, 37.615561", sent_text)
        self.assertIn("Часовой пояс: Europe/Moscow", sent_text)
        self.assertIn("Open-Meteo", sent_text)
        self.assertIn("GeoNames", sent_text)
        self.assertIn("Город пока не сохранён.", sent_text)
        self.assertNotIn("Другой вариант", sent_text)
        self.assertNotIn("100", sent_text)
        self.assertNotIn("id", sent_text.lower())
        self.assertNotIn("Москва", stdout.getvalue())
        self.assertNotIn("55.752220", stdout.getvalue())

    def test_keyboard_interrupt_returns_130_without_traceback(self) -> None:
        client = FakeTelegramClient([[], KeyboardInterrupt()])
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_geocoded_city(client, Mock())

        self.assertEqual(result, 130)
        self.assertEqual(
            output.getvalue(),
            "Ожидание новой команды /start...\n"
            "Ожидание города с геокодированием остановлено.\n",
        )
        self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main()
