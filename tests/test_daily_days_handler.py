import io
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, call, patch

from weather_alert_bot.daily_days_handler import (
    DAILY_DAYS_PROMPT,
    DAILY_DAYS_SAVED_TEXT,
    DAILY_DAYS_STORAGE_ERROR_TEXT,
    INVALID_DAILY_DAYS_TEXT,
    NO_SAVED_CITY_TEXT,
    run_until_daily_days,
)
from weather_alert_bot.geocoding import GeocodingLocation
from weather_alert_bot.storage import SQLiteSettingsStore, StorageError
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


def candidate() -> GeocodingLocation:
    return GeocodingLocation(
        id=1,
        name="Москва",
        latitude=55.75204,
        longitude=37.61781,
        timezone="Europe/Moscow",
        country_code="RU",
        country="Россия",
    )


class DailyDaysHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.storage = SQLiteSettingsStore(
            Path(self.temporary_directory.name) / "settings.sqlite3"
        )
        self.storage.save_confirmed_city(42, candidate())

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_success_normalizes_days_and_sends_exact_russian_text(self) -> None:
        client = FakeTelegramClient([[], [update(1, "/start")], [update(2, "5,1,3")]])
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_daily_days(client, self.storage)

        self.assertEqual(result, 0)
        settings = self.storage.get_user_settings(42)
        self.assertEqual(settings.daily_send_days, "1,3,5")
        self.assertEqual(settings.daily_send_time, "07:00")
        self.assertEqual(
            client.send_message.call_args_list,
            [
                call(chat_id=42, text=DAILY_DAYS_PROMPT),
                call(
                    chat_id=42,
                    text=DAILY_DAYS_SAVED_TEXT.format(daily_send_days="Пн, Ср, Пт"),
                ),
            ],
        )
        self.assertIn("Дни ежедневной отправки сохранены.\n", output.getvalue())
        self.assertNotIn("42", output.getvalue())

    def test_all_days_have_exact_ordered_success_text(self) -> None:
        client = FakeTelegramClient([[], [update(3, "/start")], [update(4, "1,2,3,4,5,6,7")]])

        self.assertEqual(run_until_daily_days(client, self.storage), 0)
        self.assertEqual(
            client.send_message.call_args_list[-1],
            call(
                chat_id=42,
                text="Дни ежедневной отправки сохранены: Пн, Вт, Ср, Чт, Пт, Сб, Вс.",
            ),
        )

    def test_invalid_values_do_not_mutate_and_then_valid_value_succeeds(self) -> None:
        self.storage.save_daily_send_time(42, "08:30")
        self.storage.save_daily_send_days(42, "6,7")
        invalid_values = (
            "",
            "   ",
            "0",
            "8",
            "1,8",
            "1,,2",
            "1-5",
            "Пн",
            "abc",
            "/start",
            "/help",
            "1,1",
        )
        client = FakeTelegramClient(
            [
                [],
                [update(10, "/start")],
                [update(index + 11, value) for index, value in enumerate(invalid_values)],
                [update(30, "1, 3, 5")],
            ]
        )

        self.assertEqual(run_until_daily_days(client, self.storage), 0)
        settings = self.storage.get_user_settings(42)
        self.assertEqual(settings.daily_send_days, "1,3,5")
        self.assertEqual(settings.daily_send_time, "08:30")
        invalid_messages = [
            item.kwargs["text"]
            for item in client.send_message.call_args_list
            if item.kwargs["text"] == INVALID_DAILY_DAYS_TEXT
        ]
        self.assertEqual(len(invalid_messages), len(invalid_values))

    def test_invalid_value_does_not_mutate_when_interrupted(self) -> None:
        self.storage.save_daily_send_days(42, "6,7")
        client = FakeTelegramClient(
            [[], [update(40, "/start")], [update(41, "1,1")], KeyboardInterrupt()]
        )

        self.assertEqual(run_until_daily_days(client, self.storage), 130)
        self.assertEqual(self.storage.get_user_settings(42).daily_send_days, "6,7")

    def test_old_updates_are_ignored(self) -> None:
        client = FakeTelegramClient(
            [
                [update(1, "/start"), update(2, "6,7")],
                [],
                [update(1, "/start"), update(3, "/start")],
                [update(4, "5,1,3")],
            ]
        )

        self.assertEqual(run_until_daily_days(client, self.storage), 0)
        self.assertEqual(self.storage.get_user_settings(42).daily_send_days, "1,3,5")

    def test_groups_and_other_chats_are_ignored(self) -> None:
        client = FakeTelegramClient(
            [
                [],
                [
                    update(10, "/start", chat_id=99, chat_type="group"),
                    update(11, "/start"),
                    update(12, "6,7", chat_id=99),
                    update(13, "6,7", chat_type="group"),
                ],
                [update(14, "6,7")],
            ]
        )

        self.assertEqual(run_until_daily_days(client, self.storage), 0)
        self.assertEqual(self.storage.get_user_settings(42).daily_send_days, "6,7")
        self.assertEqual(client.send_message.call_count, 2)

    def test_missing_city_sends_safe_message_and_does_not_create_row(self) -> None:
        client = FakeTelegramClient([[], [update(20, "/start", chat_id=700)]])

        self.assertEqual(run_until_daily_days(client, self.storage), 1)
        self.assertEqual(
            client.send_message.call_args_list,
            [call(chat_id=700, text=NO_SAVED_CITY_TEXT)],
        )
        self.assertIsNone(self.storage.get_user_settings(700))

    def test_storage_read_error_has_no_false_success(self) -> None:
        client = FakeTelegramClient([[], [update(30, "/start")]])

        with patch.object(
            self.storage,
            "get_user_settings",
            side_effect=StorageError("internal sqlite details"),
        ):
            result = run_until_daily_days(client, self.storage)

        self.assertEqual(result, 1)
        self.assertEqual(
            client.send_message.call_args_list[-1].kwargs["text"],
            DAILY_DAYS_STORAGE_ERROR_TEXT,
        )

    def test_storage_write_error_has_no_false_success_or_internal_details(self) -> None:
        client = FakeTelegramClient([[], [update(40, "/start")], [update(41, "1,2")]])
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.object(
            self.storage,
            "save_daily_send_days",
            side_effect=StorageError("internal sqlite details"),
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            result = run_until_daily_days(client, self.storage)

        self.assertEqual(result, 1)
        sent_texts = [item.kwargs["text"] for item in client.send_message.call_args_list]
        self.assertIn(DAILY_DAYS_STORAGE_ERROR_TEXT, sent_texts)
        self.assertNotIn(
            DAILY_DAYS_SAVED_TEXT.format(daily_send_days="Пн, Вт"), sent_texts
        )
        self.assertNotIn("internal sqlite details", stdout.getvalue() + stderr.getvalue())

    def test_keyboard_interrupt_returns_130_without_traceback(self) -> None:
        client = FakeTelegramClient([[], KeyboardInterrupt()])
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_daily_days(client, self.storage)

        self.assertEqual(result, 130)
        self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main()
