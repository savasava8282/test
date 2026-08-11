import io
import os
from datetime import datetime
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from weather_alert_bot.app import main
from weather_alert_bot.geomagnetic_forecast import (
    GeomagneticForecast,
    GeomagneticForecastError,
    GeomagneticForecastInterval,
)


def forecast() -> GeomagneticForecast:
    return GeomagneticForecast(
        intervals=(
            GeomagneticForecastInterval(
                timestamp=datetime(2026, 8, 11, 0),
                kp=2.33,
                status="observed",
            ),
            GeomagneticForecastInterval(
                timestamp=datetime(2026, 8, 11, 3),
                kp=4.0,
                status="predicted",
            ),
            GeomagneticForecastInterval(
                timestamp=datetime(2026, 8, 11, 6),
                kp=5.67,
                status="predicted",
            ),
        )
    )


class GeomagneticForecastCliTest(unittest.TestCase):
    def run_cli(self) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(["--fetch-kp-forecast"])
        return result, stdout.getvalue(), stderr.getvalue()

    def test_success_prints_compact_processed_output_without_config_or_sqlite(self) -> None:
        with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as client_type:
            client_type.return_value.fetch.return_value = forecast()
            with patch("weather_alert_bot.app.SQLiteSettingsStore") as storage_type:
                result, stdout, stderr = self.run_cli()

        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        client_type.assert_called_once_with()
        client_type.return_value.fetch.assert_called_once_with()
        storage_type.assert_not_called()
        self.assertIn("Источник: NOAA SWPC", stdout)
        self.assertIn("Количество интервалов: 3", stdout)
        self.assertIn("Первый timestamp: 2026-08-11 00:00:00", stdout)
        self.assertIn("Последний timestamp: 2026-08-11 06:00:00", stdout)
        self.assertIn("Первый Kp: 2.33", stdout)
        self.assertIn("Максимальный Kp: 5.67", stdout)
        self.assertIn("Статусы: observed=1, predicted=2", stdout)
        self.assertNotIn("{", stdout)
        self.assertNotIn("[", stdout)

    def test_no_telegram_token_is_required(self) -> None:
        with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as client_type:
            client_type.return_value.fetch.return_value = forecast()
            with patch("weather_alert_bot.app.TelegramClient") as telegram_type:
                result, _, stderr = self.run_cli()

        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        telegram_type.assert_not_called()

    def test_geomagnetic_error_is_safe(self) -> None:
        with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as client_type:
            client_type.return_value.fetch.side_effect = GeomagneticForecastError(
                "private NOAA response body"
            )
            result, stdout, stderr = self.run_cli()

        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Ошибка получения прогноза Kp NOAA SWPC.", stderr)
        self.assertNotIn("private NOAA response body", stderr)

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
            "--fetch-weather-forecast",
            "--geocode-city",
        )
        for action in existing_actions:
            arguments = ["--fetch-kp-forecast", action]
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
        self.assertIn("--fetch-kp-forecast", output.getvalue())


if __name__ == "__main__":
    unittest.main()
