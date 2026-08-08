import io
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, call, patch

from weather_alert_bot.geocoding import GeocodingLocation
from weather_alert_bot.storage import SQLiteSettingsStore, StorageError
from weather_alert_bot.telegram_api import TelegramMessage, TelegramUpdate
from weather_alert_bot.urgent_warnings_handler import (
    INVALID_URGENT_WARNINGS_TEXT,
    NO_SAVED_CITY_TEXT,
    URGENT_WARNINGS_DISABLED_TEXT,
    URGENT_WARNINGS_ENABLED_TEXT,
    URGENT_WARNINGS_PROMPT,
    URGENT_WARNINGS_SAVED_TEXT,
    URGENT_WARNINGS_STORAGE_ERROR_TEXT,
    run_until_urgent_warnings,
)


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


class UrgentWarningsHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.storage = SQLiteSettingsStore(
            Path(self.temporary_directory.name) / "settings.sqlite3"
        )
        self.storage.save_confirmed_city(42, candidate())

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_yes_saves_true_and_sends_exact_text(self) -> None:
        client = FakeTelegramClient([[], [update(1, "/start")], [update(2, "Да")]])
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_urgent_warnings(client, self.storage)

        self.assertEqual(result, 0)
        self.assertIs(self.storage.get_user_settings(42).urgent_warnings_enabled, True)
        self.assertEqual(
            client.send_message.call_args_list,
            [
                call(chat_id=42, text=URGENT_WARNINGS_PROMPT),
                call(chat_id=42, text=URGENT_WARNINGS_ENABLED_TEXT),
            ],
        )
        self.assertIn(f"{URGENT_WARNINGS_SAVED_TEXT}\n", output.getvalue())
        self.assertNotIn("42", output.getvalue())

    def test_no_saves_false_and_sends_exact_text(self) -> None:
        client = FakeTelegramClient([[], [update(1, "/start")], [update(2, "Нет")]])

        self.assertEqual(run_until_urgent_warnings(client, self.storage), 0)
        self.assertIs(self.storage.get_user_settings(42).urgent_warnings_enabled, False)
        self.assertEqual(
            client.send_message.call_args_list[-1],
            call(chat_id=42, text=URGENT_WARNINGS_DISABLED_TEXT),
        )

    def test_answers_are_case_insensitive_and_allow_outer_spaces(self) -> None:
        for index, answer in enumerate(("Да", "да", " НЕТ ", "Нет"), start=1):
            with self.subTest(answer=answer):
                client = FakeTelegramClient(
                    [[], [update(index * 10, "/start")], [update(index * 10 + 1, answer)]]
                )
                self.assertEqual(run_until_urgent_warnings(client, self.storage), 0)

    def test_invalid_answers_are_rejected_and_then_valid_answer_succeeds(self) -> None:
        invalid_values = ("", "   ", "/start", "/help", "1", "0", "yes", "no", "maybe")
        client = FakeTelegramClient(
            [
                [],
                [update(20, "/start")],
                [update(index + 21, value) for index, value in enumerate(invalid_values)]
                + [update(40, "Да")],
            ]
        )

        self.assertEqual(run_until_urgent_warnings(client, self.storage), 0)
        self.assertIs(self.storage.get_user_settings(42).urgent_warnings_enabled, True)
        invalid_messages = [
            item.kwargs["text"]
            for item in client.send_message.call_args_list
            if item.kwargs["text"] == INVALID_URGENT_WARNINGS_TEXT
        ]
        self.assertEqual(len(invalid_messages), len(invalid_values))

    def test_old_updates_are_ignored(self) -> None:
        client = FakeTelegramClient(
            [
                [update(1, "/start"), update(2, "Нет")],
                [],
                [update(1, "/start"), update(3, "/start")],
                [update(4, "Нет")],
            ]
        )

        self.assertEqual(run_until_urgent_warnings(client, self.storage), 0)
        self.assertIs(self.storage.get_user_settings(42).urgent_warnings_enabled, False)

    def test_groups_and_other_chats_are_ignored(self) -> None:
        client = FakeTelegramClient(
            [
                [],
                [
                    update(10, "/start", chat_id=99, chat_type="group"),
                    update(11, "/start"),
                    update(12, "Нет", chat_id=99),
                    update(13, "Нет", chat_type="group"),
                ],
                [update(14, "Нет")],
            ]
        )

        self.assertEqual(run_until_urgent_warnings(client, self.storage), 0)
        self.assertIs(self.storage.get_user_settings(42).urgent_warnings_enabled, False)
        self.assertEqual(client.send_message.call_count, 2)

    def test_missing_city_sends_safe_message_and_does_not_create_row(self) -> None:
        client = FakeTelegramClient([[], [update(20, "/start", chat_id=700)]])

        self.assertEqual(run_until_urgent_warnings(client, self.storage), 1)
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
            result = run_until_urgent_warnings(client, self.storage)

        self.assertEqual(result, 1)
        self.assertEqual(
            client.send_message.call_args_list[-1].kwargs["text"],
            URGENT_WARNINGS_STORAGE_ERROR_TEXT,
        )

    def test_storage_write_error_has_no_false_success_or_internal_details(self) -> None:
        client = FakeTelegramClient([[], [update(40, "/start")], [update(41, "Да")]])
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.object(
            self.storage,
            "save_urgent_warnings_enabled",
            side_effect=StorageError("internal sqlite details"),
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            result = run_until_urgent_warnings(client, self.storage)

        self.assertEqual(result, 1)
        sent_texts = [item.kwargs["text"] for item in client.send_message.call_args_list]
        self.assertIn(URGENT_WARNINGS_STORAGE_ERROR_TEXT, sent_texts)
        self.assertNotIn(URGENT_WARNINGS_ENABLED_TEXT, sent_texts)
        self.assertNotIn("internal sqlite details", stdout.getvalue() + stderr.getvalue())

    def test_keyboard_interrupt_returns_130_without_traceback(self) -> None:
        client = FakeTelegramClient([[], KeyboardInterrupt()])
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_urgent_warnings(client, self.storage)

        self.assertEqual(result, 130)
        self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main()
