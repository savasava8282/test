from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from weather_alert_bot.geocoding import GeocodingLocation


class StorageError(RuntimeError):
    """Raised when confirmed city settings cannot be stored safely."""


@dataclass(frozen=True, slots=True)
class UserSettings:
    telegram_chat_id: int
    city_name: str
    latitude: float
    longitude: float
    timezone: str


class SQLiteSettingsStore:
    """SQLite-backed storage for confirmed per-chat city settings."""

    _TABLE_SCHEMA = """
        CREATE TABLE IF NOT EXISTS user_settings (
            telegram_chat_id INTEGER PRIMARY KEY,
            city_name TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            timezone TEXT NOT NULL
        )
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path) as connection:
                connection.execute(self._TABLE_SCHEMA)
        except (OSError, sqlite3.Error) as exc:
            raise StorageError("Не удалось инициализировать хранилище.") from exc

    def save_confirmed_city(self, telegram_chat_id: int, candidate: GeocodingLocation) -> None:
        """Insert or update the confirmed candidate for one Telegram chat."""
        try:
            with sqlite3.connect(self.path) as connection:
                connection.execute(
                    """
                    INSERT INTO user_settings (
                        telegram_chat_id, city_name, latitude, longitude, timezone
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(telegram_chat_id) DO UPDATE SET
                        city_name = excluded.city_name,
                        latitude = excluded.latitude,
                        longitude = excluded.longitude,
                        timezone = excluded.timezone
                    """,
                    (
                        telegram_chat_id,
                        candidate.name,
                        candidate.latitude,
                        candidate.longitude,
                        candidate.timezone,
                    ),
                )
        except (OSError, sqlite3.Error) as exc:
            raise StorageError("Не удалось сохранить настройки города.") from exc

    def get_user_settings(self, telegram_chat_id: int) -> UserSettings | None:
        """Return settings for a chat, primarily for diagnostics and tests."""
        try:
            with sqlite3.connect(self.path) as connection:
                row = connection.execute(
                    """
                    SELECT telegram_chat_id, city_name, latitude, longitude, timezone
                    FROM user_settings
                    WHERE telegram_chat_id = ?
                    """,
                    (telegram_chat_id,),
                ).fetchone()
        except (OSError, sqlite3.Error) as exc:
            raise StorageError("Не удалось прочитать настройки города.") from exc

        if row is None:
            return None
        return UserSettings(
            telegram_chat_id=row[0],
            city_name=row[1],
            latitude=row[2],
            longitude=row[3],
            timezone=row[4],
        )
