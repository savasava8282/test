import io
from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, call, patch
from zoneinfo import ZoneInfo

from weather_alert_bot.daily_summary import DailySummary, format_daily_summary
from weather_alert_bot.daily_summary import (
    build_daily_summary,
    format_daily_risk_section,
)
from weather_alert_bot.daily_summary import DailySummaryError
from weather_alert_bot.climate_cache import ClimateCacheError, SQLiteClimateNormalsCache
from weather_alert_bot.climate_normals import (
    BASELINE_END,
    BASELINE_START,
    ClimateNormalDay,
    ClimateNormals,
    ClimateNormalsError,
    HistoricalTemperatureDay,
    get_climate_normal_for_date,
)
from weather_alert_bot.geomagnetic_forecast import (
    GeomagneticForecast,
    GeomagneticForecastError,
    GeomagneticForecastInterval,
)
from weather_alert_bot.geocoding import GeocodingLocation
from weather_alert_bot.storage import SQLiteSettingsStore, StorageError
from weather_alert_bot.risk_assessment import (
    CurrentDayRiskAssessment,
    RiskAssessmentError,
    assess_current_day_risks,
)
from weather_alert_bot.telegram_api import TelegramApiError, TelegramMessage, TelegramUpdate
from weather_alert_bot.today_handler import (
    CLIMATE_FALLBACK_DIAGNOSTIC,
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


def climate_normals() -> ClimateNormals:
    return ClimateNormals(
        latitude=55.75204,
        longitude=37.61781,
        timezone="Europe/Moscow",
        period_start=BASELINE_START,
        period_end=BASELINE_END,
        days=tuple(
            ClimateNormalDay(
                month,
                day,
                10.0,
                20.0,
                8 if (month, day) == (2, 29) else 30,
            )
            for offset in range(366)
            for month, day in [
                (
                    (date(2000, 1, 1) + timedelta(days=offset)).month,
                    (date(2000, 1, 1) + timedelta(days=offset)).day,
                )
            ]
        ),
    )


def historical_records() -> tuple[HistoricalTemperatureDay, ...]:
    return tuple(
        HistoricalTemperatureDay(BASELINE_START + timedelta(days=offset), 10.0, 20.0)
        for offset in range((BASELINE_END - BASELINE_START).days + 1)
    )


class TodayHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "settings.sqlite3"
        self.climate_path = Path(self.temporary_directory.name) / "climate.sqlite3"
        writable_storage = SQLiteSettingsStore(self.path)
        writable_storage.save_confirmed_city(42, candidate())
        writable_storage.mark_onboarding_completed(42)
        SQLiteClimateNormalsCache(self.climate_path).save(
            climate_normals(), generated_at=FIXED_NOW
        )

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
        climate_cache: object | None = None,
        historical_client: object | None = None,
    ) -> tuple[int, FakeTelegramClient, Mock, Mock, str, str]:
        client = FakeTelegramClient(responses)
        weather_mock = weather_client or Mock()
        weather_mock.fetch.return_value = weather()
        kp_mock = geomagnetic_client or Mock()
        kp_mock.fetch.return_value = geomagnetic()
        climate_cache_value = climate_cache or SQLiteClimateNormalsCache(self.climate_path)
        historical_mock = historical_client or Mock()
        historical_mock.fetch.return_value = historical_records()
        self.last_climate_cache = climate_cache_value
        self.last_historical_client = historical_mock
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = run_until_today(
                client,
                storage or self.read_only_storage(),
                weather_mock,
                kp_mock,
                climate_cache_value,
                historical_mock,
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

    def test_cache_hit_does_not_call_historical_client(self) -> None:
        result, _, _, _, _, _ = self.run_handler([[], [update(1, "/today")]])

        self.assertEqual(result, 0)
        self.last_historical_client.fetch.assert_not_called()

    def test_same_weather_and_geomagnetic_objects_are_reused_by_summary_and_detector(self) -> None:
        captured_summary_inputs: list[tuple[object, object]] = []
        captured_assessments: list[CurrentDayRiskAssessment] = []

        def build(*args: object) -> DailySummary:
            captured_summary_inputs.append((args[1], args[2]))
            return build_daily_summary(*args)  # type: ignore[arg-type]

        def assess(*args: object, **kwargs: object) -> CurrentDayRiskAssessment:
            result = assess_current_day_risks(*args, **kwargs)  # type: ignore[arg-type]
            captured_assessments.append(result)
            return result

        with patch(
            "weather_alert_bot.today_handler.build_daily_summary",
            side_effect=build,
        ) as summary_builder, patch(
            "weather_alert_bot.today_handler.assess_current_day_risks",
            side_effect=assess,
        ) as detector:
            result, _, weather_mock, kp_mock, _, _ = self.run_handler(
                [[], [update(1, "/today")]]
            )

        self.assertEqual(result, 0)
        summary_builder.assert_called_once()
        detector.assert_called_once()
        self.assertIs(captured_summary_inputs[0][0], weather_mock.fetch.return_value)
        self.assertIs(captured_summary_inputs[0][1], kp_mock.fetch.return_value)
        self.assertIs(detector.call_args.args[0], weather_mock.fetch.return_value)
        self.assertIs(detector.call_args.args[1], kp_mock.fetch.return_value)
        self.assertIsNotNone(detector.call_args.kwargs["climate_normal"])
        self.assertEqual(captured_assessments[0].unsupported_categories, ())

    def test_cache_miss_fetches_historical_once_and_saves_snapshot(self) -> None:
        empty_path = Path(self.temporary_directory.name) / "miss.sqlite3"
        cache = SQLiteClimateNormalsCache(empty_path)
        historical_mock = Mock()
        historical_mock.fetch.return_value = historical_records()

        result, _, _, _, _, _ = self.run_handler(
            [[], [update(1, "/today")]],
            climate_cache=cache,
            historical_client=historical_mock,
        )

        self.assertEqual(result, 0)
        historical_mock.fetch.assert_called_once_with(
            55.75204,
            37.61781,
            "Europe/Moscow",
        )
        cached = cache.get(55.75204, 37.61781, "Europe/Moscow")
        self.assertIsNotNone(cached)
        self.assertEqual(len(cached.normals.days), 366)

        second_historical = Mock()
        second_historical.fetch.return_value = historical_records()
        second_result, _, _, _, _, _ = self.run_handler(
            [[], [update(2, "/today")]],
            climate_cache=cache,
            historical_client=second_historical,
        )
        self.assertEqual(second_result, 0)
        second_historical.fetch.assert_not_called()

    def test_climate_cache_error_falls_back_to_six_category_assessment(self) -> None:
        failing_cache = Mock()
        failing_cache.get.side_effect = ClimateCacheError("private cache details")

        result, client, _, _, _, stderr = self.run_handler(
            [[], [update(1, "/today")]],
            climate_cache=failing_cache,
        )

        self.assertEqual(result, 0)
        self.assertIn(CLIMATE_FALLBACK_DIAGNOSTIC, stderr)
        self.assertNotIn("private cache details", stderr)
        sent_text = client.send_message.call_args.kwargs["text"]
        self.assertIn("Риски сегодня: значимых по включённым категориям не выявлено.", sent_text)
        self.assertIn("Временно не оценены: сильная жара, сильный холод.", sent_text)
        self.last_historical_client.fetch.assert_not_called()

    def test_historical_error_on_cache_miss_falls_back_without_writing_cache(self) -> None:
        empty_path = Path(self.temporary_directory.name) / "historical-failure.sqlite3"
        cache = SQLiteClimateNormalsCache(empty_path)
        historical_mock = Mock()
        historical_mock.fetch.side_effect = ClimateNormalsError("private historical details")

        result, client, _, _, _, stderr = self.run_handler(
            [[], [update(1, "/today")]],
            climate_cache=cache,
            historical_client=historical_mock,
        )

        self.assertEqual(result, 0)
        self.assertIn(CLIMATE_FALLBACK_DIAGNOSTIC, stderr)
        self.assertNotIn("private historical details", stderr)
        self.assertIsNone(cache.get(55.75204, 37.61781, "Europe/Moscow"))
        self.assertIn("Временно не оценены: сильная жара, сильный холод.", client.send_message.call_args.kwargs["text"])

    def test_risk_assessment_error_uses_general_safe_failure(self) -> None:
        with patch(
            "weather_alert_bot.today_handler.assess_current_day_risks",
            side_effect=RiskAssessmentError("private detector details"),
        ):
            result, client, _, _, _, output = self.run_handler(
                [[], [update(1, "/today")]]
            )

        self.assertEqual(result, 1)
        self.assertEqual(client.send_message.call_args, call(chat_id=42, text=SUMMARY_ERROR_TEXT))
        self.assertNotIn("private detector details", output)

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

    def test_send_text_composes_existing_summary_with_concise_risk_block(self) -> None:
        result, client, _, _, _, _ = self.run_handler([[], [update(1, "/today")]])
        owner = self.read_only_storage().get_single_user_settings()
        assert owner is not None
        assessment = assess_current_day_risks(
            weather(),
            geomagnetic(),
            owner.timezone,
            FIXED_NOW,
            climate_normal=get_climate_normal_for_date(climate_normals(), SUMMARY_DATE),
        )
        expected = format_daily_summary(
            build_daily_summary(
                owner,
                weather(),
                geomagnetic(),
                FIXED_NOW,
            ),
            risk_section=format_daily_risk_section(assessment, owner),
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
                SQLiteClimateNormalsCache(self.climate_path),
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
                SQLiteClimateNormalsCache(self.climate_path),
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
                SQLiteClimateNormalsCache(self.climate_path),
                Mock(),
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
            result = run_until_today(
                client,
                storage,
                Mock(),
                Mock(),
                SQLiteClimateNormalsCache(self.climate_path),
                Mock(),
                FIXED_NOW,
            )

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
