import io
import os
from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from weather_alert_bot.app import main
from weather_alert_bot.geocoding import GeocodingLocation
from weather_alert_bot.storage import SQLiteSettingsStore, StorageError
from weather_alert_bot.weather_forecast import (
    DailyForecast,
    HourlyForecast,
    WeatherForecast,
    WeatherForecastError,
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


def forecast() -> WeatherForecast:
    return WeatherForecast(
        latitude=55.75204,
        longitude=37.61781,
        timezone="Europe/Moscow",
        generation_time_ms=0.4,
        daily=(
            DailyForecast(
                date=date(2026, 8, 12),
                weather_code=1,
                temperature_2m_max=25.0,
                temperature_2m_min=15.0,
                precipitation_probability_max=40.0,
                precipitation_sum=2.5,
                wind_speed_10m_max=10.0,
                wind_gusts_10m_max=18.0,
            ),
        ),
        hourly=(
            HourlyForecast(
                time=datetime(2026, 8, 12, 0),
                temperature_2m=20.0,
                precipitation_probability=10.0,
                precipitation=0.0,
                weather_code=1,
                wind_speed_10m=5.0,
                wind_gusts_10m=8.0,
            ),
        ),
    )


class WeatherForecastStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "settings.sqlite3"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_single_user_read_api_returns_only_saved_user(self) -> None:
        store = SQLiteSettingsStore(self.path)
        store.save_confirmed_city(42, city())

        read_only_store = SQLiteSettingsStore(self.path, read_only=True)
        settings = read_only_store.get_single_user_settings()

        self.assertEqual(settings.city_name, "Москва")
        self.assertEqual(settings.latitude, 55.75204)
        self.assertEqual(settings.longitude, 37.61781)
        self.assertEqual(settings.timezone, "Europe/Moscow")

    def test_single_user_read_api_returns_none_without_saved_city(self) -> None:
        SQLiteSettingsStore(self.path)
        self.assertIsNone(
            SQLiteSettingsStore(self.path, read_only=True).get_single_user_settings()
        )

    def test_single_user_read_api_rejects_ambiguous_storage(self) -> None:
        store = SQLiteSettingsStore(self.path)
        store.save_confirmed_city(42, city())
        store.save_confirmed_city(
            43,
            GeocodingLocation(
                id=2,
                name="Сочи",
                latitude=43.58,
                longitude=39.72,
                timezone="Europe/Moscow",
                country_code="RU",
                country="Россия",
            ),
        )

        with self.assertRaises(StorageError):
            SQLiteSettingsStore(self.path, read_only=True).get_single_user_settings()


class WeatherForecastCliTest(unittest.TestCase):
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
                result = main(["--fetch-weather-forecast"])
        return result, stdout.getvalue(), stderr.getvalue()

    def test_saved_coordinates_timezone_are_used_and_sqlite_is_unchanged(self) -> None:
        SQLiteSettingsStore(self.path).save_confirmed_city(42, city())
        before = self.path.read_bytes()

        with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as client_type:
            client_type.return_value.fetch.return_value = forecast()
            result, stdout, stderr = self.run_cli()

        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        client_type.return_value.fetch.assert_called_once_with(
            55.75204,
            37.61781,
            "Europe/Moscow",
        )
        self.assertIn("Город: Москва", stdout)
        self.assertIn("Часовой пояс: Europe/Moscow", stdout)
        self.assertIn("Дней прогноза: 1", stdout)
        self.assertIn("Первая дата: 2026-08-12", stdout)
        self.assertIn("min=15, max=25", stdout)
        self.assertIn("Максимальная вероятность осадков: 40%", stdout)
        self.assertIn("Сумма осадков: 2.5", stdout)
        self.assertIn("Максимальный ветер: 10", stdout)
        self.assertIn("Максимальные порывы: 18", stdout)
        self.assertIn("Почасовых значений: 1", stdout)
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_saved_city_is_safe_and_does_not_fetch(self) -> None:
        SQLiteSettingsStore(self.path)
        with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as client_type:
            result, stdout, stderr = self.run_cli()

        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Сохранённый город не найден.", stderr)
        client_type.assert_not_called()

    def test_weather_error_is_reported_without_internal_details(self) -> None:
        SQLiteSettingsStore(self.path).save_confirmed_city(42, city())
        with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as client_type:
            client_type.return_value.fetch.side_effect = WeatherForecastError(
                "private HTTP body"
            )
            result, stdout, stderr = self.run_cli()

        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Ошибка получения прогноза погоды.", stderr)
        self.assertNotIn("private HTTP body", stderr)

    def test_mode_is_mutually_exclusive_with_all_existing_actions(self) -> None:
        existing_actions = (
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
            "--geocode-city",
        )
        for action in existing_actions:
            arguments = ["--fetch-weather-forecast", action]
            if action == "--geocode-city":
                arguments.append("Москва")
            with self.subTest(arguments=arguments):
                with self.assertRaises(SystemExit) as raised:
                    main(arguments)
                self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
