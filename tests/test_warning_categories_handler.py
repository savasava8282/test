import io
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, call, patch

from weather_alert_bot.geocoding import GeocodingLocation
from weather_alert_bot.storage import (
    SQLiteSettingsStore,
    StorageError,
    WARNING_CATEGORY_COLUMNS,
    WARNING_CATEGORY_KEYS,
)
from weather_alert_bot.telegram_api import TelegramMessage, TelegramUpdate
from weather_alert_bot.warning_categories_handler import (
    ALL_WARNING_CATEGORIES_DISABLED_TEXT,
    INVALID_WARNING_CATEGORIES_TEXT,
    NO_SAVED_CITY_TEXT,
    WARNING_CATEGORIES_PROMPT,
    WARNING_CATEGORIES_SAVED_TEXT,
    WARNING_CATEGORIES_STORAGE_ERROR_TEXT,
    parse_warning_categories,
    run_until_warning_categories,
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


class WarningCategoriesHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.storage = SQLiteSettingsStore(
            Path(self.temporary_directory.name) / "settings.sqlite3"
        )
        self.storage.save_confirmed_city(42, candidate())

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_exact_prompt_and_all_selection(self) -> None:
        client = FakeTelegramClient(
            [[], [update(1, "/start")], [update(2, "1,2,3,4,5,6,7,8")]]
        )

        result = run_until_warning_categories(client, self.storage)

        self.assertEqual(result, 0)
        self.assertEqual(
            client.send_message.call_args_list[0],
            call(chat_id=42, text=WARNING_CATEGORIES_PROMPT),
        )
        self.assertEqual(
            client.send_message.call_args_list[-1].kwargs["text"],
            "Категории предупреждений сохранены: Магнитная буря, Жара, Холод, "
            "Гололёд, Сильный дождь, Гроза, Сильный ветер, Шторм.",
        )
        settings = self.storage.get_user_settings(42)
        for key in WARNING_CATEGORY_KEYS:
            with self.subTest(key=key):
                self.assertIs(getattr(settings, WARNING_CATEGORY_COLUMNS[key]), True)

    def test_subset_is_canonicalized_and_has_exact_success_text(self) -> None:
        client = FakeTelegramClient([[], [update(1, "/start")], [update(2, "8,1,3")]])
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_warning_categories(client, self.storage)

        self.assertEqual(result, 0)
        self.assertEqual(
            client.send_message.call_args_list[-1],
            call(
                chat_id=42,
                text="Категории предупреждений сохранены: Магнитная буря, Холод, Шторм.",
            ),
        )
        self.assertIn(f"{WARNING_CATEGORIES_SAVED_TEXT}\n", output.getvalue())
        self.assertNotIn("42", output.getvalue())
        settings = self.storage.get_user_settings(42)
        self.assertIs(settings.warning_magnetic_storm_enabled, True)
        self.assertIs(settings.warning_heat_enabled, False)
        self.assertIs(settings.warning_cold_enabled, True)
        self.assertIs(settings.warning_icing_enabled, False)
        self.assertIs(settings.warning_heavy_rain_enabled, False)
        self.assertIs(settings.warning_thunderstorm_enabled, False)
        self.assertIs(settings.warning_strong_wind_enabled, False)
        self.assertIs(settings.warning_storm_enabled, True)

    def test_spaces_and_zero_selection(self) -> None:
        client = FakeTelegramClient([[], [update(1, "/start")], [update(2, " 8, 1, 3 ")]])
        self.assertEqual(run_until_warning_categories(client, self.storage), 0)
        self.assertEqual(
            client.send_message.call_args_list[-1].kwargs["text"],
            "Категории предупреждений сохранены: Магнитная буря, Холод, Шторм.",
        )

        client = FakeTelegramClient([[], [update(3, "/start")], [update(4, "0")]])
        self.assertEqual(run_until_warning_categories(client, self.storage), 0)
        self.assertEqual(
            client.send_message.call_args_list[-1],
            call(chat_id=42, text=ALL_WARNING_CATEGORIES_DISABLED_TEXT),
        )
        settings = self.storage.get_user_settings(42)
        for key in WARNING_CATEGORY_KEYS:
            with self.subTest(key=key):
                self.assertIs(getattr(settings, WARNING_CATEGORY_COLUMNS[key]), False)

    def test_parser_rejects_all_invalid_input_shapes(self) -> None:
        for value in (
            "",
            "   ",
            "/start",
            "/help",
            "1,1",
            "0,1",
            "1-4",
            "9",
            "1,9",
            "Магнитная буря",
            "magnetic_storm",
            "abc",
            "1,,2",
            ",1",
            "1,",
        ):
            with self.subTest(value=value):
                self.assertIsNone(parse_warning_categories(value))

    def test_invalid_input_is_rejected_and_handler_continues(self) -> None:
        invalid_values = ("", "   ", "/start", "1,1", "0,1", "1-4", "9", "Магнитная буря", "1,,2")
        client = FakeTelegramClient(
            [
                [],
                [update(10, "/start")],
                [update(index + 11, value) for index, value in enumerate(invalid_values)]
                + [update(30, "8,1,3")],
            ]
        )

        self.assertEqual(run_until_warning_categories(client, self.storage), 0)
        invalid_messages = [
            item.kwargs["text"]
            for item in client.send_message.call_args_list
            if item.kwargs["text"] == INVALID_WARNING_CATEGORIES_TEXT
        ]
        self.assertEqual(len(invalid_messages), len(invalid_values))

    def test_old_updates_are_ignored(self) -> None:
        client = FakeTelegramClient(
            [
                [update(1, "/start"), update(2, "8,1,3")],
                [],
                [update(1, "/start"), update(3, "/start")],
                [update(4, "8,1,3")],
            ]
        )

        self.assertEqual(run_until_warning_categories(client, self.storage), 0)
        settings = self.storage.get_user_settings(42)
        self.assertIs(settings.warning_magnetic_storm_enabled, True)
        self.assertIs(settings.warning_cold_enabled, True)
        self.assertIs(settings.warning_storm_enabled, True)

    def test_groups_and_other_chats_are_ignored_after_lock(self) -> None:
        client = FakeTelegramClient(
            [
                [],
                [
                    update(10, "/start", chat_id=99, chat_type="group"),
                    update(11, "/start"),
                    update(12, "8,1,3", chat_id=99),
                    update(13, "8,1,3", chat_type="group"),
                ],
                [update(14, "8,1,3")],
            ]
        )

        self.assertEqual(run_until_warning_categories(client, self.storage), 0)
        self.assertEqual(client.send_message.call_count, 2)

    def test_missing_city_sends_exact_safe_message(self) -> None:
        client = FakeTelegramClient([[], [update(20, "/start", chat_id=700)]])

        self.assertEqual(run_until_warning_categories(client, self.storage), 1)
        self.assertEqual(
            client.send_message.call_args_list,
            [call(chat_id=700, text=NO_SAVED_CITY_TEXT)],
        )
        self.assertIsNone(self.storage.get_user_settings(700))

    def test_storage_read_error_is_safe(self) -> None:
        client = FakeTelegramClient([[], [update(30, "/start")]])

        with patch.object(
            self.storage,
            "get_user_settings",
            side_effect=StorageError("internal sqlite details"),
        ):
            result = run_until_warning_categories(client, self.storage)

        self.assertEqual(result, 1)
        self.assertEqual(
            client.send_message.call_args_list[-1].kwargs["text"],
            WARNING_CATEGORIES_STORAGE_ERROR_TEXT,
        )

    def test_storage_write_error_has_no_false_success_or_internal_details(self) -> None:
        client = FakeTelegramClient([[], [update(40, "/start")], [update(41, "8,1,3")]])
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.object(
            self.storage,
            "save_warning_categories",
            side_effect=StorageError("internal sqlite details"),
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            result = run_until_warning_categories(client, self.storage)

        self.assertEqual(result, 1)
        sent_texts = [item.kwargs["text"] for item in client.send_message.call_args_list]
        self.assertIn(WARNING_CATEGORIES_STORAGE_ERROR_TEXT, sent_texts)
        self.assertNotIn("Категории предупреждений сохранены:", "\n".join(sent_texts))
        self.assertNotIn("internal sqlite details", stdout.getvalue() + stderr.getvalue())

    def test_keyboard_interrupt_is_safe(self) -> None:
        client = FakeTelegramClient([[], KeyboardInterrupt()])
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_warning_categories(client, self.storage)

        self.assertEqual(result, 130)
        self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main()
