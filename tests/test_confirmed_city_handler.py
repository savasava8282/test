import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, call

from weather_alert_bot.city_handler import CITY_PROMPT, INVALID_CITY_TEXT
from weather_alert_bot.confirmed_city_handler import (
    CONFIRMATION_TEXT,
    GEOCODING_ERROR_TEXT,
    NO_MATCHES_TEXT,
    REJECTED_TEXT,
    UNRECOGNIZED_ANSWER_TEXT,
    run_until_confirmed_city,
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


class ConfirmedCityHandlerTest(unittest.TestCase):
    def test_cleanup_ignores_old_updates_and_duplicate_ids(self) -> None:
        client = FakeTelegramClient(
            [
                [update(1, "/start", chat_id=900), update(2, "СтарыйГород", chat_id=900)],
                [],
                [
                    update(1, "/start", chat_id=900),
                    update(3, "/start@weather_storm_alert_bot"),
                    update(4, "Москва"),
                    update(4, "Москва"),
                ],
                [update(5, "да")],
            ]
        )
        geocoder = Mock()
        geocoder.search.return_value = (location(),)
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_confirmed_city(client, geocoder)

        self.assertEqual(result, 0)
        geocoder.search.assert_called_once_with("Москва", count=5, language="ru")
        self.assertEqual(client.send_message.call_count, 3)
        self.assertEqual(client.send_message.call_args_list[0], call(chat_id=42, text=CITY_PROMPT))
        self.assertEqual(
            client.send_message.call_args_list[-1],
            call(chat_id=42, text="Город подтверждён.\n\nГород пока не сохранён."),
        )
        self.assertEqual(
            client.get_updates_calls,
            [
                {"offset": None, "timeout": 0, "limit": 100},
                {"offset": 3, "timeout": 0, "limit": 100},
                {"offset": 3, "timeout": 30, "limit": 100},
                {"offset": 5, "timeout": 30, "limit": 100},
            ],
        )
        self.assertNotIn("СтарыйГород", output.getvalue())

    def test_filters_start_private_chat_and_text_messages(self) -> None:
        client = FakeTelegramClient(
            [
                [],
                [
                    update(10, "обычный текст"),
                    update(11, "/start", chat_id=100, chat_type="group"),
                    TelegramUpdate(update_id=12, message=None),
                    update(13, "/start@weather_storm_alert_bot"),
                ],
                [
                    update(14, "Москва", chat_id=100),
                    update(15, None),
                    update(16, "  Санкт-Петербург  "),
                ],
                [update(17, "Да")],
            ]
        )
        geocoder = Mock()
        geocoder.search.return_value = (location(name="Санкт-Петербург", admin1=None),)

        result = run_until_confirmed_city(client, geocoder)

        self.assertEqual(result, 0)
        geocoder.search.assert_called_once_with("Санкт-Петербург", count=5, language="ru")
        self.assertEqual(client.send_message.call_args_list[0], call(chat_id=42, text=CITY_PROMPT))
        self.assertEqual(client.send_message.call_args_list[-1], call(chat_id=42, text=CONFIRMATION_TEXT))

    def test_invalid_city_is_rejected_and_commands_are_not_geocoded(self) -> None:
        client = FakeTelegramClient(
            [
                [],
                [update(20, "/start")],
                [update(21, "/help"), update(22, "12345"), update(23, " New York ")],
                [update(24, "нет")],
                [update(25, "Москва")],
                [update(26, "да")],
            ]
        )
        geocoder = Mock()
        geocoder.search.side_effect = [(location(name="New York", admin1=None, country="США"),), (location(),)]

        result = run_until_confirmed_city(client, geocoder)

        self.assertEqual(result, 0)
        self.assertEqual(
            geocoder.search.call_args_list,
            [call("New York", count=5, language="ru"), call("Москва", count=5, language="ru")],
        )
        self.assertEqual(client.send_message.call_args_list[1], call(chat_id=42, text=INVALID_CITY_TEXT))
        self.assertEqual(client.send_message.call_args_list[2], call(chat_id=42, text=INVALID_CITY_TEXT))
        self.assertEqual(client.send_message.call_args_list[4], call(chat_id=42, text=REJECTED_TEXT))

    def test_candidate_uses_first_result_and_safe_display(self) -> None:
        client = FakeTelegramClient([[], [update(30, "/start")], [update(31, "Москва")], [update(32, "Да")]])
        geocoder = Mock()
        geocoder.search.return_value = (
            location(),
            location(id=2, name="Другой вариант", population=999),
        )
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            result = run_until_confirmed_city(client, geocoder)

        self.assertEqual(result, 0)
        candidate_text = client.send_message.call_args_list[1].kwargs["text"]
        self.assertIn("Москва, Москва, Россия", candidate_text)
        self.assertIn("Координаты: 55.752220, 37.615561", candidate_text)
        self.assertIn("Часовой пояс: Europe/Moscow", candidate_text)
        self.assertIn("Источник геокодирования: Open-Meteo; данные о локациях: GeoNames.", candidate_text)
        self.assertIn("Это ваш город? Ответьте «Да» или «Нет».", candidate_text)
        self.assertIn("Город пока не сохранён.", candidate_text)
        self.assertNotIn("Другой вариант", candidate_text)
        self.assertNotIn("population", candidate_text.lower())
        self.assertNotIn("999", candidate_text)
        self.assertNotIn("id", candidate_text.lower())
        self.assertNotIn("Москва", stdout.getvalue())
        self.assertNotIn("55.752220", stdout.getvalue())

    def test_yes_accepts_case_and_outer_spaces(self) -> None:
        client = FakeTelegramClient([[], [update(40, "/start")], [update(41, "Москва")], [update(42, "  ДА  ")]])
        geocoder = Mock()
        geocoder.search.return_value = (location(),)
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_confirmed_city(client, geocoder)

        self.assertEqual(result, 0)
        geocoder.search.assert_called_once()
        self.assertEqual(client.send_message.call_args_list[-1], call(chat_id=42, text=CONFIRMATION_TEXT))
        self.assertIn("Город подтверждён.\nПодтверждение отправлено.\n", output.getvalue())

    def test_no_returns_to_city_input_without_second_start(self) -> None:
        client = FakeTelegramClient(
            [[], [update(50, "/start")], [update(51, "Москва")], [update(52, "Нет")], [update(53, "Сочи")], [update(54, "да")]]
        )
        geocoder = Mock()
        geocoder.search.side_effect = [(location(),), (location(name="Сочи", admin1=None),)]
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_confirmed_city(client, geocoder)

        self.assertEqual(result, 0)
        self.assertEqual(geocoder.search.call_count, 2)
        self.assertEqual(geocoder.search.call_args_list[1], call("Сочи", count=5, language="ru"))
        self.assertEqual(client.send_message.call_args_list[2], call(chat_id=42, text=REJECTED_TEXT))
        self.assertIn("Сочи", client.send_message.call_args_list[3].kwargs["text"])
        self.assertIn("Город отклонён. Ожидание другого названия города...", output.getvalue())

    def test_invalid_confirmation_does_not_change_candidate_or_geocode_again(self) -> None:
        client = FakeTelegramClient(
            [
                [],
                [update(60, "/start")],
                [update(61, "Москва")],
                [update(62, "да."), update(63, "нет."), update(64, "yes"), update(65, "no"), update(66, "/start"), update(67, "да")],
            ]
        )
        geocoder = Mock()
        geocoder.search.return_value = (location(),)

        result = run_until_confirmed_city(client, geocoder)

        self.assertEqual(result, 0)
        geocoder.search.assert_called_once()
        self.assertEqual(
            [item.kwargs["text"] for item in client.send_message.call_args_list[2:6]],
            [UNRECOGNIZED_ANSWER_TEXT] * 4,
        )
        self.assertEqual(client.send_message.call_args_list[-1], call(chat_id=42, text=CONFIRMATION_TEXT))

    def test_other_chat_and_group_answers_are_ignored(self) -> None:
        client = FakeTelegramClient(
            [[], [update(70, "/start")], [update(71, "Москва")], [update(72, "Да", chat_id=99), update(73, "Нет", chat_type="group")], [update(74, "Да")]]
        )
        geocoder = Mock()
        geocoder.search.return_value = (location(),)

        self.assertEqual(run_until_confirmed_city(client, geocoder), 0)
        self.assertEqual(client.send_message.call_args_list[-1], call(chat_id=42, text=CONFIRMATION_TEXT))
        self.assertEqual(client.send_message.call_count, 3)

    def test_empty_result_allows_successful_follow_up(self) -> None:
        client = FakeTelegramClient([[], [update(80, "/start")], [update(81, "Пусто")], [update(82, "Москва")], [update(83, "да")]])
        geocoder = Mock()
        geocoder.search.side_effect = [(), (location(),)]
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_confirmed_city(client, geocoder)

        self.assertEqual(result, 0)
        self.assertEqual(client.send_message.call_args_list[1], call(chat_id=42, text=NO_MATCHES_TEXT))
        self.assertIn("Совпадения не найдены. Ожидание другого названия города...", output.getvalue())
        self.assertEqual(geocoder.search.call_count, 2)

    def test_geocoding_error_is_safe(self) -> None:
        client = FakeTelegramClient([[], [update(90, "/start")], [update(91, "Москва")]])
        geocoder = Mock()
        geocoder.search.side_effect = GeocodingError('https://internal.example Москва {"x":1}')
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = run_until_confirmed_city(client, geocoder)

        self.assertEqual(result, 1)
        self.assertEqual(client.send_message.call_args_list[-1], call(chat_id=42, text=GEOCODING_ERROR_TEXT))
        self.assertEqual(stderr.getvalue(), "Ошибка геокодирования города.\n")
        self.assertNotIn("Москва", stderr.getvalue())
        self.assertNotIn("https://", stderr.getvalue())
        self.assertNotIn("{", stderr.getvalue())
        self.assertNotIn("Traceback", stdout.getvalue() + stderr.getvalue())

    def test_keyboard_interrupt_returns_130_without_traceback(self) -> None:
        client = FakeTelegramClient([[], KeyboardInterrupt()])
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_confirmed_city(client, Mock())

        self.assertEqual(result, 130)
        self.assertEqual(
            output.getvalue(),
            "Ожидание новой команды /start...\nОжидание подтверждения города остановлено.\n",
        )
        self.assertNotIn("Traceback", output.getvalue())

    def test_terminal_output_does_not_contain_user_or_candidate_data(self) -> None:
        client = FakeTelegramClient([[], [update(100, "/start")], [update(101, "СекретныйГород")], [update(102, "да")]])
        geocoder = Mock()
        geocoder.search.return_value = (location(name="НайденныйГород", latitude=1.23456789, longitude=2.34567891),)
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(run_until_confirmed_city(client, geocoder), 0)

        terminal = stdout.getvalue() + stderr.getvalue()
        for secret in ("123456789:TEST_TOKEN_NOT_REAL", "42", "СекретныйГород", "НайденныйГород", "1.234568", "2.345679", "https://", "{", "}", "Traceback"):
            self.assertNotIn(secret, terminal)


if __name__ == "__main__":
    unittest.main()
