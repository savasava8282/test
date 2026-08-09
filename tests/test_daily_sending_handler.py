import io
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, call, patch

from weather_alert_bot.daily_sending_handler import (
    DAILY_SENDING_DISABLED_TEXT,
    DAILY_SENDING_ENABLED_TEXT,
    DAILY_SENDING_PROMPT,
    DAILY_SENDING_SAVED_TEXT,
    DAILY_SENDING_STORAGE_ERROR_TEXT,
    INVALID_DAILY_SENDING_TEXT,
    NO_SAVED_CITY_TEXT,
    run_until_daily_sending,
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


class DailySendingHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.storage = SQLiteSettingsStore(
            Path(self.temporary_directory.name) / "settings.sqlite3"
        )
        self.storage.save_confirmed_city(42, candidate())

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_prompt_and_yes_save_true_and_finish(self) -> None:
        client = FakeTelegramClient([[], [update(1, "/start"), update(2, "  ДА  ")]])
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_daily_sending(client, self.storage)

        self.assertEqual(result, 0)
        self.assertEqual(
            client.send_message.call_args_list,
            [
                call(chat_id=42, text=DAILY_SENDING_PROMPT),
                call(chat_id=42, text=DAILY_SENDING_ENABLED_TEXT),
            ],
        )
        self.assertIn(f"{DAILY_SENDING_SAVED_TEXT}\n", output.getvalue())
        self.assertIs(self.storage.get_user_settings(42).daily_sending_enabled, True)

    def test_no_saves_false_for_no(self) -> None:
        client = FakeTelegramClient([[], [update(1, "/start")], [update(2, "Нет")]])

        self.assertEqual(run_until_daily_sending(client, self.storage), 0)
        self.assertEqual(
            client.send_message.call_args_list[-1],
            call(chat_id=42, text=DAILY_SENDING_DISABLED_TEXT),
        )
        self.assertIs(self.storage.get_user_settings(42).daily_sending_enabled, False)

    def test_invalid_input_is_rejected_and_handler_continues(self) -> None:
        client = FakeTelegramClient(
            [[], [update(1, "/start")], [update(2, "yes"), update(3, "да")]]
        )

        self.assertEqual(run_until_daily_sending(client, self.storage), 0)
        sent_texts = [item.kwargs["text"] for item in client.send_message.call_args_list]
        self.assertIn(INVALID_DAILY_SENDING_TEXT, sent_texts)
        self.assertEqual(sent_texts[-1], DAILY_SENDING_ENABLED_TEXT)

    def test_old_updates_are_cleared_before_waiting_for_new_start(self) -> None:
        client = FakeTelegramClient(
            [
                [update(1, "/start"), update(2, "Да")],
                [],
                [update(3, "/start@weather_storm_alert_bot")],
                [update(4, "Да")],
            ]
        )

        self.assertEqual(run_until_daily_sending(client, self.storage), 0)
        self.assertEqual(client.get_updates_calls[0]["timeout"], 0)
        self.assertEqual(client.get_updates_calls[1]["timeout"], 0)
        self.assertEqual(client.get_updates_calls[2]["timeout"], 30)
        self.assertEqual(client.send_message.call_count, 2)

    def test_groups_and_other_chats_are_ignored_after_private_chat_lock(self) -> None:
        client = FakeTelegramClient(
            [
                [],
                [
                    update(1, "/start", chat_type="group"),
                    update(2, "/start"),
                    update(3, "Нет", chat_id=99),
                    update(4, "Нет", chat_type="group"),
                ],
                [update(5, "Нет")],
            ]
        )

        self.assertEqual(run_until_daily_sending(client, self.storage), 0)
        self.assertEqual(client.send_message.call_count, 2)
        self.assertTrue(all(item.kwargs["chat_id"] == 42 for item in client.send_message.call_args_list))
        self.assertIs(self.storage.get_user_settings(42).daily_sending_enabled, False)

    def test_missing_city_is_safe_and_does_not_create_row(self) -> None:
        client = FakeTelegramClient([[], [update(1, "/start", chat_id=700)]])

        self.assertEqual(run_until_daily_sending(client, self.storage), 1)
        self.assertEqual(
            client.send_message.call_args_list,
            [call(chat_id=700, text=NO_SAVED_CITY_TEXT)],
        )
        self.assertIsNone(self.storage.get_user_settings(700))

    def test_storage_read_error_is_safe(self) -> None:
        client = FakeTelegramClient([[], [update(1, "/start")]])

        with patch.object(
            self.storage,
            "get_user_settings",
            side_effect=StorageError("internal sqlite details"),
        ), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = run_until_daily_sending(client, self.storage)

        self.assertEqual(result, 1)
        self.assertEqual(client.send_message.call_args_list[-1].kwargs["text"], DAILY_SENDING_STORAGE_ERROR_TEXT)

    def test_storage_write_error_has_no_false_success_or_internal_details(self) -> None:
        client = FakeTelegramClient([[], [update(1, "/start")], [update(2, "Да")]])
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.object(
            self.storage,
            "save_daily_sending_enabled",
            side_effect=StorageError("internal sqlite details"),
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            result = run_until_daily_sending(client, self.storage)

        self.assertEqual(result, 1)
        sent_texts = [item.kwargs["text"] for item in client.send_message.call_args_list]
        self.assertIn(DAILY_SENDING_STORAGE_ERROR_TEXT, sent_texts)
        self.assertNotIn(DAILY_SENDING_ENABLED_TEXT, sent_texts)
        self.assertNotIn("internal sqlite details", stdout.getvalue() + stderr.getvalue())

    def test_keyboard_interrupt_is_safe(self) -> None:
        client = FakeTelegramClient([[], KeyboardInterrupt()])
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_daily_sending(client, self.storage)

        self.assertEqual(result, 130)
        self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main()
