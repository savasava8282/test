import os
from dataclasses import dataclass, field


class ConfigError(RuntimeError):
    """Raised when required application configuration is missing."""


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str | None = field(repr=False)


def load_settings(*, require_telegram_token: bool = False) -> Settings:
    """Load application settings from environment variables."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or None

    if require_telegram_token and token is None:
        raise ConfigError("Переменная окружения TELEGRAM_BOT_TOKEN не задана.")

    return Settings(telegram_bot_token=token)
