import io
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, call, patch

from weather_alert_bot.geocoding import GeocodingLocation
from weather_alert_bot.onboarding_complete_handler import (
    INVALID_ONBOARDING_COMPLETE_TEXT,
    NO_SAVED_CITY_TEXT,
    ONBOARDING_COMPLETE_PROMPT,
    ONBOARDING_COMPLETE_STORAGE_ERROR_TEXT,
    ONBOARDING_COMPLETED_TEXT,
    ONBOARDING_NOT_COMPLETED_TEXT,
    run_until_onboarding_complete,
)
from weather_alert_bot.settings_summary_handler import format_settings_summary
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


class OnboardingCompleteHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.storage = SQLiteSettingsStore(
            Path(self.temporary_directory.name) / "settings.sqlite3"
        )
        self.storage.save_confirmed_city(42, candidate())

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_summary_is_sent_before_confirmation_question(self) -> None:
        client = FakeTelegramClient([[], [update(1, "/start")], KeyboardInterrupt()])

        self.assertEqual(run_until_onboarding_complete(client, self.storage), 130)
        self.assertEqual(
            client.send_message.call_args_list[:2],
            [
                call(chat_id=42, text=format_settings_summary(self.storage.get_user_settings(42))),
                call(chat_id=42, text=ONBOARDING_COMPLETE_PROMPT),
            ],
        )

    def test_yes_marks_onboarding_complete_and_sends_success(self) -> None:
        client = FakeTelegramClient(
            [[], [update(1, "/start")], [update(2, "  ДА ")]]
        )

        self.assertEqual(run_until_onboarding_complete(client, self.storage), 0)
        self.assertIs(self.storage.get_user_settings(42).onboarding_completed, True)
        self.assertEqual(
            client.send_message.call_args_list[-1],
            call(chat_id=42, text=ONBOARDING_COMPLETED_TEXT),
        )

    def test_no_does_not_change_sqlite_and_finishes(self) -> None:
        before = self.storage.get_user_settings(42)
        client = FakeTelegramClient(
            [[], [update(1, "/start")], [update(2, " нет ")]]
        )

        self.assertEqual(run_until_onboarding_complete(client, self.storage), 0)
        self.assertEqual(self.storage.get_user_settings(42), before)
        self.assertEqual(
            client.send_message.call_args_list[-1],
            call(chat_id=42, text=ONBOARDING_NOT_COMPLETED_TEXT),
        )

    def test_invalid_answer_is_rejected_and_handler_continues(self) -> None:
        client = FakeTelegramClient(
            [
                [],
                [update(1, "/start")],
                [update(2, "yes")],
                [update(3, "Да")],
            ]
        )

        self.assertEqual(run_until_onboarding_complete(client, self.storage), 0)
        self.assertEqual(
            client.send_message.call_args_list[2],
            call(chat_id=42, text=INVALID_ONBOARDING_COMPLETE_TEXT),
        )
        self.assertIs(self.storage.get_user_settings(42).onboarding_completed, True)

    def test_groups_and_other_chats_are_ignored(self) -> None:
        client = FakeTelegramClient(
            [
                [],
                [
                    update(1, "/start", chat_type="group"),
                    update(2, "hello", chat_id=99),
                ],
                [update(3, "/start")],
                [
                    update(4, "Да", chat_id=99),
                    update(5, "Да", chat_type="group"),
                    update(6, "Да"),
                ],
            ]
        )

        self.assertEqual(run_until_onboarding_complete(client, self.storage), 0)
        self.assertEqual(client.send_message.call_args_list[-1], call(
            chat_id=42, text=ONBOARDING_COMPLETED_TEXT
        ))
        self.assertIs(self.storage.get_user_settings(42).onboarding_completed, True)
        self.assertIsNone(self.storage.get_user_settings(99))

    def test_old_updates_are_cleared_without_reply(self) -> None:
        client = FakeTelegramClient(
            [
                [update(1, "/start")],
                [],
                [update(2, "/start")],
                [update(3, "Нет")],
            ]
        )

        self.assertEqual(run_until_onboarding_complete(client, self.storage), 0)
        self.assertEqual(client.send_message.call_count, 3)
        self.assertEqual(client.get_updates_calls[0]["timeout"], 0)
        self.assertEqual(client.get_updates_calls[1]["timeout"], 0)
        self.assertEqual(client.get_updates_calls[2]["timeout"], 30)

    def test_missing_saved_city_is_safe(self) -> None:
        client = FakeTelegramClient([[], [update(1, "/start", chat_id=700)]])

        self.assertEqual(run_until_onboarding_complete(client, self.storage), 1)
        self.assertEqual(
            client.send_message.call_args,
            call(chat_id=700, text=NO_SAVED_CITY_TEXT),
        )
        self.assertIsNone(self.storage.get_user_settings(700))

    def test_storage_error_is_safe(self) -> None:
        client = FakeTelegramClient([[], [update(1, "/start")]])
        with patch.object(
            self.storage,
            "get_user_settings",
            side_effect=StorageError("private sqlite details"),
        ):
            self.assertEqual(run_until_onboarding_complete(client, self.storage), 1)

        self.assertEqual(
            client.send_message.call_args,
            call(chat_id=42, text=ONBOARDING_COMPLETE_STORAGE_ERROR_TEXT),
        )

    def test_storage_error_while_marking_is_safe(self) -> None:
        client = FakeTelegramClient(
            [[], [update(1, "/start")], [update(2, "Да")]]
        )
        output = io.StringIO()
        with patch.object(
            self.storage,
            "mark_onboarding_completed",
            side_effect=StorageError("private sqlite details"),
        ), redirect_stdout(output):
            result = run_until_onboarding_complete(client, self.storage)

        self.assertEqual(result, 1)
        self.assertEqual(
            client.send_message.call_args_list[-1],
            call(chat_id=42, text=ONBOARDING_COMPLETE_STORAGE_ERROR_TEXT),
        )
        self.assertNotIn("private sqlite details", output.getvalue())
        self.assertNotIn(ONBOARDING_COMPLETED_TEXT, [
            item.kwargs["text"] for item in client.send_message.call_args_list
        ])

    def test_keyboard_interrupt_is_safe(self) -> None:
        client = FakeTelegramClient([[], KeyboardInterrupt()])
        output = io.StringIO()
        with redirect_stdout(output):
            result = run_until_onboarding_complete(client, self.storage)

        self.assertEqual(result, 130)
        self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main()
