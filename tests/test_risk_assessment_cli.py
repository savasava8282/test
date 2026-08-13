from datetime import date, datetime, timedelta, timezone
import io
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import ANY, patch

from weather_alert_bot.app import main
from weather_alert_bot.climate_normals import (
    BASELINE_END,
    BASELINE_START,
    ClimateNormalDay,
    ClimateNormalsError,
    HistoricalTemperatureDay,
)
from weather_alert_bot.geocoding import GeocodingLocation
from weather_alert_bot.geomagnetic_forecast import (
    GeomagneticForecast,
    GeomagneticForecastError,
    GeomagneticForecastInterval,
)
from weather_alert_bot.risk_assessment import CurrentDayRiskAssessment, RiskAssessmentError
from weather_alert_bot.storage import SQLiteSettingsStore
from weather_alert_bot.weather_forecast import (
    DailyForecast,
    HourlyForecast,
    WeatherForecast,
    WeatherForecastError,
)


def historical_records() -> tuple[HistoricalTemperatureDay, ...]:
    return tuple(
        HistoricalTemperatureDay(
            BASELINE_START + timedelta(days=offset),
            8.0,
            18.0,
        )
        for offset in range((BASELINE_END - BASELINE_START).days + 1)
    )


def climate_normal() -> ClimateNormalDay:
    return ClimateNormalDay(
        month=8,
        day=12,
        normal_temperature_min=8.0,
        normal_temperature_max=18.0,
        sample_count=30,
    )


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
        daily=(DailyForecast(
            date=datetime(2026, 8, 12).date(), weather_code=0,
            temperature_2m_max=20, temperature_2m_min=10,
            precipitation_probability_max=0, precipitation_sum=0,
            wind_speed_10m_max=0, wind_gusts_10m_max=0,
        ),),
        hourly=(HourlyForecast(
            time=datetime(2026, 8, 12, 12), temperature_2m=15,
            precipitation_probability=0, precipitation=0, weather_code=0,
            wind_speed_10m=0, wind_gusts_10m=0,
        ),),
    )


def geomagnetic() -> GeomagneticForecast:
    return GeomagneticForecast(intervals=(GeomagneticForecastInterval(
        timestamp=datetime(2026, 8, 11, 22), kp=7,
        status="predicted",
    ),))


class RiskAssessmentCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "settings.sqlite3"
        self.historical_client_patch = patch(
            "weather_alert_bot.app.OpenMeteoHistoricalWeatherClient"
        )
        self.historical_type = self.historical_client_patch.start()
        self.historical_type.return_value.fetch.return_value = historical_records()

    def tearDown(self) -> None:
        self.historical_client_patch.stop()
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
                result = main(["--preview-current-risks"])
        return result, stdout.getvalue(), stderr.getvalue()

    def save_city(self) -> None:
        SQLiteSettingsStore(self.path).save_confirmed_city(42, city())

    def test_success_uses_saved_coordinates_timezone_and_both_fake_clients(self) -> None:
        self.save_city()
        before = self.path.read_bytes()
        with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
            weather_type.return_value.fetch.return_value = weather()
            with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as kp_type:
                kp_type.return_value.fetch.return_value = geomagnetic()
                with patch("weather_alert_bot.app.datetime") as datetime_type:
                    datetime_type.now.return_value = datetime(2026, 8, 11, 21, tzinfo=timezone.utc)
                    result, stdout, stderr = self.run_cli()

        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        weather_type.assert_called_once_with()
        weather_type.return_value.fetch.assert_called_once_with(55.75204, 37.61781, "Europe/Moscow")
        kp_type.assert_called_once_with()
        kp_type.return_value.fetch.assert_called_once_with()
        self.assertIn("Дата: 12.08.2026", stdout)
        self.assertIn("magnetic_storm", stdout)
        self.assertNotIn("Не оцениваются на этом этапе", stdout)
        self.historical_type.assert_called_once_with()
        self.historical_type.return_value.fetch.assert_called_once_with(
            55.75204, 37.61781, "Europe/Moscow"
        )
        self.assertEqual(self.path.read_bytes(), before)

    def test_no_telegram_token_is_required_and_telegram_is_not_called(self) -> None:
        self.save_city()
        with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
            weather_type.return_value.fetch.return_value = weather()
            with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as kp_type:
                kp_type.return_value.fetch.return_value = geomagnetic()
                with patch("weather_alert_bot.app.TelegramClient") as telegram_type:
                    with patch("weather_alert_bot.app.datetime") as datetime_type:
                        datetime_type.now.return_value = datetime(2026, 8, 11, 21, tzinfo=timezone.utc)
                        result, _, stderr = self.run_cli()
        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        telegram_type.assert_not_called()

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

    def test_storage_error_is_safe(self) -> None:
        with patch("weather_alert_bot.app.SQLiteSettingsStore") as store_type:
            from weather_alert_bot.storage import StorageError
            store_type.side_effect = StorageError("private sqlite contents")
            result, stdout, stderr = self.run_cli()
        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Ошибка чтения сохранённых настроек города.", stderr)
        self.assertNotIn("private sqlite contents", stderr)

    def test_weather_error_is_safe(self) -> None:
        self.save_city()
        with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
            weather_type.return_value.fetch.side_effect = WeatherForecastError("private HTTP body")
            result, stdout, stderr = self.run_cli()
        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Ошибка получения прогноза погоды.", stderr)
        self.assertNotIn("private HTTP body", stderr)

    def test_kp_error_is_safe(self) -> None:
        self.save_city()
        with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
            weather_type.return_value.fetch.return_value = weather()
            with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as kp_type:
                kp_type.return_value.fetch.side_effect = GeomagneticForecastError("private NOAA body")
                result, stdout, stderr = self.run_cli()
        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Ошибка получения прогноза Kp NOAA SWPC.", stderr)
        self.assertNotIn("private NOAA body", stderr)

    def test_risk_error_is_safe(self) -> None:
        self.save_city()
        with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
            weather_type.return_value.fetch.return_value = weather()
            with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as kp_type:
                kp_type.return_value.fetch.return_value = geomagnetic()
                with patch("weather_alert_bot.app.assess_current_day_risks", side_effect=RiskAssessmentError("private risk details")):
                    result, stdout, stderr = self.run_cli()
        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Ошибка формирования оценки рисков текущего дня.", stderr)
        self.assertNotIn("private risk details", stderr)

    def test_historical_failure_is_safe(self) -> None:
        self.save_city()
        self.historical_type.return_value.fetch.side_effect = ClimateNormalsError(
            "private historical details"
        )
        with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
            weather_type.return_value.fetch.return_value = weather()
            with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as kp_type:
                kp_type.return_value.fetch.return_value = geomagnetic()
                result, stdout, stderr = self.run_cli()
        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Ошибка получения климатической нормы.", stderr)
        self.assertNotIn("private historical details", stderr)

    def test_calculation_lookup_and_same_aware_time_are_used_for_risk_assessment(self) -> None:
        self.save_city()
        current_time = datetime(2026, 8, 11, 21, tzinfo=timezone.utc)
        normal = climate_normal()
        calculated_normals = object()
        assessment = CurrentDayRiskAssessment(
            local_date=date(2026, 8, 12),
            signals=(),
            unsupported_categories=(),
        )
        with patch("weather_alert_bot.app.calculate_climate_normals", return_value=calculated_normals) as calculate:
            with patch("weather_alert_bot.app.get_climate_normal_for_date", return_value=normal) as lookup:
                with patch("weather_alert_bot.app.assess_current_day_risks", return_value=assessment) as assess:
                    with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
                        weather_type.return_value.fetch.return_value = weather()
                        with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as kp_type:
                            kp_type.return_value.fetch.return_value = geomagnetic()
                            with patch("weather_alert_bot.app.datetime") as datetime_type:
                                datetime_type.now.return_value = current_time
                                result, stdout, stderr = self.run_cli()

        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        self.assertIn("Дата: 12.08.2026", stdout)
        datetime_type.now.assert_called_once_with(timezone.utc)
        calculate.assert_called_once()
        lookup.assert_called_once_with(calculated_normals, date(2026, 8, 12))
        assess.assert_called_once_with(
            ANY,
            ANY,
            "Europe/Moscow",
            current_time,
            climate_normal=normal,
        )

    def test_current_risks_does_not_create_telegram_or_call_today(self) -> None:
        self.save_city()
        with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
            weather_type.return_value.fetch.return_value = weather()
            with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as kp_type:
                kp_type.return_value.fetch.return_value = geomagnetic()
                with patch("weather_alert_bot.app.TelegramClient") as telegram_type:
                    with patch("weather_alert_bot.app.run_until_today") as today:
                        with patch("weather_alert_bot.app.datetime") as datetime_type:
                            datetime_type.now.return_value = datetime(2026, 8, 11, 21, tzinfo=timezone.utc)
                            result, _, stderr = self.run_cli()
        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        telegram_type.assert_not_called()
        today.assert_not_called()

    def test_mode_is_mutually_exclusive_with_all_existing_actions(self) -> None:
        actions = (
            "--check-telegram", "--wait-for-start", "--wait-for-city",
            "--wait-for-geocoded-city", "--wait-for-confirmed-city",
            "--wait-for-daily-time", "--wait-for-daily-days",
            "--wait-for-daily-sending", "--wait-for-urgent-warnings",
            "--wait-for-warning-categories", "--wait-for-settings-summary",
            "--wait-for-onboarding-complete", "--fetch-weather-forecast",
            "--fetch-kp-forecast", "--preview-daily-summary", "--wait-for-today",
            "--geocode-city",
        )
        for action in actions:
            arguments = ["--preview-current-risks", action]
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
        self.assertIn("--preview-current-risks", output.getvalue())


if __name__ == "__main__":
    unittest.main()
