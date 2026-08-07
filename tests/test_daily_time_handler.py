import io
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, call, patch

from weather_alert_bot.daily_time_handler import (
    DAILY_TIME_PROMPT,
    DAILY_TIME_SAVED_TEXT,
    DAILY_TIME_STORAGE_ERROR_TEXT,
    INVALID_DAILY_TIME_TEXT,
    NO_SAVED_CITY_TEXT,
    run_until_daily_time,
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


class DailyTimeHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.storage = SQLiteSettingsStore(
            Path(self.temporary_directory.name) / "settings.sqlite3"
        )
        self.storage.save_confirmed_city(42, candidate())

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_success_saves_time_and_sends_exact_text(self) -> None:
        client = FakeTelegramClient([[], [update(1, "/start")], [update(2, "08:30")]])
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_daily_time(client, self.storage)

        self.assertEqual(result, 0)
        self.assertEqual(self.storage.get_user_settings(42).daily_send_time, "08:30")
        self.assertEqual(
            client.send_message.call_args_list,
            [
                call(chat_id=42, text=DAILY_TIME_PROMPT),
                call(chat_id=42, text=DAILY_TIME_SAVED_TEXT.format(daily_send_time="08:30")),
            ],
        )
        self.assertIn("Время ежедневной отправки сохранено.\n", output.getvalue())
        self.assertNotIn("42", output.getvalue())

    def test_midnight_and_last_minute_are_accepted(self) -> None:
        for time_value in ("00:00", "23:59"):
            with self.subTest(time_value=time_value):
                self.storage.save_daily_send_time(42, "07:00")
                client = FakeTelegramClient(
                    [[], [update(10, "/start")], [update(11, time_value)]]
                )

                self.assertEqual(run_until_daily_time(client, self.storage), 0)
                self.assertEqual(
                    self.storage.get_user_settings(42).daily_send_time,
                    time_value,
                )

    def test_invalid_times_do_not_change_saved_value_and_then_valid_time_succeeds(self) -> None:
        invalid_values = ("7:00", "24:00", "12:60", "07", "abc", "", "   ", "/help")
        client = FakeTelegramClient(
            [
                [],
                [update(20, "/start")],
                [update(index + 21, value) for index, value in enumerate(invalid_values)],
                [update(40, "09:15")],
            ]
        )

        self.assertEqual(run_until_daily_time(client, self.storage), 0)
        self.assertEqual(self.storage.get_user_settings(42).daily_send_time, "09:15")
        invalid_messages = [
            item.kwargs["text"]
            for item in client.send_message.call_args_list
            if item.kwargs["text"] == INVALID_DAILY_TIME_TEXT
        ]
        self.assertEqual(len(invalid_messages), len(invalid_values))

    def test_invalid_time_does_not_change_existing_value_if_interrupted(self) -> None:
        self.storage.save_daily_send_time(42, "18:30")
        client = FakeTelegramClient(
            [[], [update(50, "/start")], [update(51, "24:00")], KeyboardInterrupt()]
        )

        self.assertEqual(run_until_daily_time(client, self.storage), 130)
        self.assertEqual(self.storage.get_user_settings(42).daily_send_time, "18:30")

    def test_old_updates_are_ignored(self) -> None:
        client = FakeTelegramClient(
            [
                [update(1, "/start"), update(2, "18:30")],
                [],
                [update(1, "/start"), update(3, "/start"), update(4, "07:15")],
            ]
        )

        self.assertEqual(run_until_daily_time(client, self.storage), 0)
        self.assertEqual(self.storage.get_user_settings(42).daily_send_time, "07:15")
        self.assertEqual(
            client.send_message.call_args_list[-1],
            call(chat_id=42, text=DAILY_TIME_SAVED_TEXT.format(daily_send_time="07:15")),
        )

    def test_groups_and_other_chats_are_ignored(self) -> None:
        client = FakeTelegramClient(
            [
                [],
                [
                    update(60, "/start", chat_id=99, chat_type="group"),
                    update(61, "/start"),
                    update(62, "08:00", chat_id=99),
                    update(63, "08:00", chat_type="group"),
                ],
                [update(64, "08:00")],
            ]
        )

        self.assertEqual(run_until_daily_time(client, self.storage), 0)
        self.assertEqual(self.storage.get_user_settings(42).daily_send_time, "08:00")
        self.assertEqual(client.send_message.call_count, 2)

    def test_missing_city_sends_safe_message_and_does_not_create_row(self) -> None:
        client = FakeTelegramClient([[], [update(70, "/start", chat_id=700)]])

        self.assertEqual(run_until_daily_time(client, self.storage), 1)
        self.assertEqual(
            client.send_message.call_args_list,
            [call(chat_id=700, text=NO_SAVED_CITY_TEXT)],
        )
        self.assertIsNone(self.storage.get_user_settings(700))

    def test_storage_error_has_no_false_success_message(self) -> None:
        client = FakeTelegramClient([[], [update(80, "/start")], [update(81, "08:30")]])
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.object(
            self.storage,
            "save_daily_send_time",
            side_effect=StorageError("internal sqlite details"),
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            result = run_until_daily_time(client, self.storage)

        self.assertEqual(result, 1)
        sent_texts = [item.kwargs["text"] for item in client.send_message.call_args_list]
        self.assertIn(DAILY_TIME_STORAGE_ERROR_TEXT, sent_texts)
        self.assertNotIn(DAILY_TIME_SAVED_TEXT.format(daily_send_time="08:30"), sent_texts)
        self.assertNotIn("internal sqlite details", stdout.getvalue() + stderr.getvalue())

    def test_read_storage_error_has_no_success_message(self) -> None:
        client = FakeTelegramClient([[], [update(90, "/start")]])

        with patch.object(
            self.storage,
            "get_user_settings",
            side_effect=StorageError("internal sqlite details"),
        ):
            self.assertEqual(run_until_daily_time(client, self.storage), 1)

        self.assertEqual(client.send_message.call_args_list[-1].kwargs["text"], DAILY_TIME_STORAGE_ERROR_TEXT)

    def test_keyboard_interrupt_returns_130_without_traceback(self) -> None:
        client = FakeTelegramClient([[], KeyboardInterrupt()])
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_daily_time(client, self.storage)

        self.assertEqual(result, 130)
        self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main()
