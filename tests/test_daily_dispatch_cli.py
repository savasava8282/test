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
from weather_alert_bot.daily_dispatch import DailyDispatchResult
from weather_alert_bot.storage import UserSettings


TEST_TOKEN = "123456789:TEST_TOKEN_NOT_REAL"
FIXED_NOW = datetime(2026, 8, 9, 7, tzinfo=ZoneInfo("UTC"))


def settings() -> SimpleNamespace:
    return SimpleNamespace(
        telegram_bot_token=TEST_TOKEN,
        db_path=Path("/tmp/dispatch-settings.sqlite3"),
        climate_db_path=Path("/tmp/dispatch-climate.sqlite3"),
        runtime_db_path=Path("/tmp/dispatch-runtime.sqlite3"),
    )


def owner() -> UserSettings:
    return UserSettings(
        telegram_chat_id=42,
        city_name="Москва",
        latitude=55.75204,
        longitude=37.61781,
        timezone="Europe/Moscow",
        daily_send_time="10:00",
        daily_send_days="1,2,3,4,5,6,7",
        onboarding_completed=True,
    )


class DailyDispatchCliTest(unittest.TestCase):
    def test_mode_requires_token_safely(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(["--run-daily-dispatch-once"])

        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Ошибка выполнения ежедневной рассылки", stderr.getvalue())
        self.assertNotIn(TEST_TOKEN, stderr.getvalue())

    def test_mode_wires_read_only_settings_runtime_path_and_one_aware_now(self) -> None:
        configured = settings()
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TEST_TOKEN}, clear=True):
            with patch("weather_alert_bot.app.load_settings", return_value=configured):
                with patch("weather_alert_bot.app.TelegramClient") as telegram_type:
                    with patch("weather_alert_bot.app.SQLiteSettingsStore") as storage_type:
                        storage_type.return_value.get_single_user_settings.return_value = owner()
                        with patch("weather_alert_bot.app.SQLiteRuntimeStateStore") as runtime_type:
                            runtime_type.return_value.get_daily_delivery_state.return_value = None
                            with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
                                with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as kp_type:
                                    with patch("weather_alert_bot.app.SQLiteClimateNormalsCache") as climate_type:
                                        with patch("weather_alert_bot.app.OpenMeteoHistoricalWeatherClient") as historical_type:
                                            with patch("weather_alert_bot.app.datetime") as datetime_type:
                                                datetime_type.now.return_value = FIXED_NOW
                                                with patch(
                                                    "weather_alert_bot.app.run_daily_dispatch_once",
                                                    return_value=DailyDispatchResult("not_due", FIXED_NOW.date()),
                                                ) as dispatch:
                                                    result = main(["--run-daily-dispatch-once"])

        self.assertEqual(result, 0)
        telegram_type.assert_called_once_with(TEST_TOKEN)
        storage_type.assert_called_once_with(configured.db_path, read_only=True)
        runtime_type.assert_called_once_with(configured.runtime_db_path)
        weather_type.assert_called_once_with()
        kp_type.assert_called_once_with()
        climate_type.assert_called_once_with(configured.climate_db_path)
        historical_type.assert_called_once_with()
        self.assertEqual(dispatch.call_args.kwargs["current_time"], FIXED_NOW)
        self.assertIsNotNone(dispatch.call_args.kwargs["current_time"].tzinfo)

    def test_not_due_output_is_stable(self) -> None:
        output = io.StringIO()
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TEST_TOKEN}, clear=True):
            with patch("weather_alert_bot.app.load_settings", return_value=settings()):
                with patch("weather_alert_bot.app.TelegramClient"):
                    with patch("weather_alert_bot.app.SQLiteSettingsStore") as storage_type:
                        storage_type.return_value.get_single_user_settings.return_value = owner()
                        with patch("weather_alert_bot.app.SQLiteRuntimeStateStore") as runtime_type:
                            runtime_type.return_value.get_daily_delivery_state.return_value = None
                            with patch("weather_alert_bot.app.datetime") as datetime_type:
                                datetime_type.now.return_value = FIXED_NOW
                                with patch(
                                    "weather_alert_bot.app.evaluate_daily_dispatch_due",
                                    return_value=SimpleNamespace(status="not_due"),
                                ):
                                    with redirect_stdout(output):
                                        result = main(["--run-daily-dispatch-once"])
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue(), "Ежедневная сводка сейчас не запланирована.\n")

    def test_help_and_mutual_exclusion(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--run-daily-dispatch-once", output.getvalue())

        with self.assertRaises(SystemExit) as raised:
            main(["--run-daily-dispatch-once", "--wait-for-today"])
        self.assertEqual(raised.exception.code, 2)

    def test_sent_and_already_sent_outputs_are_stable(self) -> None:
        for status, expected in (
            ("sent", "Ежедневная сводка отправлена по расписанию.\n"),
            ("already_sent", "Ежедневная сводка за текущий день уже отправлена.\n"),
        ):
            with self.subTest(status=status):
                output = io.StringIO()
                with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TEST_TOKEN}, clear=True):
                    with patch("weather_alert_bot.app.load_settings", return_value=settings()):
                        with patch("weather_alert_bot.app.TelegramClient"):
                            with patch("weather_alert_bot.app.SQLiteSettingsStore") as storage_type:
                                storage_type.return_value.get_single_user_settings.return_value = owner()
                                with patch("weather_alert_bot.app.SQLiteRuntimeStateStore") as runtime_type:
                                    runtime_type.return_value.get_daily_delivery_state.return_value = None
                                    with patch("weather_alert_bot.app.datetime") as datetime_type:
                                        datetime_type.now.return_value = FIXED_NOW
                                        with patch(
                                            "weather_alert_bot.app.evaluate_daily_dispatch_due",
                                            return_value=SimpleNamespace(status="due"),
                                        ):
                                            with patch(
                                                "weather_alert_bot.app.run_daily_dispatch_once",
                                                return_value=DailyDispatchResult(status, FIXED_NOW.date()),
                                            ):
                                                with redirect_stdout(output):
                                                    result = main(["--run-daily-dispatch-once"])
                self.assertEqual(result, 0)
                self.assertEqual(output.getvalue(), expected)


if __name__ == "__main__":
    unittest.main()
