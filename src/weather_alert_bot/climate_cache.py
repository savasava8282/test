from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import math
from pathlib import Path
import sqlite3
from urllib.parse import quote

from weather_alert_bot.climate_normals import (
    BASELINE_END,
    BASELINE_START,
    HISTORICAL_ENDPOINT,
    HISTORICAL_MODEL,
    ClimateNormalDay,
    ClimateNormals,
    OpenMeteoHistoricalWeatherClient,
    calculate_climate_normals,
)


CACHE_SCHEMA_VERSION = 1
CLIMATE_SOURCE_IDENTIFIER = HISTORICAL_ENDPOINT


class ClimateCacheError(RuntimeError):
    """Raised when calculated climate-normal cache data is unsafe to use."""


@dataclass(frozen=True, slots=True)
class CachedClimateNormals:
    """A validated climate-normal snapshot together with cache metadata."""

    normals: ClimateNormals
    generated_at: datetime
    model: str
    source_identifier: str
    schema_version: int = CACHE_SCHEMA_VERSION


# A leap year makes the expected key set include 29 February without storing a year.
_EXPECTED_CALENDAR_DAYS = frozenset(
    (
        (date(2000, 1, 1) + timedelta(days=offset)).month,
        (date(2000, 1, 1) + timedelta(days=offset)).day,
    )
    for offset in range(366)
)


