import io
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import ANY, Mock, call, patch

from weather_alert_bot.geocoding import GeocodingLocation
from weather_alert_bot.settings_summary_handler import (
    NO_SAVED_CITY_TEXT,
    SETTINGS_SUMMARY_STORAGE_ERROR_TEXT,
    format_daily_send_days,
    format_settings_summary,
    format_warning_categories,
    run_until_settings_summary,
)
from weather_alert_bot.storage import SQLiteSettingsStore, StorageError, WARNING_CATEGORY_KEYS
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


class SettingsSummaryHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.storage = SQLiteSettingsStore(
            Path(self.temporary_directory.name) / "settings.sqlite3"
        )
        self.storage.save_confirmed_city(42, candidate())

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _run_summary(self, *responses: object) -> str:
        client = FakeTelegramClient([[], [update(1, "/start")], *responses])
        self.assertEqual(run_until_settings_summary(client, self.storage), 0)
        return client.send_message.call_args_list[-1].kwargs["text"]

    def test_full_summary_has_stable_format(self) -> None:
        self.storage.save_daily_send_time(42, "08:30")
        self.storage.save_daily_send_days(42, "1,3,5")
        self.storage.save_daily_sending_enabled(42, False)
        self.storage.save_urgent_warnings_enabled(42, False)
        self.storage.save_warning_categories(42, {"magnetic_storm", "cold", "storm"})

        summary = self._run_summary()

        self.assertEqual(
            summary,
            "Итоговые настройки:\n\n"
            "Город: Москва\n"
            "Время ежедневной отправки: 08:30\n"
            "Дни отправки: Пн, Ср, Пт\n"
            "Ежедневная рассылка: выключена\n"
            "Срочные предупреждения: выключены\n"
            "Категории предупреждений: Магнитная буря, Холод, Шторм",
        )

    def test_days_1_3_5_are_formatted_in_russian(self) -> None:
        self.assertEqual(format_daily_send_days("1,3,5"), "Пн, Ср, Пт")

    def test_all_seven_days_are_formatted_in_order(self) -> None:
        self.assertEqual(
            format_daily_send_days("1,2,3,4,5,6,7"),
            "Пн, Вт, Ср, Чт, Пт, Сб, Вс",
        )

    def test_daily_sending_true_and_false_are_localized(self) -> None:
        self.storage.save_daily_sending_enabled(42, True)
        self.assertIn("Ежедневная рассылка: включена", self._run_summary())

        self.storage.save_daily_sending_enabled(42, False)
        self.assertIn("Ежедневная рассылка: выключена", self._run_summary())

    def test_urgent_warnings_true_and_false_are_localized(self) -> None:
        self.storage.save_urgent_warnings_enabled(42, True)
        self.assertIn("Срочные предупреждения: включены", self._run_summary())

        self.storage.save_urgent_warnings_enabled(42, False)
        self.assertIn("Срочные предупреждения: выключены", self._run_summary())

    def test_all_warning_categories_are_listed(self) -> None:
        settings = self.storage.get_user_settings(42)
        self.assertIsNotNone(settings)
        self.assertEqual(
            format_warning_categories(settings),
            "Магнитная буря, Жара, Холод, Гололёд, Сильный дождь, Гроза, "
            "Сильный ветер, Шторм",
        )
        self.assertTrue(all(getattr(settings, f"warning_{key}_enabled") for key in WARNING_CATEGORY_KEYS))

    def test_subset_of_warning_categories_is_listed_in_established_order(self) -> None:
        self.storage.save_warning_categories(42, {"storm", "heat", "icing"})
        settings = self.storage.get_user_settings(42)

        self.assertEqual(
            format_warning_categories(settings),
            "Жара, Гололёд, Шторм",
        )

    def test_all_warning_categories_disabled_has_required_text(self) -> None:
        self.storage.save_warning_categories(42, set())
        settings = self.storage.get_user_settings(42)

        self.assertEqual(format_warning_categories(settings), "отключены")
        self.assertIn("Категории предупреждений: отключены", format_settings_summary(settings))

    def test_summary_does_not_modify_saved_settings(self) -> None:
        before = self.storage.get_user_settings(42)
        client = FakeTelegramClient([[], [update(1, "/start")]])

        self.assertEqual(run_until_settings_summary(client, self.storage), 0)
        self.assertEqual(self.storage.get_user_settings(42), before)

    def test_old_updates_are_cleared_before_new_start(self) -> None:
        client = FakeTelegramClient(
            [
                [update(1, "/start"), update(2, "/start")],
                [],
                [update(3, "/start@weather_storm_alert_bot")],
            ]
        )

        self.assertEqual(run_until_settings_summary(client, self.storage), 0)
        self.assertEqual(client.get_updates_calls[0]["timeout"], 0)
        self.assertEqual(client.get_updates_calls[1]["timeout"], 0)
        self.assertEqual(client.get_updates_calls[2]["timeout"], 30)
        self.assertEqual(client.send_message.call_count, 1)

    def test_groups_and_other_chats_are_ignored(self) -> None:
        client = FakeTelegramClient(
            [
                [],
                [
                    update(1, "/start", chat_type="group"),
                    update(2, "/start@weather_storm_alert_bot"),
                    update(3, "/start", chat_id=99),
                ],
            ]
        )

        self.assertEqual(run_until_settings_summary(client, self.storage), 0)
        self.assertEqual(
            client.send_message.call_args,
            call(chat_id=42, text=ANY),
        )

    def test_missing_saved_user_is_safe(self) -> None:
        client = FakeTelegramClient([[], [update(1, "/start", chat_id=700)]])

        self.assertEqual(run_until_settings_summary(client, self.storage), 1)
        self.assertEqual(
            client.send_message.call_args_list,
            [call(chat_id=700, text=NO_SAVED_CITY_TEXT)],
        )
        self.assertIsNone(self.storage.get_user_settings(700))

    def test_storage_error_is_safe(self) -> None:
        client = FakeTelegramClient([[], [update(1, "/start")]])
        stdout = io.StringIO()

        with patch.object(
            self.storage,
            "get_user_settings",
            side_effect=StorageError("internal sqlite details"),
        ), redirect_stdout(stdout):
            result = run_until_settings_summary(client, self.storage)

        self.assertEqual(result, 1)
        self.assertEqual(
            client.send_message.call_args,
            call(chat_id=42, text=SETTINGS_SUMMARY_STORAGE_ERROR_TEXT),
        )
        self.assertNotIn("internal sqlite details", stdout.getvalue())

    def test_keyboard_interrupt_is_safe(self) -> None:
        client = FakeTelegramClient([[], KeyboardInterrupt()])
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_settings_summary(client, self.storage)

        self.assertEqual(result, 130)
        self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main()
