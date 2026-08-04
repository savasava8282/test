import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, call

from weather_alert_bot.city_handler import (
    CITY_CONFIRMATION_TEMPLATE,
    CITY_PROMPT,
    INVALID_CITY_TEXT,
    is_valid_city,
    run_until_city,
)
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


class FakeClient:
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


class CityValidationTest(unittest.TestCase):
    def test_valid_city_examples(self) -> None:
        for city in (
            "Москва",
            "Санкт-Петербург",
            "New York",
            "'s-Hertogenbosch",
            "Ростов-на-Дону",
        ):
            with self.subTest(city=city):
                self.assertTrue(is_valid_city(city))

    def test_invalid_city_examples(self) -> None:
        invalid_values = (
            "",
            "   ",
            "Я",
            "A" * 101,
            "12345",
            "Москва\nЦентр",
            "Москва\tЦентр",
            "/help",
            "/start",
        )
        for city in invalid_values:
            with self.subTest(city=city):
                self.assertFalse(is_valid_city(city))


class CityHandlerTest(unittest.TestCase):
    def test_old_updates_are_discarded_and_new_start_and_city_are_processed(self) -> None:
        client = FakeClient(
            [
                [update(10, "/start", chat_id=900)],
                [],
                [
                    update(10, "/start", chat_id=900),
                    update(11, "/start", chat_id=42),
                    update(12, "  Москва  ", chat_id=42),
                ],
            ]
        )
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_city(client)

        self.assertEqual(result, 0)
        client.send_message.assert_has_calls(
            [
                call(chat_id=42, text=CITY_PROMPT),
                call(
                    chat_id=42,
                    text=CITY_CONFIRMATION_TEMPLATE.format(city="Москва"),
                ),
            ]
        )
        self.assertEqual(client.send_message.call_count, 2)
        self.assertEqual(
            client.get_updates_calls,
            [
                {"offset": None, "timeout": 0, "limit": 100},
                {"offset": 11, "timeout": 0, "limit": 100},
                {"offset": 11, "timeout": 30, "limit": 100},
            ],
        )
        self.assertEqual(
            output.getvalue(),
            "Ожидание новой команды /start...\n"
            "Команда /start получена.\n"
            "Ожидание названия города...\n"
            "Название города получено.\n"
            "Подтверждение отправлено.\n",
        )
        self.assertNotIn("900", output.getvalue())
        self.assertNotIn("Москва", output.getvalue())

    def test_filters_until_start_then_accepts_only_same_private_chat(self) -> None:
        client = FakeClient(
            [
                [],
                [
                    update(20, "hello", chat_id=100),
                    update(21, "/help", chat_id=101),
                    update(22, "/start", chat_id=102, chat_type="group"),
                    TelegramUpdate(update_id=23, message=None),
                    update(24, "/start@weather_storm_alert_bot", chat_id=42),
                ],
                [
                    update(25, "Москва", chat_id=100),
                    update(26, None, chat_id=42),
                    update(27, "Санкт-Петербург", chat_id=42),
                ],
            ]
        )

        output = io.StringIO()
        with redirect_stdout(output):
            result = run_until_city(client)

        self.assertEqual(result, 0)
        client.send_message.assert_has_calls(
            [
                call(chat_id=42, text=CITY_PROMPT),
                call(
                    chat_id=42,
                    text=CITY_CONFIRMATION_TEMPLATE.format(city="Санкт-Петербург"),
                ),
            ]
        )
        self.assertEqual(client.send_message.call_count, 2)
        self.assertEqual(client.get_updates_calls[1]["offset"], None)
        self.assertEqual(client.get_updates_calls[2]["offset"], 25)
        self.assertNotIn("100", output.getvalue())
        self.assertNotIn("hello", output.getvalue())
        self.assertNotIn("Санкт-Петербург", output.getvalue())
        self.assertNotIn("123456789:TEST_TOKEN_NOT_REAL", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())

    def test_invalid_city_gets_exact_error_and_handler_continues(self) -> None:
        client = FakeClient(
            [
                [],
                [update(30, "/start")],
                [update(31, "/start"), update(32, "12345"), update(33, " New York ")],
            ]
        )

        result = run_until_city(client)

        self.assertEqual(result, 0)
        client.send_message.assert_has_calls(
            [
                call(chat_id=42, text=CITY_PROMPT),
                call(chat_id=42, text=INVALID_CITY_TEXT),
                call(chat_id=42, text=INVALID_CITY_TEXT),
                call(
                    chat_id=42,
                    text=CITY_CONFIRMATION_TEMPLATE.format(city="New York"),
                ),
            ]
        )
        self.assertEqual(client.send_message.call_count, 4)

    def test_duplicate_update_id_is_not_processed_twice_and_offset_moves_forward(self) -> None:
        client = FakeClient(
            [
                [],
                [update(40, "/start")],
                [update(40, "/start"), update(41, "Москва")],
            ]
        )

        result = run_until_city(client)

        self.assertEqual(result, 0)
        self.assertEqual(client.send_message.call_count, 2)
        self.assertEqual(client.get_updates_calls[2]["offset"], 41)

    def test_keyboard_interrupt_returns_130_without_traceback(self) -> None:
        client = FakeClient([[], KeyboardInterrupt()])
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_city(client)

        self.assertEqual(result, 130)
        self.assertEqual(
            output.getvalue(),
            "Ожидание новой команды /start...\nОжидание города остановлено.\n",
        )
        self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main()