class SQLiteClimateNormalsCache:
    """Separate SQLite persistence for calculated climate-normal snapshots."""

    _SCHEMA = (
        """
        CREATE TABLE IF NOT EXISTS climate_normal_sets (
            set_id INTEGER PRIMARY KEY,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            timezone TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            model TEXT NOT NULL,
            source_identifier TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            UNIQUE (latitude, longitude, timezone, period_start, period_end, model)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS climate_normal_days (
            set_id INTEGER NOT NULL,
            month INTEGER NOT NULL,
            day INTEGER NOT NULL,
            normal_temperature_min REAL NOT NULL,
            normal_temperature_max REAL NOT NULL,
            sample_count INTEGER NOT NULL,
            PRIMARY KEY (set_id, month, day),
            FOREIGN KEY (set_id) REFERENCES climate_normal_sets(set_id)
                ON DELETE CASCADE
        )
        """,
    )

    _SET_COLUMNS = frozenset(
        {
            "set_id",
            "latitude",
            "longitude",
            "timezone",
            "period_start",
            "period_end",
            "model",
            "source_identifier",
            "generated_at",
            "schema_version",
        }
    )
    _DAY_COLUMNS = frozenset(
        {
            "set_id",
            "month",
            "day",
            "normal_temperature_min",
            "normal_temperature_max",
            "sample_count",
        }
    )

    def __init__(self, path: Path | str, *, read_only: bool = False) -> None:
        self.path = Path(path).expanduser()
        self._read_only = read_only
        try:
            if self._read_only:
                with self._connect() as connection:
                    self._validate_schema(connection)
            else:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self._connect() as connection:
                    for statement in self._SCHEMA:
                        connection.execute(statement)
                    self._validate_schema(connection)
        except ClimateCacheError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise ClimateCacheError("Не удалось инициализировать кэш климатических норм.") from exc

    def _connect(self) -> sqlite3.Connection:
        if not self._read_only:
            connection = sqlite3.connect(self.path)
        else:
            database_uri = f"file:{quote(str(self.path.resolve()), safe='/')}?mode=ro"
            connection = sqlite3.connect(database_uri, uri=True)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @classmethod
    def _validate_schema(cls, connection: sqlite3.Connection) -> None:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not {"climate_normal_sets", "climate_normal_days"}.issubset(tables):
            raise ClimateCacheError("Кэш климатических норм не содержит поддерживаемую схему.")

        set_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(climate_normal_sets)")
        }
        day_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(climate_normal_days)")
        }
        if not cls._SET_COLUMNS.issubset(set_columns) or not cls._DAY_COLUMNS.issubset(day_columns):
            raise ClimateCacheError("Кэш климатических норм имеет неполную схему.")

    @staticmethod
    def _coordinate(value: object, label: str, minimum: float, maximum: float) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not minimum <= float(value) <= maximum
        ):
            raise ClimateCacheError(f"Некорректная {label} климатического кэша.")
        return float(value)

    @staticmethod
    def _timezone(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ClimateCacheError("Некорректный часовой пояс климатического кэша.")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ClimateCacheError("Некорректный часовой пояс климатического кэша.")
        return value.strip()

    @staticmethod
    def _generated_at(value: object) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ClimateCacheError("Время генерации климатического кэша должно быть aware datetime.")
        try:
            if value.utcoffset() is None:
                raise ClimateCacheError("Время генерации климатического кэша должно быть aware datetime.")
            return value.astimezone(timezone.utc)
        except ClimateCacheError:
            raise
        except (OverflowError, TypeError, ValueError) as exc:
            raise ClimateCacheError("Время генерации климатического кэша имеет недопустимый формат.") from exc

    @staticmethod
    def _generated_at_text(value: datetime) -> str:
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")

    @classmethod
    def _parse_generated_at(cls, value: object) -> datetime:
        if not isinstance(value, str) or not value:
            raise ClimateCacheError("Кэш содержит некорректное время генерации.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ClimateCacheError("Кэш содержит некорректное время генерации.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ClimateCacheError("Кэш содержит не aware время генерации.")
        if parsed.utcoffset() != timedelta(0):
            raise ClimateCacheError("Кэш содержит время генерации не в UTC.")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _date_text(value: object, label: str) -> date:
        if not isinstance(value, str):
            raise ClimateCacheError(f"Кэш содержит некорректное поле {label}.")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ClimateCacheError(f"Кэш содержит некорректное поле {label}.") from exc
        if parsed.isoformat() != value:
            raise ClimateCacheError(f"Кэш содержит некорректное поле {label}.")
        return parsed

    @staticmethod
    def _temperature(value: object, label: str) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ClimateCacheError(f"Кэш содержит некорректную температуру {label}.")
        return float(value)

    @staticmethod
    def _sample_count(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ClimateCacheError("Кэш содержит некорректное количество наблюдений.")
        return value

    @classmethod
    def _validated_normals(cls, normals: object) -> tuple[ClimateNormals, tuple[ClimateNormalDay, ...]]:
        if not isinstance(normals, ClimateNormals):
            raise ClimateCacheError("Климатическая норма имеет недопустимый тип.")
        latitude = cls._coordinate(normals.latitude, "широта", -90, 90)
        longitude = cls._coordinate(normals.longitude, "долгота", -180, 180)
        timezone_name = cls._timezone(normals.timezone)
        if normals.period_start != BASELINE_START or normals.period_end != BASELINE_END:
            raise ClimateCacheError("Климатическая норма имеет неподдерживаемый период.")
        try:
            days = tuple(normals.days)
        except TypeError as exc:
            raise ClimateCacheError("Климатическая норма не содержит корректные календарные дни.") from exc
        if len(days) != 366:
            raise ClimateCacheError("Климатическая норма не содержит полный набор 366 дней.")

        seen: set[tuple[int, int]] = set()
        validated_days: list[ClimateNormalDay] = []
        for normal_day in days:
            if not isinstance(normal_day, ClimateNormalDay):
                raise ClimateCacheError("Климатическая норма содержит недопустимый день.")
            month = normal_day.month
            day = normal_day.day
            if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
                raise ClimateCacheError("Кэш содержит некорректный месяц.")
            if isinstance(day, bool) or not isinstance(day, int):
                raise ClimateCacheError("Кэш содержит некорректный день.")
            try:
                date(2000, month, day)
            except ValueError as exc:
                raise ClimateCacheError("Кэш содержит некорректный календарный день.") from exc
            key = (month, day)
            if key in seen:
                raise ClimateCacheError("Климатическая норма содержит повторяющийся день.")
            seen.add(key)
            minimum = cls._temperature(normal_day.normal_temperature_min, "minimum")
            maximum = cls._temperature(normal_day.normal_temperature_max, "maximum")
            if minimum > maximum:
                raise ClimateCacheError("Климатическая норма содержит minimum выше maximum.")
            sample_count = cls._sample_count(normal_day.sample_count)
            validated_days.append(
                ClimateNormalDay(month, day, minimum, maximum, sample_count)
            )
        if seen != _EXPECTED_CALENDAR_DAYS or (2, 29) not in seen:
            raise ClimateCacheError("Климатическая норма не покрывает все 366 календарных дней.")

        validated_normals = ClimateNormals(
            latitude=latitude,
            longitude=longitude,
            timezone=timezone_name,
            period_start=BASELINE_START,
            period_end=BASELINE_END,
            days=tuple(validated_days),
        )
        return validated_normals, tuple(validated_days)

    def save(self, normals: ClimateNormals, *, generated_at: datetime) -> None:
        """Atomically replace the snapshot for one location identity."""
        if self._read_only:
            raise ClimateCacheError("Запись в read-only кэш климатических норм запрещена.")
        validated_normals, days = self._validated_normals(normals)
        normalized_generated_at = self._generated_at(generated_at)
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT set_id FROM climate_normal_sets
                    WHERE latitude = ? AND longitude = ? AND timezone = ?
                      AND period_start = ? AND period_end = ? AND model = ?
                    """,
                    (
                        validated_normals.latitude,
                        validated_normals.longitude,
                        validated_normals.timezone,
                        BASELINE_START.isoformat(),
                        BASELINE_END.isoformat(),
                        HISTORICAL_MODEL,
                    ),
                ).fetchone()
                metadata = (
                    validated_normals.latitude,
                    validated_normals.longitude,
                    validated_normals.timezone,
                    BASELINE_START.isoformat(),
                    BASELINE_END.isoformat(),
                    HISTORICAL_MODEL,
                    CLIMATE_SOURCE_IDENTIFIER,
                    self._generated_at_text(normalized_generated_at),
                    CACHE_SCHEMA_VERSION,
                )
                if row is None:
                    cursor = connection.execute(
                        """
                        INSERT INTO climate_normal_sets (
                            latitude, longitude, timezone, period_start, period_end,
                            model, source_identifier, generated_at, schema_version
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        metadata,
                    )
                    set_id = cursor.lastrowid
                else:
                    set_id = row[0]
                    connection.execute(
                        """
                        UPDATE climate_normal_sets
                        SET latitude = ?, longitude = ?, timezone = ?,
                            period_start = ?, period_end = ?, model = ?,
                            source_identifier = ?, generated_at = ?, schema_version = ?
                        WHERE set_id = ?
                        """,
                        metadata + (set_id,),
                    )
                    connection.execute(
                        "DELETE FROM climate_normal_days WHERE set_id = ?", (set_id,)
                    )

                connection.executemany(
                    """
                    INSERT INTO climate_normal_days (
                        set_id, month, day, normal_temperature_min,
                        normal_temperature_max, sample_count
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            set_id,
                            normal_day.month,
                            normal_day.day,
                            normal_day.normal_temperature_min,
                            normal_day.normal_temperature_max,
                            normal_day.sample_count,
                        )
                        for normal_day in days
                    ],
                )
        except ClimateCacheError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise ClimateCacheError("Не удалось сохранить климатическую норму в кэш.") from exc

    def get(self, latitude: float, longitude: float, timezone_name: str) -> CachedClimateNormals | None:
        """Return a complete cached snapshot, or None for a cache miss."""
        normalized_latitude = self._coordinate(latitude, "широта", -90, 90)
        normalized_longitude = self._coordinate(longitude, "долгота", -180, 180)
        normalized_timezone = self._timezone(timezone_name)
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT set_id, latitude, longitude, timezone, period_start,
                           period_end, model, source_identifier, generated_at,
                           schema_version
                    FROM climate_normal_sets
                    WHERE latitude = ? AND longitude = ? AND timezone = ?
                      AND period_start = ? AND period_end = ? AND model = ?
                    """,
                    (
                        normalized_latitude,
                        normalized_longitude,
                        normalized_timezone,
                        BASELINE_START.isoformat(),
                        BASELINE_END.isoformat(),
                        HISTORICAL_MODEL,
                    ),
                ).fetchall()
                if not rows:
                    related_rows = connection.execute(
                        """
                        SELECT set_id FROM climate_normal_sets
                        WHERE latitude = ? AND longitude = ? AND timezone = ?
                        """,
                        (
                            normalized_latitude,
                            normalized_longitude,
                            normalized_timezone,
                        ),
                    ).fetchall()
                    if related_rows:
                        raise ClimateCacheError(
                            "Кэш содержит набор с неподдерживаемой identity."
                        )
                    return None
                if len(rows) != 1:
                    raise ClimateCacheError("Кэш содержит повторяющиеся наборы для одной identity.")
                row = rows[0]
                return self._read_snapshot(connection, row)
        except ClimateCacheError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise ClimateCacheError("Не удалось прочитать климатическую норму из кэша.") from exc

    @classmethod
    def _read_snapshot(
        cls,
        connection: sqlite3.Connection,
        row: tuple[object, ...],
    ) -> CachedClimateNormals:
        set_id, latitude, longitude, timezone_name, period_start, period_end, model, source, generated_at, version = row
        if isinstance(set_id, bool) or not isinstance(set_id, int):
            raise ClimateCacheError("Кэш содержит некорректный идентификатор набора.")
        normalized_latitude = cls._coordinate(latitude, "широта", -90, 90)
        normalized_longitude = cls._coordinate(longitude, "долгота", -180, 180)
        normalized_timezone = cls._timezone(timezone_name)
        if cls._date_text(period_start, "period_start") != BASELINE_START:
            raise ClimateCacheError("Кэш содержит неподдерживаемый period_start.")
        if cls._date_text(period_end, "period_end") != BASELINE_END:
            raise ClimateCacheError("Кэш содержит неподдерживаемый period_end.")
        if model != HISTORICAL_MODEL:
            raise ClimateCacheError("Кэш содержит неподдерживаемую модель.")
        if source != CLIMATE_SOURCE_IDENTIFIER:
            raise ClimateCacheError("Кэш содержит неподдерживаемый source identifier.")
        if isinstance(version, bool) or not isinstance(version, int) or version != CACHE_SCHEMA_VERSION:
            raise ClimateCacheError("Кэш содержит неподдерживаемую версию схемы.")
        normalized_generated_at = cls._parse_generated_at(generated_at)

        rows = connection.execute(
            """
            SELECT month, day, normal_temperature_min,
                   normal_temperature_max, sample_count
            FROM climate_normal_days
            WHERE set_id = ?
            ORDER BY month, day
            """,
            (set_id,),
        ).fetchall()
        if len(rows) != 366:
            raise ClimateCacheError("Кэш содержит неполный набор климатических дней.")
        days: list[ClimateNormalDay] = []
        seen: set[tuple[int, int]] = set()
        for day_row in rows:
            month, day, minimum, maximum, sample_count = day_row
            if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
                raise ClimateCacheError("Кэш содержит некорректный месяц.")
            if isinstance(day, bool) or not isinstance(day, int):
                raise ClimateCacheError("Кэш содержит некорректный день.")
            try:
                date(2000, month, day)
            except ValueError as exc:
                raise ClimateCacheError("Кэш содержит некорректный календарный день.") from exc
            key = (month, day)
            if key in seen:
                raise ClimateCacheError("Кэш содержит повторяющийся календарный день.")
            seen.add(key)
            parsed_minimum = cls._temperature(minimum, "minimum")
            parsed_maximum = cls._temperature(maximum, "maximum")
            if parsed_minimum > parsed_maximum:
                raise ClimateCacheError("Кэш содержит minimum выше maximum.")
            days.append(
                ClimateNormalDay(
                    month,
                    day,
                    parsed_minimum,
                    parsed_maximum,
                    cls._sample_count(sample_count),
                )
            )
        if seen != _EXPECTED_CALENDAR_DAYS or (2, 29) not in seen:
            raise ClimateCacheError("Кэш не содержит все 366 календарных дней.")
        normals = ClimateNormals(
            latitude=normalized_latitude,
            longitude=normalized_longitude,
            timezone=normalized_timezone,
            period_start=BASELINE_START,
            period_end=BASELINE_END,
            days=tuple(days),
        )
        return CachedClimateNormals(
            normals=normals,
            generated_at=normalized_generated_at,
            model=model,
            source_identifier=source,
            schema_version=version,
        )


def get_or_create_climate_normals(
    cache: SQLiteClimateNormalsCache,
    historical_client: OpenMeteoHistoricalWeatherClient,
    latitude: float,
    longitude: float,
    timezone_name: str,
    generated_at: datetime,
    *,
    calculator=None,
) -> ClimateNormals:
    """Use cache on hit; fetch, calculate and save exactly once on miss."""
    cached = cache.get(latitude, longitude, timezone_name)
    if cached is not None:
        return cached.normals
    historical_days = historical_client.fetch(latitude, longitude, timezone_name)
    calculation = calculate_climate_normals if calculator is None else calculator
    normals = calculation(
        historical_days, latitude, longitude, timezone_name
    )
    cache.save(normals, generated_at=generated_at)
    return normals


def refresh_climate_normals(
    cache: SQLiteClimateNormalsCache,
    historical_client: OpenMeteoHistoricalWeatherClient,
    latitude: float,
    longitude: float,
    timezone_name: str,
    generated_at: datetime,
    *,
    calculator=None,
) -> ClimateNormals:
    """Always fetch and replace one location's calculated snapshot."""
    historical_days = historical_client.fetch(latitude, longitude, timezone_name)
    calculation = calculate_climate_normals if calculator is None else calculator
    normals = calculation(
        historical_days, latitude, longitude, timezone_name
    )
    cache.save(normals, generated_at=generated_at)
    return normals
