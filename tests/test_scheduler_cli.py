import io
import os
from pathlib import Path
import signal
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from weather_alert_bot.app import main


TEST_TOKEN = "123456789:TEST_TOKEN_NOT_REAL"


def settings() -> SimpleNamespace:
    return SimpleNamespace(
        telegram_bot_token=TEST_TOKEN,
        db_path=Path("/tmp/scheduler-settings.sqlite3"),
        climate_db_path=Path("/tmp/scheduler-climate.sqlite3"),
        runtime_db_path=Path("/tmp/scheduler-runtime.sqlite3"),
    )


class SchedulerCliTest(unittest.TestCase):
    def test_mode_requires_token_without_leaking_configuration(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(["--run-scheduler"])

        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "Ошибка запуска планировщика.\n")
        self.assertNotIn(TEST_TOKEN, stderr.getvalue())

    def test_mode_is_mutually_exclusive_with_existing_actions(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            main(["--run-scheduler", "--run-daily-dispatch-once"])
        self.assertEqual(raised.exception.code, 2)

    def test_mode_wires_configured_read_only_and_writable_paths(self) -> None:
        configured = settings()
        output = io.StringIO()
        signal_handlers: dict[int, object] = {}

        def fake_signal(signum: int, handler: object) -> object:
            signal_handlers[signum] = handler
            return handler

        def fake_loop(**kwargs: object) -> None:
            stop_event = kwargs["stop_event"]
            signal_handlers[signal.SIGTERM](signal.SIGTERM, None)  # type: ignore[index]
            self.assertTrue(stop_event.is_set())

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TEST_TOKEN}, clear=True):
            with patch("weather_alert_bot.app.load_settings", return_value=configured):
                with patch("weather_alert_bot.app.TelegramClient") as telegram_type:
                    with patch("weather_alert_bot.app.SQLiteSettingsStore") as settings_type:
                        with patch("weather_alert_bot.app.SQLiteRuntimeStateStore") as runtime_type:
                            with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
                                with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as geomagnetic_type:
                                    with patch("weather_alert_bot.app.SQLiteClimateNormalsCache") as climate_type:
                                        with patch("weather_alert_bot.app.OpenMeteoHistoricalWeatherClient") as historical_type:
                                            with patch("weather_alert_bot.app.signal.signal", side_effect=fake_signal):
                                                with patch("weather_alert_bot.app.run_scheduler_loop", side_effect=fake_loop) as loop:
                                                    with redirect_stdout(output):
                                                        result = main(["--run-scheduler"])

        self.assertEqual(result, 0)
        self.assertEqual(
            output.getvalue(),
            "Планировщик запущен.\nПланировщик остановлен.\n",
        )
        telegram_type.assert_called_once_with(TEST_TOKEN)
        settings_type.assert_called_once_with(configured.db_path, read_only=True)
        runtime_type.assert_called_once_with(configured.runtime_db_path)
        climate_type.assert_called_once_with(configured.climate_db_path)
        weather_type.assert_called_once_with()
        geomagnetic_type.assert_called_once_with()
        historical_type.assert_called_once_with()
        loop.assert_called_once()
        self.assertEqual(loop.call_args.kwargs["settings_store"], settings_type.return_value)
        self.assertEqual(loop.call_args.kwargs["runtime_state"], runtime_type.return_value)
        self.assertEqual(loop.call_args.kwargs["weather_client"], weather_type.return_value)
        self.assertEqual(
            loop.call_args.kwargs["geomagnetic_client"], geomagnetic_type.return_value
        )
        self.assertEqual(loop.call_args.kwargs["climate_cache"], climate_type.return_value)
        self.assertEqual(
            loop.call_args.kwargs["historical_client"], historical_type.return_value
        )
        self.assertEqual(loop.call_args.kwargs["telegram_client"], telegram_type.return_value)
        self.assertIn(signal.SIGINT, signal_handlers)
        self.assertIn(signal.SIGTERM, signal_handlers)

    def test_help_contains_mode(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--run-scheduler", output.getvalue())


if __name__ == "__main__":
    unittest.main()
