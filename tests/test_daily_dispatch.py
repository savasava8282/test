from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from weather_alert_bot.daily_dispatch import (
    DailyDispatchError,
    evaluate_daily_dispatch_due,
    run_daily_dispatch_once,
)
from weather_alert_bot.runtime_state import (
    RuntimeStateError,
    SQLiteRuntimeStateStore,
)
from weather_alert_bot.storage import UserSettings
from weather_alert_bot.telegram_api import TelegramApiError
from weather_alert_bot.weather_forecast import WeatherForecastError


UTC = ZoneInfo("UTC")


def owner(**changes: object) -> UserSettings:
    values: dict[str, object] = {
        "telegram_chat_id": 42,
        "city_name": "Москва",
        "latitude": 55.75204,
        "longitude": 37.61781,
        "timezone": "Europe/Moscow",
        "daily_send_time": "10:00",
        "daily_send_days": "1,2,3,4,5,6,7",
        "daily_sending_enabled": True,
        "onboarding_completed": True,
    }
    values.update(changes)
    return UserSettings(**values)  # type: ignore[arg-type]


class DailyDispatchDueTest(unittest.TestCase):
    def test_exact_local_minute_is_due_and_seconds_do_not_matter(self) -> None:
        settings = owner(timezone="Asia/Tokyo", daily_send_time="09:00")
        for second in (0, 25, 59):
            with self.subTest(second=second):
                decision = evaluate_daily_dispatch_due(
                    settings,
                    datetime(2026, 8, 9, 0, 0, second, tzinfo=UTC),
                    None,
                )
                self.assertEqual(decision.status, "due")
                self.assertEqual(decision.local_date, date(2026, 8, 9))

    def test_one_minute_before_and_after_are_not_due(self) -> None:
        settings = owner(timezone="Europe/Moscow", daily_send_time="10:00")
        for current in (
            datetime(2026, 8, 9, 6, 59, 59, tzinfo=UTC),
            datetime(2026, 8, 9, 7, 1, tzinfo=UTC),
        ):
            with self.subTest(current=current):
                self.assertEqual(
                    evaluate_daily_dispatch_due(settings, current, None).status,
                    "not_due",
                )

    def test_local_date_and_weekday_are_used_not_utc_values(self) -> None:
        settings = owner(
            timezone="Pacific/Honolulu",
            daily_send_time="14:00",
            daily_send_days="7",
        )
        current = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
        decision = evaluate_daily_dispatch_due(settings, current, None)
        self.assertEqual(decision.status, "due")
        self.assertEqual(decision.local_date, date(2026, 8, 9))

    def test_positive_offset_crosses_utc_date(self) -> None:
        settings = owner(timezone="Pacific/Kiritimati", daily_send_time="14:00")
        current = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
        decision = evaluate_daily_dispatch_due(settings, current, None)
        self.assertEqual(decision.local_date, date(2026, 8, 9))
        self.assertEqual(decision.status, "due")

    def test_dst_timezone_uses_local_wall_clock(self) -> None:
        settings = owner(timezone="America/New_York", daily_send_time="01:30")
        current = datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
        decision = evaluate_daily_dispatch_due(settings, current, None)
        self.assertEqual(decision.status, "due")
        self.assertEqual(decision.local_date, date(2026, 11, 1))

    def test_onboarding_disabled_is_not_due(self) -> None:
        self.assertEqual(
            evaluate_daily_dispatch_due(
                owner(onboarding_completed=False),
                datetime(2026, 8, 9, 7, tzinfo=UTC),
                None,
            ).status,
            "not_due",
        )

    def test_daily_sending_disabled_is_not_due(self) -> None:
        self.assertEqual(
            evaluate_daily_dispatch_due(
                owner(daily_sending_enabled=False),
                datetime(2026, 8, 9, 7, tzinfo=UTC),
                None,
            ).status,
            "not_due",
        )

    def test_unselected_weekday_is_not_due(self) -> None:
        settings = owner(daily_send_days="1")
        decision = evaluate_daily_dispatch_due(settings, datetime(2026, 8, 9, 7, tzinfo=UTC), None)
        self.assertEqual(decision.status, "not_due")

    def test_same_local_date_is_already_sent(self) -> None:
        settings = owner()
        decision = evaluate_daily_dispatch_due(
            settings,
            datetime(2026, 8, 9, 7, 15, tzinfo=UTC),
            date(2026, 8, 9),
        )
        self.assertEqual(decision.status, "not_due")

        decision = evaluate_daily_dispatch_due(
            settings,
            datetime(2026, 8, 9, 7, tzinfo=UTC),
            date(2026, 8, 9),
        )
        self.assertEqual(decision.status, "already_sent")

    def test_previous_local_date_allows_new_delivery(self) -> None:
        decision = evaluate_daily_dispatch_due(
            owner(), datetime(2026, 8, 9, 7, tzinfo=UTC), date(2026, 8, 8)
        )
        self.assertEqual(decision.status, "due")

    def test_invalid_time_days_timezone_and_current_time_are_safe_errors(self) -> None:
        cases = (
            owner(daily_send_time="25:00"),
            owner(daily_send_days="1,1"),
            owner(timezone="Not/AZone"),
        )
        for settings in cases:
            with self.subTest(settings=settings):
                with self.assertRaises(DailyDispatchError):
                    evaluate_daily_dispatch_due(settings, datetime(2026, 8, 9, 7, tzinfo=UTC), None)
        with self.assertRaises(DailyDispatchError):
            evaluate_daily_dispatch_due(owner(), datetime(2026, 8, 9, 7), None)


class DailyDispatchRunTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.runtime_path = Path(self.directory.name) / "runtime.sqlite3"
        self.runtime = SQLiteRuntimeStateStore(self.runtime_path)
        self.current_time = datetime(2026, 8, 9, 7, tzinfo=UTC)
        self.weather = Mock()
        self.geomagnetic = Mock()
        self.climate = Mock()
        self.historical = Mock()
        self.telegram = Mock()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def run_dispatch(self, settings: UserSettings | None = None):
        return run_daily_dispatch_once(
            owner=settings or owner(),
            runtime_state=self.runtime,
            weather_client=self.weather,
            geomagnetic_client=self.geomagnetic,
            climate_cache=self.climate,
            historical_client=self.historical,
            telegram_client=self.telegram,
            current_time=self.current_time,
        )

    def test_not_due_does_not_call_any_external_dependency(self) -> None:
        result = self.run_dispatch(owner(daily_send_time="11:00"))
        self.assertEqual(result.status, "not_due")
        self.weather.fetch.assert_not_called()
        self.geomagnetic.fetch.assert_not_called()
        self.historical.fetch.assert_not_called()
        self.telegram.send_message.assert_not_called()
        self.climate.get.assert_not_called()

    def test_already_sent_does_not_call_any_external_dependency(self) -> None:
        self.runtime.mark_daily_delivery_success(42, date(2026, 8, 9), self.current_time)
        result = self.run_dispatch()
        self.assertEqual(result.status, "already_sent")
        self.weather.fetch.assert_not_called()
        self.geomagnetic.fetch.assert_not_called()
        self.historical.fetch.assert_not_called()
        self.telegram.send_message.assert_not_called()
        self.climate.get.assert_not_called()

    @patch("weather_alert_bot.daily_dispatch.build_production_daily_report", return_value="REPORT")
    def test_due_builds_once_sends_once_then_marks_state(self, report: Mock) -> None:
        result = self.run_dispatch()
        self.assertEqual(result.status, "sent")
        report.assert_called_once()
        self.telegram.send_message.assert_called_once_with(chat_id=42, text="REPORT")
        state = self.runtime.get_daily_delivery_state(42)
        self.assertEqual(state.last_successful_local_date, date(2026, 8, 9))

    @patch("weather_alert_bot.daily_dispatch.build_production_daily_report", return_value="REPORT")
    def test_repeated_tick_after_success_has_no_duplicate(self, report: Mock) -> None:
        self.assertEqual(self.run_dispatch().status, "sent")
        self.telegram.reset_mock()
        second = self.run_dispatch()
        self.assertEqual(second.status, "already_sent")
        report.assert_called_once()
        self.telegram.send_message.assert_not_called()

    @patch(
        "weather_alert_bot.daily_dispatch.build_production_daily_report",
        side_effect=WeatherForecastError("private weather"),
    )
    def test_report_failure_does_not_mark_state(self, report: Mock) -> None:
        with self.assertRaises(DailyDispatchError):
            self.run_dispatch()
        self.telegram.send_message.assert_not_called()
        self.assertIsNone(self.runtime.get_daily_delivery_state(42))

    @patch("weather_alert_bot.daily_dispatch.build_production_daily_report", return_value="REPORT")
    def test_telegram_failure_does_not_mark_state(self, report: Mock) -> None:
        self.telegram.send_message.side_effect = TelegramApiError("private telegram")
        with self.assertRaises(DailyDispatchError):
            self.run_dispatch()
        self.assertIsNone(self.runtime.get_daily_delivery_state(42))

    @patch("weather_alert_bot.daily_dispatch.build_production_daily_report", return_value="REPORT")
    def test_runtime_write_failure_after_send_does_not_send_again(self, report: Mock) -> None:
        self.runtime.mark_daily_delivery_success = Mock(  # type: ignore[method-assign]
            side_effect=RuntimeStateError("private state")
        )
        with self.assertRaises(DailyDispatchError):
            self.run_dispatch()
        self.telegram.send_message.assert_called_once_with(chat_id=42, text="REPORT")
        report.assert_called_once()


if __name__ == "__main__":
    unittest.main()
