import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock

from weather_alert_bot.start_handler import WELCOME_TEXT, run_until_start
from weather_alert_bot.telegram_api import TelegramMessage, TelegramUpdate


def update(
    update_id: int,
    text: str | None,
    *,
    chat_id: int = 42,
    chat_type: str = "private",
) -> TelegramUpdate:
    return TelegramUpdate(
        update_id=update_id,
        message=TelegramMessage(chat_id=chat_id, chat_type=chat_type, text=text),
    )


class FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.responses = iter(responses)
        self.get_updates_calls: list[dict[str, object]] = []
        self.send_message = Mock()

    def get_updates(self, **kwargs: object) -> list[TelegramUpdate]:
        self.get_updates_calls.append(kwargs)
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return response


class StartHandlerTest(unittest.TestCase):
    def test_old_updates_are_discarded_without_reply_and_offset_advances(self) -> None:
        client = FakeClient(
            [
                [update(10, "/start", chat_id=900)],
                [],
                [update(10, "/start", chat_id=900), update(11, "/start")],
            ]
        )
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_start(client)

        self.assertEqual(result, 0)
        client.send_message.assert_called_once_with(chat_id=42, text=WELCOME_TEXT)
        self.assertEqual(
            client.get_updates_calls,
            [
                {"offset": None, "timeout": 0, "limit": 100},
                {"offset": 11, "timeout": 0, "limit": 100},
                {"offset": 11, "timeout": 30, "limit": 100},
            ],
        )

    def test_only_new_private_start_commands_are_answered_once(self) -> None:
        client = FakeClient(
            [
                [],
                [
                    update(20, "hello", chat_id=101),
                    update(21, "/help", chat_id=102),
                    update(22, "/start", chat_id=103, chat_type="group"),
                    TelegramUpdate(update_id=23, message=None),
                    update(24, "/start@weather_storm_alert_bot", chat_id=104),
                ],
            ]
        )
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_start(client)

        self.assertEqual(result, 0)
        client.send_message.assert_called_once_with(chat_id=104, text=WELCOME_TEXT)
        self.assertEqual(
            output.getvalue(),
            "Ожидание новой команды /start...\n"
            "Команда /start получена.\n"
            "Приветственное сообщение отправлено.\n",
        )
        self.assertNotIn("101", output.getvalue())
        self.assertNotIn("104", output.getvalue())

    def test_duplicate_update_id_is_not_processed_twice_and_offset_moves_forward(self) -> None:
        client = FakeClient(
            [
                [],
                [update(30, "not a command")],
                [update(30, "/start"), update(31, "/start")],
            ]
        )

        result = run_until_start(client)

        self.assertEqual(result, 0)
        client.send_message.assert_called_once_with(chat_id=42, text=WELCOME_TEXT)
        self.assertEqual(client.get_updates_calls[1]["offset"], None)
        self.assertEqual(client.get_updates_calls[2]["offset"], 31)

    def test_keyboard_interrupt_returns_130_without_traceback(self) -> None:
        client = FakeClient([[], KeyboardInterrupt()])
        output = io.StringIO()

        with redirect_stdout(output):
            result = run_until_start(client)

        self.assertEqual(result, 130)
        self.assertEqual(
            output.getvalue(),
            "Ожидание новой команды /start...\nОжидание /start остановлено.\n",
        )
        self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main()
