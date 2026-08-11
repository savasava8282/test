import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from weather_alert_bot.app import main
from weather_alert_bot.storage import StorageError


TEST_TOKEN = "123456789:TEST_TOKEN_NOT_REAL"


class OnboardingCompleteCliTest(unittest.TestCase):
    def test_mode_requires_token_safely(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(["--wait-for-onboarding-complete"])

        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Ошибка завершения первоначальной настройки", stderr.getvalue())
        self.assertNotIn(TEST_TOKEN, stderr.getvalue())

    def test_mode_wires_telegram_client_storage_and_handler(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TEST_TOKEN}, clear=True):
            with patch("weather_alert_bot.app.TelegramClient") as client_type:
                with patch("weather_alert_bot.app.SQLiteSettingsStore") as storage_type:
                    with patch(
                        "weather_alert_bot.app.run_until_onboarding_complete",
                        return_value=0,
                    ) as handler:
                        result = main(["--wait-for-onboarding-complete"])

        self.assertEqual(result, 0)
        client_type.assert_called_once_with(TEST_TOKEN)
        storage_type.assert_called_once()
        handler.assert_called_once_with(
            client_type.return_value,
            storage_type.return_value,
        )

    def test_storage_error_is_reported_without_internal_details(self) -> None:
        output = io.StringIO()
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TEST_TOKEN}, clear=True):
            with patch(
                "weather_alert_bot.app.run_until_onboarding_complete",
                side_effect=StorageError("private sqlite details"),
            ):
                with redirect_stdout(output), redirect_stderr(output):
                    result = main(["--wait-for-onboarding-complete"])

        self.assertEqual(result, 1)
        self.assertIn("Ошибка завершения первоначальной настройки", output.getvalue())
        self.assertNotIn("private sqlite details", output.getvalue())

    def test_mode_is_mutually_exclusive_with_all_existing_modes(self) -> None:
        existing_modes = (
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
            "--geocode-city",
        )
        for argument in existing_modes:
            arguments = ["--wait-for-onboarding-complete", argument]
            if argument == "--geocode-city":
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
        self.assertIn("--wait-for-onboarding-complete", output.getvalue())


if __name__ == "__main__":
    unittest.main()
