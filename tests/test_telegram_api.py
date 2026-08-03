import io
import json
import os
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from weather_alert_bot.app import main
from weather_alert_bot.telegram_api import (
    TelegramApiError,
    TelegramBotIdentity,
    TelegramClient,
)


TEST_TOKEN = "123456789:TEST_TOKEN_NOT_REAL"


class MockResponse:
    def __init__(self, payload: object, *, status: int = 200) -> None:
        self.status = status
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "MockResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status


class TelegramClientTest(unittest.TestCase):
    def test_get_me_returns_identity_and_uses_configured_timeout(self) -> None:
        response = MockResponse(
            {
                "ok": True,
                "result": {
                    "id": 8980247554,
                    "is_bot": True,
                    "first_name": "Погода и магнитные бури",
                    "username": "weather_storm_alert_bot",
                },
            }
        )

        with patch(
            "weather_alert_bot.telegram_api.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            identity = TelegramClient(TEST_TOKEN, timeout=3.5).get_me()

        self.assertEqual(
            identity,
            TelegramBotIdentity(
                id=8980247554,
                username="weather_storm_alert_bot",
                first_name="Погода и магнитные бури",
            ),
        )
        urlopen.assert_called_once()
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 3.5)
        self.assertIn("getMe", urlopen.call_args.args[0].full_url)

    def test_negative_telegram_response_is_safe_error(self) -> None:
        response = MockResponse({"ok": False, "error_code": 401, "description": "Unauthorized"})

        with patch(
            "weather_alert_bot.telegram_api.urllib.request.urlopen",
            return_value=response,
        ):
            with self.assertRaises(TelegramApiError) as raised:
                TelegramClient(TEST_TOKEN).get_me()

        self.assertIn("отклонил", str(raised.exception))
        self.assertNotIn(TEST_TOKEN, str(raised.exception))

    def test_network_error_is_converted(self) -> None:
        with patch(
            "weather_alert_bot.telegram_api.urllib.request.urlopen",
            side_effect=urllib.error.URLError("network unavailable"),
        ):
            with self.assertRaises(TelegramApiError) as raised:
                TelegramClient(TEST_TOKEN).get_me()

        self.assertIn("подключиться", str(raised.exception))
        self.assertNotIn(TEST_TOKEN, str(raised.exception))

    def test_invalid_json_is_converted(self) -> None:
        response = MockResponse({})
        response._body = b"not-json"

        with patch(
            "weather_alert_bot.telegram_api.urllib.request.urlopen",
            return_value=response,
        ):
            with self.assertRaises(TelegramApiError) as raised:
                TelegramClient(TEST_TOKEN).get_me()

        self.assertIn("JSON", str(raised.exception))
        self.assertNotIn(TEST_TOKEN, str(raised.exception))

    def test_missing_required_fields_are_rejected(self) -> None:
        for result in ({"id": 1, "username": "bot"}, {"id": 1, "first_name": "Bot"}):
            with self.subTest(result=result):
                response = MockResponse({"ok": True, "result": result})
                with patch(
                    "weather_alert_bot.telegram_api.urllib.request.urlopen",
                    return_value=response,
                ):
                    with self.assertRaises(TelegramApiError):
                        TelegramClient(TEST_TOKEN).get_me()

    def test_http_error_is_checked_without_exposing_token(self) -> None:
        response = MockResponse({"ok": True}, status=503)

        with patch(
            "weather_alert_bot.telegram_api.urllib.request.urlopen",
            return_value=response,
        ):
            with self.assertRaises(TelegramApiError) as raised:
                TelegramClient(TEST_TOKEN).get_me()

        self.assertIn("503", str(raised.exception))
        self.assertNotIn(TEST_TOKEN, str(raised.exception))

    def test_repr_does_not_expose_token(self) -> None:
        client = TelegramClient(TEST_TOKEN)

        self.assertNotIn(TEST_TOKEN, repr(client))
        self.assertNotIn(TEST_TOKEN, str(client))


class TelegramCheckCommandTest(unittest.TestCase):
    def test_check_without_token_fails_safely(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                return_code = main(["--check-telegram"])

        self.assertEqual(return_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Ошибка проверки Telegram", stderr.getvalue())
        self.assertNotIn(TEST_TOKEN, stderr.getvalue())

    def test_check_prints_only_safe_bot_identity(self) -> None:
        response = MockResponse(
            {
                "ok": True,
                "result": {
                    "id": 8980247554,
                    "first_name": "Погода и магнитные бури",
                    "username": "weather_storm_alert_bot",
                },
            }
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TEST_TOKEN}, clear=True):
            with patch(
                "weather_alert_bot.telegram_api.urllib.request.urlopen",
                return_value=response,
            ):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    return_code = main(["--check-telegram"])

        self.assertEqual(return_code, 0)
        self.assertEqual(
            stdout.getvalue(),
            "Токен принят Telegram: да\n"
            "ID бота: 8980247554\n"
            "Username: @weather_storm_alert_bot\n"
            "Имя: Погода и магнитные бури\n",
        )
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn(TEST_TOKEN, stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
