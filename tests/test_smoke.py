import io
import os
import unittest
from contextlib import redirect_stdout
from contextlib import redirect_stderr
from unittest.mock import patch

from weather_alert_bot.app import main


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

    def test_telegram_modes_are_mutually_exclusive(self) -> None:
        for arguments in (
            ["--check-telegram", "--wait-for-start"],
            ["--check-telegram", "--geocode-city", "Москва"],
            ["--wait-for-start", "--geocode-city", "Москва"],
            ["--wait-for-city", "--geocode-city", "Москва"],
            ["--wait-for-city", "--wait-for-geocoded-city"],
            ["--wait-for-geocoded-city", "--geocode-city", "Москва"],
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
        self.assertIn("--geocode-city CITY", output.getvalue())

        with self.assertRaises(SystemExit) as raised:
            main(["--wait-for-start", "--wait-for-city"])

        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
