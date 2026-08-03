import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class TelegramApiError(RuntimeError):
    """Raised when Telegram Bot API cannot return a valid bot identity."""


@dataclass(frozen=True, slots=True)
class TelegramBotIdentity:
    id: int
    username: str
    first_name: str


class TelegramClient:
    """Minimal client for safe, read-only Telegram Bot API checks."""

    __slots__ = ("__token", "__timeout")

    def __init__(self, token: str, *, timeout: float = 10.0) -> None:
        if not isinstance(token, str) or not token.strip():
            raise TelegramApiError("Токен Telegram не задан.")

        try:
            normalized_timeout = float(timeout)
        except (TypeError, ValueError) as exc:
            raise TelegramApiError("Некорректный timeout Telegram API.") from exc

        if normalized_timeout <= 0:
            raise TelegramApiError("Timeout Telegram API должен быть положительным.")

        self.__token = token.strip()
        self.__timeout = normalized_timeout

    @property
    def timeout(self) -> float:
        """Return the configured request timeout in seconds."""
        return self.__timeout

    def __repr__(self) -> str:
        return f"TelegramClient(timeout={self.__timeout!r})"

    def get_me(self) -> TelegramBotIdentity:
        """Return the identity of the bot associated with the configured token."""
        payload = self.__request("getMe")
        result = payload.get("result")

        if not isinstance(result, dict):
            raise TelegramApiError("Ответ Telegram не содержит данных о боте.")

        bot_id = result.get("id")
        username = result.get("username")
        first_name = result.get("first_name")

        if (
            isinstance(bot_id, bool)
            or not isinstance(bot_id, int)
            or not isinstance(username, str)
            or not isinstance(first_name, str)
        ):
            raise TelegramApiError("Ответ Telegram не содержит обязательные поля бота.")

        return TelegramBotIdentity(
            id=bot_id,
            username=username,
            first_name=first_name,
        )

    def __request(self, method: str) -> dict[str, Any]:
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{self.__token}/{method}",
            method="GET",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.__timeout) as response:
                status = getattr(response, "status", None)
                if isinstance(status, bool) or not isinstance(status, int):
                    status = response.getcode()
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            raise TelegramApiError(f"Telegram вернул HTTP-ошибку ({exc.code}).") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TelegramApiError("Не удалось подключиться к Telegram.") from exc

        if not isinstance(status, int) or status < 200 or status >= 300:
            raise TelegramApiError(f"Telegram вернул HTTP-статус {status}.")

        try:
            payload = json.loads(response_body)
        except (TypeError, ValueError) as exc:
            raise TelegramApiError("Telegram вернул некорректный JSON.") from exc

        if not isinstance(payload, dict):
            raise TelegramApiError("Ответ Telegram имеет некорректную структуру.")

        if payload.get("ok") is not True:
            raise TelegramApiError("Telegram отклонил запрос getMe.")

        return payload
