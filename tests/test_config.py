import os
import unittest
from unittest.mock import patch

from weather_alert_bot.config import ConfigError, Settings, load_settings


class LoadSettingsTest(unittest.TestCase):
    def test_missing_optional_token_returns_none(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = load_settings(require_telegram_token=False)

        self.assertIsNone(settings.telegram_bot_token)

    def test_empty_and_whitespace_tokens_return_none(self) -> None:
        for value in ("", "   "):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": value}, clear=True):
                    settings = load_settings()

                self.assertIsNone(settings.telegram_bot_token)

    def test_token_is_read_and_trimmed(self) -> None:
        test_token = "test-token-not-real-12345"

        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": f"  {test_token}  "},
            clear=True,
        ):
            settings = load_settings()

        self.assertEqual(settings.telegram_bot_token, test_token)

    def test_missing_required_token_raises_exact_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                ConfigError,
                "^Переменная окружения TELEGRAM_BOT_TOKEN не задана\\.$",
            ):
                load_settings(require_telegram_token=True)

    def test_settings_repr_hides_token(self) -> None:
        test_token = "test-token-not-real-12345"

        settings_repr = repr(Settings(telegram_bot_token=test_token))

        self.assertNotIn(test_token, settings_repr)

    def test_loader_does_not_change_environment(self) -> None:
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "  test-token-not-real-12345  "},
            clear=True,
        ):
            environment_before = dict(os.environ)
            load_settings()
            self.assertEqual(dict(os.environ), environment_before)
