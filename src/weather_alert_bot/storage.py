from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
import re

from weather_alert_bot.geocoding import GeocodingLocation


class StorageError(RuntimeError):
    """Raised when confirmed city settings cannot be stored safely."""


DAILY_SEND_TIME_DEFAULT = "07:00"
DAILY_SEND_DAYS_DEFAULT = "1,2,3,4,5,6,7"
_DAILY_SEND_TIME_PATTERN = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")
_DAILY_SEND_DAY_PATTERN = re.compile(r"[1-7]\Z")


def normalize_daily_send_time(value: str) -> str:
    """Return a strict local 24-hour time in normalized HH:MM form."""
    if not isinstance(value, str):
        raise ValueError("Время ежедневной отправки должно быть текстом.")

    normalized = value.strip()
    if _DAILY_SEND_TIME_PATTERN.fullmatch(normalized) is None:
        raise ValueError("Время ежедневной отправки должно быть в формате ЧЧ:ММ.")
    return normalized


def normalize_daily_send_days(value: str) -> str:
    """Return selected weekdays in canonical ascending numeric form."""
    if not isinstance(value, str):
        raise ValueError("Дни ежедневной отправки должны быть текстом.")

    parts = value.strip().split(",")
    if not parts or any(not part.strip() for part in parts):
        raise ValueError("Нужно выбрать хотя бы один день.")

    normalized_parts = [part.strip() for part in parts]
    if any(_DAILY_SEND_DAY_PATTERN.fullmatch(part) is None for part in normalized_parts):
        raise ValueError("Дни должны быть номерами от 1 до 7 через запятую.")
    if len(set(normalized_parts)) != len(normalized_parts):
        raise ValueError("Дни не должны повторяться.")

    return ",".join(sorted(normalized_parts, key=int))


@dataclass(frozen=True, slots=True)
class UserSettings:
    telegram_chat_id: int
    city_name: str
    latitude: float
    longitude: float
    timezone: str
    daily_send_time: str = DAILY_SEND_TIME_DEFAULT
    daily_send_days: str = DAILY_SEND_DAYS_DEFAULT


class SQLiteSettingsStore:
    """SQLite-backed storage for confirmed per-chat city settings."""

    _TABLE_SCHEMA = """
        CREATE TABLE IF NOT EXISTS user_settings (
            telegram_chat_id INTEGER PRIMARY KEY,
            city_name TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            timezone TEXT NOT NULL,
            daily_send_time TEXT NOT NULL DEFAULT '07:00',
            daily_send_days TEXT NOT NULL DEFAULT '1,2,3,4,5,6,7'
        )
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path) as connection:
                connection.execute(self._TABLE_SCHEMA)
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(user_settings)")
                }
                if "daily_send_time" not in columns:
                    connection.execute(
                        """
                        ALTER TABLE user_settings
                        ADD COLUMN daily_send_time TEXT NOT NULL DEFAULT '07:00'
                        """
                    )
                if "daily_send_days" not in columns:
                    connection.execute(
                        """
                        ALTER TABLE user_settings
                        ADD COLUMN daily_send_days TEXT NOT NULL DEFAULT '1,2,3,4,5,6,7'
                        """
                    )
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
                    SELECT telegram_chat_id, city_name, latitude, longitude, timezone,
                           daily_send_time, daily_send_days
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
            daily_send_time=row[5],
            daily_send_days=row[6],
        )

    def save_daily_send_time(self, telegram_chat_id: int, daily_send_time: str) -> None:
        """Update the local daily send time for an existing saved city only."""
        try:
            normalized_time = normalize_daily_send_time(daily_send_time)
        except ValueError as exc:
            raise StorageError("Некорректное время ежедневной отправки.") from exc

        try:
            with sqlite3.connect(self.path) as connection:
                cursor = connection.execute(
                    """
                    UPDATE user_settings
                    SET daily_send_time = ?
                    WHERE telegram_chat_id = ?
                    """,
                    (normalized_time, telegram_chat_id),
                )
                if cursor.rowcount != 1:
                    raise StorageError("Сначала сохраните город пользователя.")
        except StorageError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise StorageError("Не удалось сохранить время ежедневной отправки.") from exc

    def save_daily_send_days(self, telegram_chat_id: int, daily_send_days: str) -> None:
        """Update weekdays for an existing saved city only."""
        try:
            normalized_days = normalize_daily_send_days(daily_send_days)
        except ValueError as exc:
            raise StorageError("Некорректные дни ежедневной отправки.") from exc

        try:
            with sqlite3.connect(self.path) as connection:
                cursor = connection.execute(
                    """
                    UPDATE user_settings
                    SET daily_send_days = ?
                    WHERE telegram_chat_id = ?
                    """,
                    (normalized_days, telegram_chat_id),
                )
                if cursor.rowcount != 1:
                    raise StorageError("Сначала сохраните город пользователя.")
        except StorageError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise StorageError("Не удалось сохранить дни ежедневной отправки.") from exc
