import io
from contextlib import redirect_stderr
from datetime import datetime
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from weather_alert_bot.climate_cache import ClimateCacheError
from weather_alert_bot.daily_report import (
    CLIMATE_FALLBACK_DIAGNOSTIC,
    build_production_daily_report,
)
from weather_alert_bot.storage import UserSettings


class DailyReportServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.owner = UserSettings(
            telegram_chat_id=42,
            city_name="Москва",
            latitude=55.75,
            longitude=37.61,
            timezone="Europe/Moscow",
            onboarding_completed=True,
        )
        self.formed_at = datetime(2026, 8, 9, 7, tzinfo=ZoneInfo("UTC"))
        self.weather = object()
        self.geomagnetic = object()
        self.summary = object()
        self.assessment = object()
        self.weather_client = Mock()
        self.weather_client.fetch.return_value = self.weather
        self.geomagnetic_client = Mock()
        self.geomagnetic_client.fetch.return_value = self.geomagnetic
        self.cache = Mock()
        self.historical = Mock()

    def test_service_owns_single_fetch_and_shared_report_composition(self) -> None:
        assessor = Mock(return_value=self.assessment)
        with patch("weather_alert_bot.daily_report.build_daily_summary", return_value=self.summary) as builder:
            with patch("weather_alert_bot.daily_report.format_daily_risk_section", return_value="RISK") as risk_formatter:
                with patch("weather_alert_bot.daily_report.format_daily_summary", return_value="REPORT") as formatter:
                    with patch("weather_alert_bot.daily_report.get_or_create_climate_normals", return_value=object()):
                        with patch("weather_alert_bot.daily_report.local_calendar_date", return_value=self.formed_at.date()):
                            with patch("weather_alert_bot.daily_report.get_climate_normal_for_date", return_value=object()):
                                result = build_production_daily_report(
                                    owner=self.owner,
                                    weather_client=self.weather_client,
                                    geomagnetic_client=self.geomagnetic_client,
                                    climate_cache=self.cache,
                                    historical_client=self.historical,
                                    formed_at=self.formed_at,
                                    risk_assessor=assessor,
                                )

        self.assertEqual(result, "REPORT")
        self.weather_client.fetch.assert_called_once()
        self.geomagnetic_client.fetch.assert_called_once()
        builder.assert_called_once_with(self.owner, self.weather, self.geomagnetic, self.formed_at)
        climate_normal = assessor.call_args.kwargs["climate_normal"]
        self.assertIsNotNone(climate_normal)
        assessor.assert_called_once_with(
            self.weather,
            self.geomagnetic,
            self.owner.timezone,
            self.formed_at,
            climate_normal=climate_normal,
        )
        risk_formatter.assert_called_once_with(self.assessment, self.owner)
        formatter.assert_called_once_with(self.summary, risk_section="RISK")

    def test_climate_only_failure_keeps_report_and_passes_no_normal(self) -> None:
        captured: list[object] = []

        def assess(*args: object, **kwargs: object) -> object:
            captured.append(kwargs["climate_normal"])
            return self.assessment

        stderr = io.StringIO()
        with patch("weather_alert_bot.daily_report.build_daily_summary", return_value=self.summary):
            with patch("weather_alert_bot.daily_report.get_or_create_climate_normals", side_effect=ClimateCacheError("private")):
                with patch("weather_alert_bot.daily_report.format_daily_risk_section", return_value="RISK"):
                    with patch("weather_alert_bot.daily_report.format_daily_summary", return_value="REPORT"):
                        with redirect_stderr(stderr):
                            result = build_production_daily_report(
                                owner=self.owner,
                                weather_client=self.weather_client,
                                geomagnetic_client=self.geomagnetic_client,
                                climate_cache=self.cache,
                                historical_client=self.historical,
                                formed_at=self.formed_at,
                                risk_assessor=assess,
                            )

        self.assertEqual(result, "REPORT")
        self.assertEqual(captured, [None])
        self.assertIn(CLIMATE_FALLBACK_DIAGNOSTIC, stderr.getvalue())
        self.assertNotIn("private", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
