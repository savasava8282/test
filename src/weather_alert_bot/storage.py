from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
import re
from collections.abc import Iterable, Mapping

from weather_alert_bot.geocoding import GeocodingLocation


class StorageError(RuntimeError):
    """Raised when confirmed city settings cannot be stored safely."""


DAILY_SEND_TIME_DEFAULT = "07:00"
DAILY_SEND_DAYS_DEFAULT = "1,2,3,4,5,6,7"
DAILY_SENDING_ENABLED_DEFAULT = True
ONBOARDING_COMPLETED_DEFAULT = False
URGENT_WARNINGS_ENABLED_DEFAULT = True
WARNING_CATEGORY_DEFAULT = True
WARNING_CATEGORY_KEYS: tuple[str, ...] = (
    "magnetic_storm",
    "heat",
    "cold",
    "icing",
    "heavy_rain",
    "thunderstorm",
    "strong_wind",
    "storm",
)
WARNING_CATEGORY_COLUMNS = {
    key: f"warning_{key}_enabled" for key in WARNING_CATEGORY_KEYS
}
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


def normalize_warning_categories(value: Iterable[str]) -> frozenset[str]:
    """Validate and canonicalize the enabled warning-category keys."""
    if isinstance(value, (str, bytes, bytearray, Mapping)):
        raise ValueError("Категории предупреждений должны быть набором ключей.")

    try:
        categories = tuple(value)
    except TypeError as exc:
        raise ValueError("Категории предупреждений должны быть набором ключей.") from exc

    if any(not isinstance(category, str) for category in categories):
        raise ValueError("Ключ категории предупреждений должен быть текстом.")
    if any(category not in WARNING_CATEGORY_COLUMNS for category in categories):
        raise ValueError("Неизвестная категория предупреждений.")
    if len(categories) != len(set(categories)):
        raise ValueError("Категории предупреждений не должны повторяться.")

    return frozenset(categories)


