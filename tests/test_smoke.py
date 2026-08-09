import io
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr
from contextlib import redirect_stdout
from unittest.mock import patch

from weather_alert_bot.app import main
from weather_alert_bot.storage import StorageError
from weather_alert_bot.telegram_api import TelegramApiError


class SmokeTest(unittest.TestCase):
    def test_main(self) -> None:
        output = io.StringIO()

        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(output):
                return_code = main([])

        self.assertEqual(return_code, 0)
        self.assertEqual(output.getvalue(), "Каркас погодного бота готов.\n")

    def test_wait_for_start_without_token_fails_safely(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                return_code = main(["--wait-for-start"])

        self.assertEqual(return_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Ошибка ожидания /start", stderr.getvalue())
        self.assertNotIn("123456789:TEST_TOKEN_NOT_REAL", stderr.getvalue())

    def test_wait_for_start_uses_mock_client(self) -> None:
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "123456789:TEST_TOKEN_NOT_REAL"},
            clear=True,
        ):
            with patch("weather_alert_bot.app.TelegramClient") as client_type:
                with patch("weather_alert_bot.app.run_until_start", return_value=0) as handler:
                    return_code = main(["--wait-for-start"])

        self.assertEqual(return_code, 0)
        client_type.assert_called_once_with("123456789:TEST_TOKEN_NOT_REAL")
        handler.assert_called_once_with(client_type.return_value)

    def test_wait_for_city_without_token_fails_safely(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                return_code = main(["--wait-for-city"])

        self.assertEqual(return_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Ошибка ожидания города", stderr.getvalue())
        self.assertNotIn("123456789:TEST_TOKEN_NOT_REAL", stderr.getvalue())

    def test_wait_for_city_uses_mock_client(self) -> None:
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "123456789:TEST_TOKEN_NOT_REAL"},
            clear=True,
        ):
            with patch("weather_alert_bot.app.TelegramClient") as client_type:
                with patch("weather_alert_bot.app.run_until_city", return_value=0) as handler:
                    return_code = main(["--wait-for-city"])

        self.assertEqual(return_code, 0)
        client_type.assert_called_once_with("123456789:TEST_TOKEN_NOT_REAL")
        handler.assert_called_once_with(client_type.return_value)

    def test_wait_for_geocoded_city_without_token_fails_safely(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                return_code = main(["--wait-for-geocoded-city"])

        self.assertEqual(return_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Ошибка ожидания города с геокодированием", stderr.getvalue())
        self.assertNotIn("123456789:TEST_TOKEN_NOT_REAL", stderr.getvalue())

    def test_wait_for_geocoded_city_creates_both_clients_and_uses_handler(self) -> None:
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "123456789:TEST_TOKEN_NOT_REAL"},
            clear=True,
        ):
            with patch("weather_alert_bot.app.TelegramClient") as client_type:
                with patch("weather_alert_bot.app.OpenMeteoGeocodingClient") as geocoder_type:
                    with patch(
                        "weather_alert_bot.app.run_until_geocoded_city",
                        return_value=0,
                    ) as handler:
                        return_code = main(["--wait-for-geocoded-city"])

        self.assertEqual(return_code, 0)
        client_type.assert_called_once_with("123456789:TEST_TOKEN_NOT_REAL")
        geocoder_type.assert_called_once_with()
        handler.assert_called_once_with(client_type.return_value, geocoder_type.return_value)

    def test_wait_for_confirmed_city_without_token_fails_safely(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                return_code = main(["--wait-for-confirmed-city"])

        self.assertEqual(return_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Ошибка ожидания подтверждённого города", stderr.getvalue())
        self.assertNotIn("123456789:TEST_TOKEN_NOT_REAL", stderr.getvalue())

    def test_wait_for_confirmed_city_creates_both_clients_and_uses_handler(self) -> None:
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "123456789:TEST_TOKEN_NOT_REAL"},
            clear=True,
        ):
            with patch("weather_alert_bot.app.TelegramClient") as client_type:
                with patch("weather_alert_bot.app.OpenMeteoGeocodingClient") as geocoder_type:
                    with patch("weather_alert_bot.app.SQLiteSettingsStore") as storage_type:
                        with patch(
                            "weather_alert_bot.app.run_until_confirmed_city",
                            return_value=0,
                        ) as handler:
                            return_code = main(["--wait-for-confirmed-city"])

        self.assertEqual(return_code, 0)
        client_type.assert_called_once_with("123456789:TEST_TOKEN_NOT_REAL")
        geocoder_type.assert_called_once_with()
        storage_type.assert_called_once()
        handler.assert_called_once_with(
            client_type.return_value,
            geocoder_type.return_value,
            storage_type.return_value,
        )

    def test_wait_for_confirmed_city_handles_telegram_error_without_traceback(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "123456789:TEST_TOKEN_NOT_REAL"},
            clear=True,
        ):
            with patch(
                "weather_alert_bot.app.run_until_confirmed_city",
                side_effect=TelegramApiError("https://internal.example chat 42 {\"x\":1}"),
            ):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    return_code = main(["--wait-for-confirmed-city"])

        self.assertEqual(return_code, 1)
        terminal = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn("Traceback", terminal)
        self.assertNotIn("https://", terminal)
        self.assertNotIn("42", terminal)
        self.assertNotIn("{", terminal)

    def test_wait_for_daily_time_without_token_fails_safely(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                return_code = main(["--wait-for-daily-time"])

        self.assertEqual(return_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Ошибка настройки времени ежедневной отправки", stderr.getvalue())
        self.assertNotIn("123456789:TEST_TOKEN_NOT_REAL", stderr.getvalue())

    def test_wait_for_daily_time_creates_client_and_storage_and_uses_handler(self) -> None:
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "123456789:TEST_TOKEN_NOT_REAL"},
            clear=True,
        ):
            with patch("weather_alert_bot.app.TelegramClient") as client_type:
                with patch("weather_alert_bot.app.SQLiteSettingsStore") as storage_type:
                    with patch(
                        "weather_alert_bot.app.run_until_daily_time",
                        return_value=0,
                    ) as handler:
                        return_code = main(["--wait-for-daily-time"])

        self.assertEqual(return_code, 0)
        client_type.assert_called_once_with("123456789:TEST_TOKEN_NOT_REAL")
        storage_type.assert_called_once()
        handler.assert_called_once_with(client_type.return_value, storage_type.return_value)

    def test_wait_for_daily_time_handles_storage_error_without_traceback(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch.dict(
                os.environ,
                {
                    "TELEGRAM_BOT_TOKEN": "123456789:TEST_TOKEN_NOT_REAL",
                    "WEATHER_ALERT_BOT_DB_PATH": str(Path(temporary_directory) / "settings.sqlite3"),
                },
                clear=True,
            ):
                with patch(
                    "weather_alert_bot.app.run_until_daily_time",
                    side_effect=StorageError("internal details"),
                ):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        return_code = main(["--wait-for-daily-time"])

        self.assertEqual(return_code, 1)
        self.assertNotIn("Traceback", stdout.getvalue() + stderr.getvalue())
        self.assertNotIn("internal details", stdout.getvalue() + stderr.getvalue())

    def test_wait_for_daily_days_without_token_fails_safely(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                return_code = main(["--wait-for-daily-days"])

        self.assertEqual(return_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Ошибка настройки дней ежедневной отправки", stderr.getvalue())
        self.assertNotIn("123456789:TEST_TOKEN_NOT_REAL", stderr.getvalue())

    def test_wait_for_daily_days_creates_client_and_storage_and_uses_handler(self) -> None:
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "123456789:TEST_TOKEN_NOT_REAL"},
            clear=True,
        ):
            with patch("weather_alert_bot.app.TelegramClient") as client_type:
                with patch("weather_alert_bot.app.SQLiteSettingsStore") as storage_type:
                    with patch(
                        "weather_alert_bot.app.run_until_daily_days",
                        return_value=0,
                    ) as handler:
                        return_code = main(["--wait-for-daily-days"])

        self.assertEqual(return_code, 0)
        client_type.assert_called_once_with("123456789:TEST_TOKEN_NOT_REAL")
        storage_type.assert_called_once()
        handler.assert_called_once_with(client_type.return_value, storage_type.return_value)

    def test_wait_for_urgent_warnings_without_token_fails_safely(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                return_code = main(["--wait-for-urgent-warnings"])

        self.assertEqual(return_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Ошибка настройки срочных предупреждений", stderr.getvalue())
        self.assertNotIn("123456789:TEST_TOKEN_NOT_REAL", stderr.getvalue())

    def test_wait_for_urgent_warnings_creates_client_and_storage_and_uses_handler(self) -> None:
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "123456789:TEST_TOKEN_NOT_REAL"},
            clear=True,
        ):
            with patch("weather_alert_bot.app.TelegramClient") as client_type:
                with patch("weather_alert_bot.app.SQLiteSettingsStore") as storage_type:
                    with patch(
                        "weather_alert_bot.app.run_until_urgent_warnings",
                        return_value=0,
                    ) as handler:
                        return_code = main(["--wait-for-urgent-warnings"])

        self.assertEqual(return_code, 0)
        client_type.assert_called_once_with("123456789:TEST_TOKEN_NOT_REAL")
        storage_type.assert_called_once()
        handler.assert_called_once_with(client_type.return_value, storage_type.return_value)

    def test_wait_for_urgent_warnings_handles_storage_error_without_traceback(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "123456789:TEST_TOKEN_NOT_REAL"},
            clear=True,
        ):
            with patch(
                "weather_alert_bot.app.run_until_urgent_warnings",
                side_effect=StorageError("internal details"),
            ):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    return_code = main(["--wait-for-urgent-warnings"])

        self.assertEqual(return_code, 1)
        terminal = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn("Traceback", terminal)
        self.assertNotIn("internal details", terminal)

    def test_wait_for_warning_categories_without_token_fails_safely(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                return_code = main(["--wait-for-warning-categories"])

        self.assertEqual(return_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Ошибка настройки категорий предупреждений", stderr.getvalue())
        self.assertNotIn("123456789:TEST_TOKEN_NOT_REAL", stderr.getvalue())

    def test_wait_for_warning_categories_creates_client_and_storage_and_uses_handler(self) -> None:
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "123456789:TEST_TOKEN_NOT_REAL"},
            clear=True,
        ):
            with patch("weather_alert_bot.app.TelegramClient") as client_type:
                with patch("weather_alert_bot.app.SQLiteSettingsStore") as storage_type:
                    with patch(
                        "weather_alert_bot.app.run_until_warning_categories",
                        return_value=0,
                    ) as handler:
                        return_code = main(["--wait-for-warning-categories"])

        self.assertEqual(return_code, 0)
        client_type.assert_called_once_with("123456789:TEST_TOKEN_NOT_REAL")
        storage_type.assert_called_once()
        handler.assert_called_once_with(client_type.return_value, storage_type.return_value)

    def test_wait_for_warning_categories_handles_storage_error_without_traceback(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "123456789:TEST_TOKEN_NOT_REAL"},
            clear=True,
        ):
            with patch(
                "weather_alert_bot.app.run_until_warning_categories",
                side_effect=StorageError("internal details"),
            ):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    return_code = main(["--wait-for-warning-categories"])

        self.assertEqual(return_code, 1)
        terminal = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn("Traceback", terminal)
        self.assertNotIn("internal details", terminal)

    def test_warning_categories_are_mutually_exclusive_with_existing_one_shot_modes(self) -> None:
        for argument in (
            "--check-telegram",
            "--wait-for-start",
            "--wait-for-city",
            "--wait-for-geocoded-city",
            "--wait-for-confirmed-city",
            "--wait-for-daily-time",
            "--wait-for-daily-days",
            "--wait-for-urgent-warnings",
            "--geocode-city",
        ):
            arguments = ["--wait-for-warning-categories", argument]
            if argument == "--geocode-city":
                arguments.append("Москва")
            with self.subTest(arguments=arguments):
                with self.assertRaises(SystemExit) as raised:
                    main(arguments)
                self.assertEqual(raised.exception.code, 2)

    def test_one_shot_modes_are_mutually_exclusive_with_urgent_warnings(self) -> None:
        with self.assertRaises(SystemExit) as context:
            main(["--wait-for-urgent-warnings", "--wait-for-daily-days"])

        self.assertEqual(context.exception.code, 2)

    def test_wait_for_daily_days_handles_storage_error_without_traceback(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch.dict(
                os.environ,
                {
                    "TELEGRAM_BOT_TOKEN": "123456789:TEST_TOKEN_NOT_REAL",
                    "WEATHER_ALERT_BOT_DB_PATH": str(Path(temporary_directory) / "settings.sqlite3"),
                },
                clear=True,
            ):
                with patch(
                    "weather_alert_bot.app.run_until_daily_days",
                    side_effect=StorageError("internal details"),
                ):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        return_code = main(["--wait-for-daily-days"])

        self.assertEqual(return_code, 1)
        self.assertNotIn("Traceback", stdout.getvalue() + stderr.getvalue())
        self.assertNotIn("internal details", stdout.getvalue() + stderr.getvalue())

    def test_wait_for_daily_sending_without_token_fails_safely(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                return_code = main(["--wait-for-daily-sending"])

        self.assertEqual(return_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Ошибка настройки ежедневной рассылки", stderr.getvalue())
        self.assertNotIn("123456789:TEST_TOKEN_NOT_REAL", stderr.getvalue())

    def test_wait_for_daily_sending_wires_client_storage_and_handler(self) -> None:
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "123456789:TEST_TOKEN_NOT_REAL"},
            clear=True,
        ):
            with patch("weather_alert_bot.app.TelegramClient") as client_type:
                with patch("weather_alert_bot.app.SQLiteSettingsStore") as storage_type:
                    with patch(
                        "weather_alert_bot.app.run_until_daily_sending",
                        return_value=0,
                    ) as handler:
                        return_code = main(["--wait-for-daily-sending"])

        self.assertEqual(return_code, 0)
        client_type.assert_called_once_with("123456789:TEST_TOKEN_NOT_REAL")
        storage_type.assert_called_once()
        handler.assert_called_once_with(client_type.return_value, storage_type.return_value)

    def test_daily_sending_is_mutually_exclusive_with_all_one_shot_modes(self) -> None:
        for argument in (
            "--check-telegram",
            "--wait-for-start",
            "--wait-for-city",
            "--wait-for-geocoded-city",
            "--wait-for-confirmed-city",
            "--wait-for-daily-time",
            "--wait-for-daily-days",
            "--wait-for-urgent-warnings",
            "--wait-for-warning-categories",
            "--geocode-city",
        ):
            arguments = ["--wait-for-daily-sending", argument]
            if argument == "--geocode-city":
                arguments.append("Москва")
            with self.subTest(arguments=arguments):
                with self.assertRaises(SystemExit) as raised:
                    main(arguments)
                self.assertEqual(raised.exception.code, 2)

    def test_help_contains_wait_for_daily_sending(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                main(["--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--wait-for-daily-sending", output.getvalue())

    def test_wait_for_confirmed_city_is_mutually_exclusive_with_existing_modes(self) -> None:
        for arguments in (
            ["--check-telegram", "--wait-for-confirmed-city"],
            ["--wait-for-start", "--wait-for-confirmed-city"],
            ["--wait-for-city", "--wait-for-confirmed-city"],
            ["--wait-for-geocoded-city", "--wait-for-confirmed-city"],
            ["--wait-for-confirmed-city", "--geocode-city", "Москва"],
            ["--wait-for-confirmed-city", "--wait-for-daily-time"],
            ["--wait-for-confirmed-city", "--wait-for-daily-days"],
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(SystemExit) as raised:
                    main(arguments)
                self.assertEqual(raised.exception.code, 2)

    def test_telegram_modes_are_mutually_exclusive(self) -> None:
        for arguments in (
            ["--check-telegram", "--wait-for-start"],
            ["--check-telegram", "--geocode-city", "Москва"],
            ["--wait-for-start", "--geocode-city", "Москва"],
            ["--wait-for-city", "--geocode-city", "Москва"],
            ["--wait-for-city", "--wait-for-geocoded-city"],
            ["--wait-for-geocoded-city", "--geocode-city", "Москва"],
            ["--wait-for-confirmed-city", "--geocode-city", "Москва"],
            ["--wait-for-daily-time", "--geocode-city", "Москва"],
            ["--wait-for-daily-days", "--geocode-city", "Москва"],
            ["--wait-for-daily-time", "--wait-for-daily-days"],
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(SystemExit) as raised:
                    main(arguments)
                self.assertEqual(raised.exception.code, 2)

    def test_help_contains_wait_for_city(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                main(["--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--wait-for-city", output.getvalue())
        self.assertIn("--wait-for-geocoded-city", output.getvalue())
        self.assertIn("--wait-for-confirmed-city", output.getvalue())
        self.assertIn("--wait-for-daily-time", output.getvalue())
        self.assertIn("--wait-for-daily-days", output.getvalue())
        self.assertIn("--wait-for-warning-categories", output.getvalue())
        self.assertIn("--geocode-city CITY", output.getvalue())

        with self.assertRaises(SystemExit) as raised:
            main(["--wait-for-start", "--wait-for-city"])

        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
