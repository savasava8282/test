import os
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_DB_PATH = Path("~/.local/share/weather-alert-bot/settings.sqlite3").expanduser()
DEFAULT_CLIMATE_DB_PATH = Path(
    "~/.local/share/weather-alert-bot/climate_normals.sqlite3"
).expanduser()


class ConfigError(RuntimeError):
    """Raised when required application configuration is missing."""


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str | None = field(repr=False)
    db_path: Path
    climate_db_path: Path = DEFAULT_CLIMATE_DB_PATH


def load_settings(*, require_telegram_token: bool = False) -> Settings:
    """Load application settings from environment variables."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or None
    configured_db_path = os.environ.get("WEATHER_ALERT_BOT_DB_PATH", "").strip()
    db_path = Path(configured_db_path).expanduser() if configured_db_path else DEFAULT_DB_PATH
    configured_climate_db_path = os.environ.get(
        "WEATHER_ALERT_BOT_CLIMATE_DB_PATH", ""
    ).strip()
    climate_db_path = (
        Path(configured_climate_db_path).expanduser()
        if configured_climate_db_path
        else DEFAULT_CLIMATE_DB_PATH
    )

    if require_telegram_token and token is None:
        raise ConfigError("Переменная окружения TELEGRAM_BOT_TOKEN не задана.")

    return Settings(
        telegram_bot_token=token,
        db_path=db_path,
        climate_db_path=climate_db_path,
    )
