import io
import os
from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
from zoneinfo import ZoneInfo

from weather_alert_bot.app import main
from weather_alert_bot.daily_summary import DailySummaryError
from weather_alert_bot.geocoding import GeocodingLocation
from weather_alert_bot.geomagnetic_forecast import (
    GeomagneticForecast,
    GeomagneticForecastError,
    GeomagneticForecastInterval,
)
from weather_alert_bot.storage import SQLiteSettingsStore
from weather_alert_bot.weather_forecast import (
    DailyForecast,
    HourlyForecast,
    WeatherForecast,
    WeatherForecastError,
)


FIXED_NOW = datetime(2026, 8, 10, 21, tzinfo=ZoneInfo("UTC"))
SUMMARY_DATE = date(2026, 8, 11)


def city() -> GeocodingLocation:
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
                kp=5.67,
                status="predicted",
            ),
        )
    )


class DailySummaryCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "settings.sqlite3"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def run_cli(self) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(
            os.environ,
            {"WEATHER_ALERT_BOT_DB_PATH": str(self.path)},
            clear=True,
        ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(["--preview-daily-summary"])
        return result, stdout.getvalue(), stderr.getvalue()

    def save_city(self) -> None:
        SQLiteSettingsStore(self.path).save_confirmed_city(42, city())

    def test_success_wires_both_clients_and_prints_summary_without_token(self) -> None:
        self.save_city()
        before = self.path.read_bytes()
        with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
            weather_type.return_value.fetch.return_value = weather()
            with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as kp_type:
                kp_type.return_value.fetch.return_value = geomagnetic()
                with patch("weather_alert_bot.app.datetime") as datetime_type:
                    datetime_type.now.return_value = FIXED_NOW
                    result, stdout, stderr = self.run_cli()

        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        weather_type.assert_called_once_with()
        weather_type.return_value.fetch.assert_called_once_with(
            55.75204,
            37.61781,
            "Europe/Moscow",
        )
        kp_type.assert_called_once_with()
        kp_type.return_value.fetch.assert_called_once_with()
        self.assertIn("📍 Москва", stdout)
        self.assertIn("Погода: дождь", stdout)
        self.assertIn("Магнитная активность: Kp до 5.67", stdout)
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_city_is_safe_and_clients_are_not_called(self) -> None:
        SQLiteSettingsStore(self.path)
        with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
            with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as kp_type:
                result, stdout, stderr = self.run_cli()

        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Сохранённый город не найден.", stderr)
        weather_type.assert_not_called()
        kp_type.assert_not_called()

    def test_weather_error_is_safe(self) -> None:
        self.save_city()
        with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
            weather_type.return_value.fetch.side_effect = WeatherForecastError("private")
            result, stdout, stderr = self.run_cli()

        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Ошибка получения прогноза погоды.", stderr)
        self.assertNotIn("private", stderr)

    def test_kp_error_is_safe(self) -> None:
        self.save_city()
        with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
            weather_type.return_value.fetch.return_value = weather()
            with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as kp_type:
                kp_type.return_value.fetch.side_effect = GeomagneticForecastError("private")
                result, stdout, stderr = self.run_cli()

        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Ошибка получения прогноза Kp NOAA SWPC.", stderr)
        self.assertNotIn("private", stderr)

    def test_summary_error_is_safe(self) -> None:
        self.save_city()
        with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
            weather_type.return_value.fetch.return_value = weather()
            with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as kp_type:
                kp_type.return_value.fetch.return_value = geomagnetic()
                with patch(
                    "weather_alert_bot.app.build_daily_summary",
                    side_effect=DailySummaryError("private summary details"),
                ):
                    result, stdout, stderr = self.run_cli()

        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Ошибка формирования ежедневной сводки.", stderr)
        self.assertNotIn("private summary details", stderr)

    def test_mode_is_mutually_exclusive_with_all_existing_actions(self) -> None:
        actions = (
            "--check-telegram",
            "--wait-for-start",
            "--wait-for-city",
            "--wait-for-geocoded-city",
            "--wait-for-confirmed-city",
            "--wait-for-daily-time",
            "--wait-for-daily-days",
            "--wait-for-daily-sending",
            "--wait-for-urgent-warnings",
            "--wait-for-warning-categories",
            "--wait-for-settings-summary",
            "--wait-for-onboarding-complete",
            "--fetch-weather-forecast",
            "--fetch-kp-forecast",
            "--geocode-city",
        )
        for action in actions:
            arguments = ["--preview-daily-summary", action]
            if action == "--geocode-city":
                arguments.append("Москва")
            with self.subTest(arguments=arguments):
                with self.assertRaises(SystemExit) as raised:
                    main(arguments)
                self.assertEqual(raised.exception.code, 2)

    def test_help_contains_mode(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                main(["--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--preview-daily-summary", output.getvalue())

