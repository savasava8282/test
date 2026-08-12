import io
from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, call, patch
from zoneinfo import ZoneInfo

from weather_alert_bot.daily_summary import DailySummary, format_daily_summary
from weather_alert_bot.daily_summary import build_daily_summary
from weather_alert_bot.daily_summary import DailySummaryError
from weather_alert_bot.geomagnetic_forecast import (
    GeomagneticForecast,
    GeomagneticForecastError,
    GeomagneticForecastInterval,
)
from weather_alert_bot.geocoding import GeocodingLocation
from weather_alert_bot.storage import SQLiteSettingsStore, StorageError
from weather_alert_bot.telegram_api import TelegramApiError, TelegramMessage, TelegramUpdate
from weather_alert_bot.today_handler import (
    ONBOARDING_REQUIRED_TEXT,
    SUMMARY_ERROR_TEXT,
    run_until_today,
)
from weather_alert_bot.weather_forecast import (
    DailyForecast,
    HourlyForecast,
    WeatherForecast,
    WeatherForecastError,
)


FIXED_NOW = datetime(2026, 8, 10, 21, tzinfo=ZoneInfo("UTC"))
SUMMARY_DATE = date(2026, 8, 11)


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


def weather() -> WeatherForecast:
    return WeatherForecast(
        latitude=55.75204,
        longitude=37.61781,
        timezone="Europe/Moscow",
        generation_time_ms=None,
        daily=(
            DailyForecast(
                date=SUMMARY_DATE,
                weather_code=61,
                temperature_2m_max=25.1,
                temperature_2m_min=15.5,
                precipitation_probability_max=78.0,
                precipitation_sum=1.1,
                wind_speed_10m_max=14.7,
                wind_gusts_10m_max=43.9,
            ),
        ),
        hourly=(
            HourlyForecast(
                time=datetime(2026, 8, 11, 9),
                temperature_2m=18.0,
                precipitation_probability=20.0,
                precipitation=0.0,
                weather_code=61,
                wind_speed_10m=10.0,
                wind_gusts_10m=20.0,
            ),
            HourlyForecast(
                time=datetime(2026, 8, 11, 15),
                temperature_2m=24.0,
                precipitation_probability=78.0,
                precipitation=0.5,
                weather_code=61,
                wind_speed_10m=10.0,
                wind_gusts_10m=20.0,
            ),
        ),
    )


def geomagnetic() -> GeomagneticForecast:
    return GeomagneticForecast(
        intervals=(
            GeomagneticForecastInterval(
                timestamp=datetime(2026, 8, 11),
                kp=2.0,
                status="predicted",
            ),
        )
    )


class TodayHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "settings.sqlite3"
        writable_storage = SQLiteSettingsStore(self.path)
        writable_storage.save_confirmed_city(42, candidate())
        writable_storage.mark_onboarding_completed(42)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def read_only_storage(self) -> SQLiteSettingsStore:
        return SQLiteSettingsStore(self.path, read_only=True)

    def run_handler(
        self,
        responses: list[object],
        *,
        weather_client: object | None = None,
        geomagnetic_client: object | None = None,
        storage: object | None = None,
    ) -> tuple[int, FakeTelegramClient, Mock, Mock, str, str]:
        client = FakeTelegramClient(responses)
        weather_mock = weather_client or Mock()
        weather_mock.fetch.return_value = weather()
        kp_mock = geomagnetic_client or Mock()
        kp_mock.fetch.return_value = geomagnetic()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = run_until_today(
                client,
                storage or self.read_only_storage(),
                weather_mock,
                kp_mock,
                FIXED_NOW,
            )
        return result, client, weather_mock, kp_mock, stdout.getvalue(), stderr.getvalue()

    def test_old_queued_today_is_removed_without_response(self) -> None:
        result, client, weather_mock, kp_mock, _, _ = self.run_handler(
            [[update(1, "/today")], [], [update(2, "/today")]]
        )

        self.assertEqual(result, 0)
        self.assertEqual(client.get_updates_calls[0]["timeout"], 0)
        self.assertEqual(client.get_updates_calls[1]["timeout"], 0)
        self.assertEqual(client.get_updates_calls[2]["timeout"], 30)
        self.assertEqual(client.send_message.call_count, 1)
        weather_mock.fetch.assert_called_once()
        kp_mock.fetch.assert_called_once()

    def test_private_owner_today_is_accepted_and_finishes_after_one_send(self) -> None:
        result, client, _, _, _, _ = self.run_handler([[], [update(1, "/today")]])

        self.assertEqual(result, 0)
        self.assertEqual(client.send_message.call_count, 1)
        self.assertEqual(client.get_updates_calls[-1]["timeout"], 30)

    def test_username_command_is_accepted(self) -> None:
        result, client, _, _, _, _ = self.run_handler(
            [[], [update(1, "/today@weather_storm_alert_bot")]]
        )

        self.assertEqual(result, 0)
        self.assertEqual(client.send_message.call_count, 1)

    def test_other_text_is_ignored(self) -> None:
        result, client, weather_mock, kp_mock, _, _ = self.run_handler(
            [[], [update(1, "погода")], [update(2, "/today")]]
        )

        self.assertEqual(result, 0)
        self.assertEqual(client.send_message.call_count, 1)
        weather_mock.fetch.assert_called_once()
        kp_mock.fetch.assert_called_once()

    def test_groups_and_other_chats_are_ignored_without_external_requests(self) -> None:
        weather_mock = Mock()
        kp_mock = Mock()
        result, client, _, _, _, output = self.run_handler(
            [[], [
                update(1, "/today", chat_type="group"),
                update(2, "/today", chat_id=99),
            ], KeyboardInterrupt()],
            weather_client=weather_mock,
            geomagnetic_client=kp_mock,
        )

        self.assertEqual(result, 130)
        client.send_message.assert_not_called()
        weather_mock.fetch.assert_not_called()
        kp_mock.fetch.assert_not_called()
        self.assertNotIn("Traceback", output)

    def test_send_text_equals_existing_formatter_byte_for_byte(self) -> None:
        result, client, _, _, _, _ = self.run_handler([[], [update(1, "/today")]])
        expected = format_daily_summary(
            build_daily_summary(
                self.read_only_storage().get_single_user_settings(),
                weather(),
                geomagnetic(),
                FIXED_NOW,
            )
        )

        self.assertEqual(result, 0)
        self.assertEqual(
            client.send_message.call_args,
            call(chat_id=42, text=expected),
        )

    def test_daily_sending_disabled_does_not_block_manual_today(self) -> None:
        writable_storage = SQLiteSettingsStore(self.path)
        writable_storage.save_daily_sending_enabled(42, False)

        result, client, weather_mock, kp_mock, _, _ = self.run_handler(
            [[], [update(1, "/today")]]
        )

        self.assertEqual(result, 0)
        client.send_message.assert_called_once()
        weather_mock.fetch.assert_called_once()
        kp_mock.fetch.assert_called_once()

    def test_incomplete_onboarding_sends_safe_message_without_data_requests(self) -> None:
        incomplete_path = Path(self.temporary_directory.name) / "incomplete.sqlite3"
        incomplete_storage = SQLiteSettingsStore(incomplete_path)
        incomplete_storage.save_confirmed_city(42, candidate())
        weather_mock = Mock()
        kp_mock = Mock()
        result, client, _, _, _, _ = self.run_handler(
            [[], [update(1, "/today")]],
            storage=SQLiteSettingsStore(incomplete_path, read_only=True),
            weather_client=weather_mock,
            geomagnetic_client=kp_mock,
        )

        self.assertEqual(result, 1)
        self.assertEqual(client.send_message.call_args, call(chat_id=42, text=ONBOARDING_REQUIRED_TEXT))
        weather_mock.fetch.assert_not_called()
        kp_mock.fetch.assert_not_called()

    def test_weather_error_sends_safe_message(self) -> None:
        weather_mock = Mock()
        weather_mock.fetch.side_effect = WeatherForecastError("private weather details")
        result, client, _, kp_mock, _, stderr = self.run_handler(
            [[], [update(1, "/today")]], weather_client=weather_mock
        )

        self.assertEqual(result, 1)
        self.assertEqual(client.send_message.call_args, call(chat_id=42, text=SUMMARY_ERROR_TEXT))
        kp_mock.fetch.assert_not_called()
        self.assertNotIn("private weather details", stderr)

    def test_geomagnetic_error_sends_safe_message(self) -> None:
        kp_mock = Mock()
        kp_mock.fetch.side_effect = GeomagneticForecastError("private Kp details")
        result, client, _, _, _, stderr = self.run_handler(
            [[], [update(1, "/today")]], geomagnetic_client=kp_mock
        )

        self.assertEqual(result, 1)
        self.assertEqual(client.send_message.call_args, call(chat_id=42, text=SUMMARY_ERROR_TEXT))
        self.assertNotIn("private Kp details", stderr)

    def test_daily_summary_error_sends_safe_message(self) -> None:
        with patch(
            "weather_alert_bot.today_handler.build_daily_summary",
            side_effect=DailySummaryError("private summary details"),
        ):
            result, client, _, _, _, stderr = self.run_handler([[], [update(1, "/today")]])

        self.assertEqual(result, 1)
        self.assertEqual(client.send_message.call_args, call(chat_id=42, text=SUMMARY_ERROR_TEXT))
        self.assertNotIn("private summary details", stderr)

    def test_error_message_send_error_is_safe(self) -> None:
        weather_mock = Mock()
        weather_mock.fetch.side_effect = WeatherForecastError("private details")
        failing_client = FakeTelegramClient([[], [update(1, "/today")]])
        failing_client.send_message.side_effect = TelegramApiError("token chat URL private")
        output_stream = io.StringIO()
        error_stream = io.StringIO()
        with redirect_stdout(output_stream), redirect_stderr(error_stream):
            result = run_until_today(
                failing_client,
                self.read_only_storage(),
                weather_mock,
                Mock(),
                FIXED_NOW,
            )

        self.assertEqual(result, 1)
        self.assertNotIn("token chat URL private", output_stream.getvalue() + error_stream.getvalue())

    def test_missing_owner_is_safe_and_does_not_poll(self) -> None:
        empty_path = Path(self.temporary_directory.name) / "empty.sqlite3"
        SQLiteSettingsStore(empty_path)
        client = FakeTelegramClient([])
        output = io.StringIO()
        error = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            result = run_until_today(
                client,
                SQLiteSettingsStore(empty_path, read_only=True),
                Mock(),
                Mock(),
                FIXED_NOW,
            )

        self.assertEqual(result, 1)
        self.assertEqual(client.get_updates_calls, [])
        self.assertNotIn("Traceback", output.getvalue() + error.getvalue())

    def test_success_send_error_returns_one_without_traceback(self) -> None:
        client = FakeTelegramClient([[], [update(1, "/today")]])
        client.send_message.side_effect = TelegramApiError("private Telegram details")
        output = io.StringIO()
        error = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            result = run_until_today(
                client,
                self.read_only_storage(),
                Mock(fetch=Mock(return_value=weather())),
                Mock(fetch=Mock(return_value=geomagnetic())),
                FIXED_NOW,
            )

        self.assertEqual(result, 1)
        self.assertNotIn("private Telegram details", output.getvalue() + error.getvalue())
        self.assertNotIn("Traceback", output.getvalue() + error.getvalue())

    def test_storage_error_does_not_start_polling(self) -> None:
        storage = Mock()
        storage.get_single_user_settings.side_effect = StorageError("private sqlite details")
        client = FakeTelegramClient([])
        output = io.StringIO()
        error = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            result = run_until_today(client, storage, Mock(), Mock(), FIXED_NOW)

        self.assertEqual(result, 1)
        self.assertEqual(client.get_updates_calls, [])
        self.assertNotIn("private sqlite details", error.getvalue())

    def test_read_only_storage_is_not_modified(self) -> None:
        before = self.path.read_bytes()
        result, _, _, _, _, _ = self.run_handler([[], [update(1, "/today")]])
        after = self.path.read_bytes()

        self.assertEqual(result, 0)
        self.assertEqual(after, before)

    def test_formed_at_is_passed_to_builder_as_aware_datetime(self) -> None:
        captured: list[datetime] = []

        def build(*args: object) -> DailySummary:
            captured.append(args[-1])
            return build_daily_summary(
                self.read_only_storage().get_single_user_settings(),
                weather(),
                geomagnetic(),
                FIXED_NOW,
            )

        with patch("weather_alert_bot.today_handler.build_daily_summary", side_effect=build):
            result, _, _, _, _, _ = self.run_handler([[], [update(1, "/today")]])

        self.assertEqual(result, 0)
        self.assertEqual(captured, [FIXED_NOW])
        self.assertIsNotNone(captured[0].tzinfo)

    def test_keyboard_interrupt_is_safe(self) -> None:
        result, _, _, _, output, _ = self.run_handler([[], KeyboardInterrupt()])

        self.assertEqual(result, 130)
        self.assertNotIn("Traceback", output)


if __name__ == "__main__":
    unittest.main()
