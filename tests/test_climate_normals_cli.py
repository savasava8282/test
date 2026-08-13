from datetime import datetime, timezone
import io
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from weather_alert_bot.app import main
from weather_alert_bot.climate_normals import (
    BASELINE_END,
    BASELINE_START,
    ClimateNormalsError,
    HistoricalTemperatureDay,
)
from weather_alert_bot.geocoding import GeocodingLocation
from weather_alert_bot.storage import SQLiteSettingsStore


def city(timezone_name: str = "Europe/Moscow") -> GeocodingLocation:
    return GeocodingLocation(
        id=1,
        name="Москва",
        latitude=55.75204,
        longitude=37.61781,
        timezone=timezone_name,
        country_code="RU",
        country="Россия",
    )


def records() -> tuple[HistoricalTemperatureDay, ...]:
    from datetime import timedelta

    return tuple(
        HistoricalTemperatureDay(
            BASELINE_START + timedelta(days=offset),
            8.0,
            18.0,
        )
        for offset in range((BASELINE_END - BASELINE_START).days + 1)
    )


class ClimateNormalsCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "settings.sqlite3"
        SQLiteSettingsStore(self.path).save_confirmed_city(42, city())

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
                result = main(["--preview-climate-normal"])
        return result, stdout.getvalue(), stderr.getvalue()

    def test_success_uses_saved_settings_one_historical_request_and_aware_now(self) -> None:
        before = self.path.read_bytes()
        with patch("weather_alert_bot.app.OpenMeteoHistoricalWeatherClient") as climate_type:
            climate_type.return_value.fetch.return_value = records()
            with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
                with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as kp_type:
                    with patch("weather_alert_bot.app.TelegramClient") as telegram_type:
                        with patch("weather_alert_bot.app.datetime") as datetime_type:
                            now = datetime(2026, 8, 11, 21, tzinfo=timezone.utc)
                            datetime_type.now.return_value = now
                            result, stdout, stderr = self.run_cli()

        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        climate_type.assert_called_once_with()
        climate_type.return_value.fetch.assert_called_once_with(
            55.75204, 37.61781, "Europe/Moscow"
        )
        weather_type.assert_not_called()
        kp_type.assert_not_called()
        telegram_type.assert_not_called()
        datetime_type.now.assert_called_once_with(timezone.utc)
        self.assertIn("Климатическая норма: 12 августа", stdout)
        self.assertIn("Обычный минимум: +8.0 °C", stdout)
        self.assertEqual(self.path.read_bytes(), before)

    def test_no_telegram_token_is_required_and_invalid_timezone_is_safe(self) -> None:
        SQLiteSettingsStore(self.path).save_confirmed_city(42, city("No/Such_Zone"))
        with patch("weather_alert_bot.app.OpenMeteoHistoricalWeatherClient") as climate_type:
            result, stdout, stderr = self.run_cli()
        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Ошибка получения климатической нормы.", stderr)
        climate_type.assert_not_called()

    def test_missing_settings_and_client_error_are_safe(self) -> None:
        empty_path = self.path.with_name("empty.sqlite3")
        SQLiteSettingsStore(empty_path)
        with patch.dict(os.environ, {"WEATHER_ALERT_BOT_DB_PATH": str(empty_path)}, clear=True):
            output = io.StringIO()
            with redirect_stdout(output), redirect_stderr(output):
                result = main(["--preview-climate-normal"])
        self.assertEqual(result, 1)
        self.assertIn("Сохранённый город не найден.", output.getvalue())

        with patch("weather_alert_bot.app.OpenMeteoHistoricalWeatherClient") as climate_type:
            climate_type.return_value.fetch.side_effect = ClimateNormalsError("private body")
            result, stdout, stderr = self.run_cli()
        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Ошибка получения климатической нормы.", stderr)
        self.assertNotIn("private body", stderr)

    def test_mode_is_mutually_exclusive_with_all_existing_actions_and_help(self) -> None:
        actions = (
            "--check-telegram", "--wait-for-start", "--wait-for-city",
            "--wait-for-geocoded-city", "--wait-for-confirmed-city",
            "--wait-for-daily-time", "--wait-for-daily-days",
            "--wait-for-daily-sending", "--wait-for-urgent-warnings",
            "--wait-for-warning-categories", "--wait-for-settings-summary",
            "--wait-for-onboarding-complete", "--fetch-weather-forecast",
            "--fetch-kp-forecast", "--preview-daily-summary",
            "--preview-current-risks", "--wait-for-today", "--geocode-city",
        )
        for action in actions:
            arguments = ["--preview-climate-normal", action]
            if action == "--geocode-city":
                arguments.append("Москва")
            with self.subTest(arguments=arguments):
                with self.assertRaises(SystemExit) as raised:
                    main(arguments)
                self.assertEqual(raised.exception.code, 2)

        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--preview-climate-normal", output.getvalue())


if __name__ == "__main__":
    unittest.main()
