import io
import os
from pathlib import Path
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from weather_alert_bot.app import main
from weather_alert_bot.storage import StorageError


TEST_TOKEN = "123456789:TEST_TOKEN_NOT_REAL"
FIXED_NOW = datetime(2026, 8, 10, 21, tzinfo=ZoneInfo("UTC"))


class TodayCliTest(unittest.TestCase):
    def test_mode_requires_token_safely(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(["--wait-for-today"])

        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Ошибка обработки команды /today", stderr.getvalue())
        self.assertNotIn(TEST_TOKEN, stderr.getvalue())

    def test_mode_uses_read_only_storage_existing_clients_and_aware_now(self) -> None:
        settings = SimpleNamespace(
            telegram_bot_token=TEST_TOKEN,
            db_path=Path("/tmp/test-today-settings.sqlite3"),
            climate_db_path=Path("/tmp/test-today-climate.sqlite3"),
            runtime_db_path=Path("/tmp/test-today-runtime.sqlite3"),
        )
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TEST_TOKEN}, clear=True):
            with patch("weather_alert_bot.app.load_settings", return_value=settings):
                with patch("weather_alert_bot.app.TelegramClient") as client_type:
                    with patch("weather_alert_bot.app.SQLiteSettingsStore") as storage_type:
                        with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
                            with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as kp_type:
                                with patch("weather_alert_bot.app.SQLiteClimateNormalsCache") as climate_type:
                                    with patch("weather_alert_bot.app.OpenMeteoHistoricalWeatherClient") as historical_type:
                                        with patch("weather_alert_bot.app.datetime") as datetime_type:
                                            datetime_type.now.return_value = FIXED_NOW
                                            with patch(
                                                "weather_alert_bot.app.run_until_today",
                                                return_value=0,
                                            ) as handler:
                                                result = main(["--wait-for-today"])

        self.assertEqual(result, 0)
        client_type.assert_called_once_with(TEST_TOKEN)
        storage_type.assert_called_once_with(settings.db_path, read_only=True)
        weather_type.assert_called_once_with()
        kp_type.assert_called_once_with()
        climate_type.assert_called_once_with(settings.climate_db_path)
        historical_type.assert_called_once_with()
        handler.assert_called_once_with(
            client_type.return_value,
            storage_type.return_value,
            weather_type.return_value,
            kp_type.return_value,
            climate_type.return_value,
            historical_type.return_value,
            FIXED_NOW,
        )
        self.assertIsNotNone(FIXED_NOW.tzinfo)

    def test_handler_storage_error_is_safe(self) -> None:
        output = io.StringIO()
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TEST_TOKEN}, clear=True):
            with patch(
                "weather_alert_bot.app.run_until_today",
                side_effect=StorageError("private SQLite path and details"),
            ):
                with patch("weather_alert_bot.app.SQLiteClimateNormalsCache"):
                    with redirect_stdout(output), redirect_stderr(output):
                        result = main(["--wait-for-today"])

        self.assertEqual(result, 1)
        self.assertIn("Ошибка обработки команды /today", output.getvalue())
        self.assertNotIn("private SQLite path and details", output.getvalue())

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
            "--preview-daily-summary",
            "--run-daily-dispatch-once",
            "--geocode-city",
        )
        for action in actions:
            arguments = ["--wait-for-today", action]
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
        self.assertIn("--wait-for-today", output.getvalue())


if __name__ == "__main__":
    unittest.main()
