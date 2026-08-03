import io
import json
import os
import unittest
import urllib.error
import urllib.parse
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from weather_alert_bot.app import main
from weather_alert_bot.telegram_api import (
    TelegramApiError,
    TelegramBotIdentity,
    TelegramClient,
    TelegramMessage,
    TelegramUpdate,
)


TEST_TOKEN = "123456789:TEST_TOKEN_NOT_REAL"


class MockResponse:
    def __init__(self, payload: object, *, status: int = 200, raw: bool = False) -> None:
        self.status = status
        self._body = payload if raw else json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "MockResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status


class TelegramClientTest(unittest.TestCase):
    def test_get_updates_parses_text_and_ignores_unsupported_update_types(self) -> None:
        response = MockResponse(
            {
                "ok": True,
                "result": [
                    {
                        "update_id": 101,
                        "message": {
                            "chat": {"id": 42, "type": "private"},
                            "text": "/start",
                        },
                    },
                    {"update_id": 102, "callback_query": {"id": "ignored"}},
                    {"update_id": "invalid"},
                ],
            }
        )

        with patch(
            "weather_alert_bot.telegram_api.urllib.request.urlopen",
            return_value=response,
        ):
            updates = TelegramClient(TEST_TOKEN).get_updates()

        self.assertEqual(
            updates,
            [
                TelegramUpdate(
                    update_id=101,
                    message=TelegramMessage(chat_id=42, chat_type="private", text="/start"),
                ),
                TelegramUpdate(update_id=102, message=None),
            ],
        )

    def test_get_updates_passes_offset_timeout_and_limit(self) -> None:
        response = MockResponse({"ok": True, "result": []})

        with patch(
            "weather_alert_bot.telegram_api.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            updates = TelegramClient(TEST_TOKEN).get_updates(
                offset=77,
                timeout=12,
                limit=9,
            )

        self.assertEqual(updates, [])
        request = urlopen.call_args.args[0]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        self.assertEqual(query, {"offset": ["77"], "timeout": ["12"], "limit": ["9"]})
        self.assertEqual(request.method, "GET")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 17.0)

    def test_get_updates_validates_timeout_and_limit(self) -> None:
        client = TelegramClient(TEST_TOKEN)

        for kwargs in ({"timeout": -1}, {"timeout": 51}, {"limit": 0}, {"limit": 101}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(TelegramApiError):
                    client.get_updates(**kwargs)

    def test_get_updates_without_message_is_safe(self) -> None:
        response = MockResponse({"ok": True, "result": [{"update_id": 103}]})

        with patch(
            "weather_alert_bot.telegram_api.urllib.request.urlopen",
            return_value=response,
        ):
            self.assertEqual(
                TelegramClient(TEST_TOKEN).get_updates(),
                [TelegramUpdate(update_id=103, message=None)],
            )

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
        response = MockResponse(b"not-json", raw=True)

        with patch(
            "weather_alert_bot.telegram_api.urllib.request.urlopen",
            return_value=response,
        ):
            with self.assertRaises(TelegramApiError) as raised:
                TelegramClient(TEST_TOKEN).get_me()

        self.assertIn("JSON", str(raised.exception))
        self.assertNotIn(TEST_TOKEN, str(raised.exception))

    def test_send_message_uses_post_with_chat_id_and_text(self) -> None:
        response = MockResponse({"ok": True, "result": {"message_id": 12}})

        with patch(
            "weather_alert_bot.telegram_api.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            result = TelegramClient(TEST_TOKEN).send_message(
                chat_id=42,
                text="Привет",
            )

        self.assertIsNone(result)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"chat_id": 42, "text": "Привет"},
        )
        self.assertEqual(request.headers["Content-type"], "application/json")

    def test_send_message_rejects_empty_text_without_request(self) -> None:
        with patch(
            "weather_alert_bot.telegram_api.urllib.request.urlopen",
        ) as urlopen:
            with self.assertRaises(TelegramApiError):
                TelegramClient(TEST_TOKEN).send_message(chat_id=42, text="  ")

        urlopen.assert_not_called()

    def test_send_message_negative_response_is_safe_error(self) -> None:
        response = MockResponse({"ok": False, "error_code": 400, "description": "bad"})

        with patch(
            "weather_alert_bot.telegram_api.urllib.request.urlopen",
            return_value=response,
        ):
            with self.assertRaises(TelegramApiError) as raised:
                TelegramClient(TEST_TOKEN).send_message(chat_id=42, text="Привет")

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