@dataclass(frozen=True, slots=True)
class UserSettings:
    telegram_chat_id: int
    city_name: str
    latitude: float
    longitude: float
    timezone: str
    daily_send_time: str = DAILY_SEND_TIME_DEFAULT
    daily_send_days: str = DAILY_SEND_DAYS_DEFAULT
    urgent_warnings_enabled: bool = URGENT_WARNINGS_ENABLED_DEFAULT
    warning_magnetic_storm_enabled: bool = WARNING_CATEGORY_DEFAULT
    warning_heat_enabled: bool = WARNING_CATEGORY_DEFAULT
    warning_cold_enabled: bool = WARNING_CATEGORY_DEFAULT
    warning_icing_enabled: bool = WARNING_CATEGORY_DEFAULT
    warning_heavy_rain_enabled: bool = WARNING_CATEGORY_DEFAULT
    warning_thunderstorm_enabled: bool = WARNING_CATEGORY_DEFAULT
    warning_strong_wind_enabled: bool = WARNING_CATEGORY_DEFAULT
    warning_storm_enabled: bool = WARNING_CATEGORY_DEFAULT
    daily_sending_enabled: bool = DAILY_SENDING_ENABLED_DEFAULT
    onboarding_completed: bool = ONBOARDING_COMPLETED_DEFAULT


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
            daily_send_days TEXT NOT NULL DEFAULT '1,2,3,4,5,6,7',
            daily_sending_enabled INTEGER NOT NULL DEFAULT 1,
            urgent_warnings_enabled INTEGER NOT NULL DEFAULT 1,
            warning_magnetic_storm_enabled INTEGER NOT NULL DEFAULT 1,
            warning_heat_enabled INTEGER NOT NULL DEFAULT 1,
            warning_cold_enabled INTEGER NOT NULL DEFAULT 1,
            warning_icing_enabled INTEGER NOT NULL DEFAULT 1,
            warning_heavy_rain_enabled INTEGER NOT NULL DEFAULT 1,
            warning_thunderstorm_enabled INTEGER NOT NULL DEFAULT 1,
            warning_strong_wind_enabled INTEGER NOT NULL DEFAULT 1,
            warning_storm_enabled INTEGER NOT NULL DEFAULT 1,
            onboarding_completed INTEGER NOT NULL DEFAULT 0
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
                if "daily_sending_enabled" not in columns:
                    connection.execute(
                        """
                        ALTER TABLE user_settings
                        ADD COLUMN daily_sending_enabled INTEGER NOT NULL DEFAULT 1
                        """
                    )
                if "urgent_warnings_enabled" not in columns:
                    connection.execute(
                        """
                        ALTER TABLE user_settings
                        ADD COLUMN urgent_warnings_enabled INTEGER NOT NULL DEFAULT 1
                        """
                    )
                for column in WARNING_CATEGORY_COLUMNS.values():
                    if column not in columns:
                        connection.execute(
                            f"""
                            ALTER TABLE user_settings
                            ADD COLUMN {column} INTEGER NOT NULL DEFAULT 1
                            """
                        )
                if "onboarding_completed" not in columns:
                    connection.execute(
                        """
                        ALTER TABLE user_settings
                        ADD COLUMN onboarding_completed INTEGER NOT NULL DEFAULT 0
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
                           daily_send_time, daily_send_days, urgent_warnings_enabled,
                           warning_magnetic_storm_enabled, warning_heat_enabled,
                           warning_cold_enabled, warning_icing_enabled,
                           warning_heavy_rain_enabled, warning_thunderstorm_enabled,
                           warning_strong_wind_enabled, warning_storm_enabled,
                           daily_sending_enabled, onboarding_completed
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
            urgent_warnings_enabled=bool(row[7]),
            warning_magnetic_storm_enabled=bool(row[8]),
            warning_heat_enabled=bool(row[9]),
            warning_cold_enabled=bool(row[10]),
            warning_icing_enabled=bool(row[11]),
            warning_heavy_rain_enabled=bool(row[12]),
            warning_thunderstorm_enabled=bool(row[13]),
            warning_strong_wind_enabled=bool(row[14]),
            warning_storm_enabled=bool(row[15]),
            daily_sending_enabled=bool(row[16]),
            onboarding_completed=bool(row[17]),
        )

    def mark_onboarding_completed(self, telegram_chat_id: int) -> None:
        """Mark onboarding complete for an existing saved city only."""
        try:
            with sqlite3.connect(self.path) as connection:
                cursor = connection.execute(
                    """
                    UPDATE user_settings
                    SET onboarding_completed = 1
                    WHERE telegram_chat_id = ?
                      AND city_name IS NOT NULL
                      AND TRIM(city_name) <> ''
                    """,
                    (telegram_chat_id,),
                )
                if cursor.rowcount != 1:
                    raise StorageError("Сначала сохраните подтверждённый город.")
        except StorageError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise StorageError(
                "Не удалось завершить первоначальную настройку."
            ) from exc

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

    def save_urgent_warnings_enabled(
        self,
        telegram_chat_id: int,
        enabled: bool,
    ) -> None:
        """Update urgent-warning preference for an existing saved city only."""
        if type(enabled) is not bool:
            raise StorageError("Настройка срочных предупреждений должна быть boolean.")

        try:
            with sqlite3.connect(self.path) as connection:
                cursor = connection.execute(
                    """
                    UPDATE user_settings
                    SET urgent_warnings_enabled = ?
                    WHERE telegram_chat_id = ?
                    """,
                    (int(enabled), telegram_chat_id),
                )
                if cursor.rowcount != 1:
                    raise StorageError("Сначала сохраните город пользователя.")
        except StorageError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise StorageError(
                "Не удалось сохранить настройку срочных предупреждений."
            ) from exc

    def save_daily_sending_enabled(
        self,
        telegram_chat_id: int,
        enabled: bool,
    ) -> None:
        """Update daily-sending preference for an existing saved city only."""
        if type(enabled) is not bool:
            raise StorageError("Настройка ежедневной рассылки должна быть boolean.")

        try:
            with sqlite3.connect(self.path) as connection:
                cursor = connection.execute(
                    """
                    UPDATE user_settings
                    SET daily_sending_enabled = ?
                    WHERE telegram_chat_id = ?
                    """,
                    (int(enabled), telegram_chat_id),
                )
                if cursor.rowcount != 1:
                    raise StorageError("Сначала сохраните город пользователя.")
        except StorageError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise StorageError(
                "Не удалось сохранить настройку ежедневной рассылки."
            ) from exc

    def save_warning_categories(
        self,
        telegram_chat_id: int,
        enabled_categories: Iterable[str],
    ) -> None:
        """Replace all warning-category states for an existing saved city."""
        try:
            normalized_categories = normalize_warning_categories(enabled_categories)
        except (TypeError, ValueError) as exc:
            raise StorageError("Некорректные категории предупреждений.") from exc

        assignments = ", ".join(
            f"{column} = ?" for column in WARNING_CATEGORY_COLUMNS.values()
        )
        values = [
            int(category in normalized_categories)
            for category in WARNING_CATEGORY_COLUMNS
        ]
        values.append(telegram_chat_id)

        try:
            with sqlite3.connect(self.path) as connection:
                cursor = connection.execute(
                    f"""
                    UPDATE user_settings
                    SET {assignments}
                    WHERE telegram_chat_id = ?
                    """,
                    values,
                )
                if cursor.rowcount != 1:
                    raise StorageError("Сначала сохраните город пользователя.")
        except StorageError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise StorageError(
                "Не удалось сохранить категории предупреждений."
            ) from exc
