import os
from pathlib import Path
import unittest
from unittest.mock import patch

from weather_alert_bot.config import DEFAULT_DB_PATH, ConfigError, Settings, load_settings


TEST_TOKEN = "123456789:TEST_TOKEN_NOT_REAL"


class LoadSettingsTest(unittest.TestCase):
    def test_missing_optional_token_returns_none(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = load_settings(require_telegram_token=False)

        self.assertIsNone(settings.telegram_bot_token)
        self.assertEqual(settings.db_path, DEFAULT_DB_PATH)

    def test_database_path_uses_environment_variable(self) -> None:
        with patch.dict(
            os.environ,
            {"WEATHER_ALERT_BOT_DB_PATH": "~/weather-alert-test/settings.sqlite3"},
            clear=True,
        ):
            settings = load_settings()

        self.assertEqual(
            settings.db_path,
            Path.home() / "weather-alert-test" / "settings.sqlite3",
        )

    def test_empty_and_whitespace_tokens_return_none(self) -> None:
        for value in ("", "   "):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": value}, clear=True):
                    settings = load_settings()

                self.assertIsNone(settings.telegram_bot_token)

    def test_token_is_read_and_trimmed(self) -> None:
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": f"  {TEST_TOKEN}  "},
            clear=True,
        ):
            settings = load_settings()

        self.assertEqual(settings.telegram_bot_token, TEST_TOKEN)

    def test_missing_required_token_raises_exact_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                ConfigError,
                "^Переменная окружения TELEGRAM_BOT_TOKEN не задана\\.$",
            ):
                load_settings(require_telegram_token=True)

    def test_settings_repr_hides_token(self) -> None:
        settings_repr = repr(Settings(telegram_bot_token=TEST_TOKEN, db_path=DEFAULT_DB_PATH))

        self.assertNotIn(TEST_TOKEN, settings_repr)

    def test_loader_does_not_change_environment(self) -> None:
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": f"  {TEST_TOKEN}  "},
            clear=True,
        ):
            environment_before = dict(os.environ)
            load_settings()
            self.assertEqual(dict(os.environ), environment_before)
