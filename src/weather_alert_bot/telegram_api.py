import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class TelegramApiError(RuntimeError):
    """Raised when Telegram Bot API cannot return a safe valid response."""


@dataclass(frozen=True, slots=True)
class TelegramBotIdentity:
    id: int
    username: str
    first_name: str


@dataclass(frozen=True, slots=True)
class TelegramMessage:
    chat_id: int
    chat_type: str
    text: str | None


@dataclass(frozen=True, slots=True)
class TelegramUpdate:
    update_id: int
    message: TelegramMessage | None


class TelegramClient:
    """Small Telegram Bot API client with token-safe errors."""

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

    def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 30,
        limit: int = 100,
    ) -> list[TelegramUpdate]:
        """Return supported Telegram updates using long polling."""
        if offset is not None and (
            isinstance(offset, bool) or not isinstance(offset, int)
        ):
            raise TelegramApiError("Некорректный offset Telegram API.")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 0 <= timeout <= 50:
            raise TelegramApiError("Timeout getUpdates должен быть целым числом от 0 до 50.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise TelegramApiError("Limit getUpdates должен быть целым числом от 1 до 100.")

        parameters: dict[str, int] = {"timeout": timeout, "limit": limit}
        if offset is not None:
            parameters["offset"] = offset

        payload = self.__request(
            "getUpdates",
            parameters=parameters,
            request_timeout=max(self.__timeout, float(timeout + 5)),
        )
        result = payload.get("result")
        if not isinstance(result, list):
            raise TelegramApiError("Ответ Telegram не содержит список обновлений.")

        updates: list[TelegramUpdate] = []
        for raw_update in result:
            update = self.__parse_update(raw_update)
            if update is not None:
                updates.append(update)
        return updates

    def send_message(self, *, chat_id: int, text: str) -> None:
        """Send one text message through the official Telegram method."""
        if isinstance(chat_id, bool) or not isinstance(chat_id, int):
            raise TelegramApiError("Некорректный chat_id Telegram.")
        if not isinstance(text, str) or not text.strip():
            raise TelegramApiError("Текст сообщения Telegram не должен быть пустым.")

        self.__request(
            "sendMessage",
            parameters={"chat_id": chat_id, "text": text},
            http_method="POST",
        )

    @staticmethod
    def __parse_update(raw_update: object) -> TelegramUpdate | None:
        if not isinstance(raw_update, dict):
            return None

        update_id = raw_update.get("update_id")
        if isinstance(update_id, bool) or not isinstance(update_id, int):
            return None

        raw_message = raw_update.get("message")
        if not isinstance(raw_message, dict):
            return TelegramUpdate(update_id=update_id, message=None)

        raw_chat = raw_message.get("chat")
        if not isinstance(raw_chat, dict):
            return TelegramUpdate(update_id=update_id, message=None)

        chat_id = raw_chat.get("id")
        chat_type = raw_chat.get("type")
        if (
            isinstance(chat_id, bool)
            or not isinstance(chat_id, int)
            or not isinstance(chat_type, str)
        ):
            return TelegramUpdate(update_id=update_id, message=None)

        text = raw_message.get("text")
        if text is not None and not isinstance(text, str):
            text = None

        return TelegramUpdate(
            update_id=update_id,
            message=TelegramMessage(chat_id=chat_id, chat_type=chat_type, text=text),
        )

    def __request(
        self,
        method: str,
        *,
        parameters: dict[str, object] | None = None,
        http_method: str = "GET",
        request_timeout: float | None = None,
    ) -> dict[str, Any]:
        request_url = f"https://api.telegram.org/bot{self.__token}/{method}"
        request_data: bytes | None = None
        headers: dict[str, str] = {}

        if http_method == "POST":
            request_data = json.dumps(parameters or {}).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif parameters:
            query = urllib.parse.urlencode(parameters)
            request_url = f"{request_url}?{query}"

        request = urllib.request.Request(
            request_url,
            data=request_data,
            headers=headers,
            method=http_method,
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.__timeout if request_timeout is None else request_timeout,
            ) as response:
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
            raise TelegramApiError(f"Telegram отклонил запрос {method}.")

        return payload
