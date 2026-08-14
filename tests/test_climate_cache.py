from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from weather_alert_bot.climate_cache import (
    CACHE_SCHEMA_VERSION,
    CLIMATE_SOURCE_IDENTIFIER,
    ClimateCacheError,
    SQLiteClimateNormalsCache,
    get_or_create_climate_normals,
    refresh_climate_normals,
)
from weather_alert_bot.climate_normals import (
    BASELINE_END,
    BASELINE_START,
    HISTORICAL_MODEL,
    ClimateNormalDay,
    ClimateNormals,
    HistoricalTemperatureDay,
    calculate_climate_normals,
)
from weather_alert_bot.config import DEFAULT_CLIMATE_DB_PATH, DEFAULT_DB_PATH, load_settings


def normals(latitude: float = 55.75, longitude: float = 37.62, timezone_name: str = "Europe/Moscow") -> ClimateNormals:
    return ClimateNormals(
        latitude=latitude,
        longitude=longitude,
        timezone=timezone_name,
        period_start=BASELINE_START,
        period_end=BASELINE_END,
        days=tuple(
            ClimateNormalDay(month, day, 1.0, 11.0, 8 if (month, day) == (2, 29) else 30)
            for offset in range(366)
            for month, day in [
                ((date(2000, 1, 1) + timedelta(days=offset)).month,
                 (date(2000, 1, 1) + timedelta(days=offset)).day)
            ]
        ),
    )


def historical_records() -> tuple[HistoricalTemperatureDay, ...]:
    return tuple(
        HistoricalTemperatureDay(BASELINE_START + timedelta(days=offset), 1.0, 11.0)
        for offset in range((BASELINE_END - BASELINE_START).days + 1)
    )


class ClimateCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "climate.sqlite3"
        self.generated_at = datetime(2026, 8, 13, 12, 34, 56, 789, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def save(self, value: ClimateNormals | None = None) -> SQLiteClimateNormalsCache:
        cache = SQLiteClimateNormalsCache(self.path)
        cache.save(value or normals(), generated_at=self.generated_at)
        return cache

    def test_creation_has_two_tables_and_does_not_use_settings_default(self) -> None:
        cache = SQLiteClimateNormalsCache(self.path)
        self.assertTrue(self.path.exists())
        with sqlite3.connect(self.path) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        self.assertIn("climate_normal_sets", tables)
        self.assertIn("climate_normal_days", tables)
        self.assertNotEqual(DEFAULT_CLIMATE_DB_PATH, DEFAULT_DB_PATH)
        self.assertEqual(cache.path, self.path)

    def test_save_get_roundtrip_metadata_all_days_and_february_29(self) -> None:
        cached = self.save().get(55.75, 37.62, "Europe/Moscow")
        self.assertIsNotNone(cached)
        assert cached is not None
        self.assertEqual(cached.normals, normals())
        self.assertEqual(cached.generated_at, self.generated_at)
        self.assertEqual(cached.model, HISTORICAL_MODEL)
        self.assertEqual(cached.source_identifier, CLIMATE_SOURCE_IDENTIFIER)
        self.assertEqual(cached.schema_version, CACHE_SCHEMA_VERSION)
        self.assertEqual(len(cached.normals.days), 366)
        self.assertEqual((cached.normals.days[59].month, cached.normals.days[59].day), (2, 29))

    def test_aware_non_utc_timestamp_is_saved_as_utc(self) -> None:
        source_time = datetime.fromisoformat("2026-08-13T15:34:56+03:00")
        cache = SQLiteClimateNormalsCache(self.path)
        cache.save(normals(), generated_at=source_time)
        loaded = cache.get(55.75, 37.62, "Europe/Moscow")
        assert loaded is not None
        self.assertEqual(loaded.generated_at, datetime(2026, 8, 13, 12, 34, 56, tzinfo=timezone.utc))

    def test_missing_identity_and_multiple_locations(self) -> None:
        cache = self.save()
        self.assertIsNone(cache.get(55.75, 37.63, "Europe/Moscow"))
        cache.save(normals(43.6, 39.7, "Europe/Moscow"), generated_at=self.generated_at)
        cache.save(normals(55.75, 37.62, "UTC"), generated_at=self.generated_at)
        self.assertIsNotNone(cache.get(55.75, 37.62, "Europe/Moscow"))
        self.assertIsNotNone(cache.get(43.6, 39.7, "Europe/Moscow"))
        self.assertIsNotNone(cache.get(55.75, 37.62, "UTC"))

    def test_overwrite_replaces_days_without_duplicates(self) -> None:
        cache = self.save()
        replacement = tuple(
            ClimateNormalDay(day.month, day.day, 2.0, 12.0, day.sample_count)
            for day in normals().days
        )
        cache.save(ClimateNormals(55.75, 37.62, "Europe/Moscow", BASELINE_START, BASELINE_END, replacement), generated_at=self.generated_at + timedelta(days=1))
        loaded = cache.get(55.75, 37.62, "Europe/Moscow")
        assert loaded is not None
        self.assertEqual(len(loaded.normals.days), 366)
        self.assertEqual(loaded.normals.days[0].normal_temperature_min, 2.0)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM climate_normal_sets").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM climate_normal_days").fetchone()[0], 366)

    def test_validation_rejects_bad_normals(self) -> None:
        original = normals()
        cases = {
            "missing": original.days[:-1],
            "duplicate": original.days[:-1] + (original.days[0],),
            "bad_month": (ClimateNormalDay(13, 1, 1, 11, 30),) + original.days[1:],
            "bad_day": (ClimateNormalDay(2, 30, 1, 11, 30),) + original.days[1:],
            "bad_range": (ClimateNormalDay(1, 1, 12, 11, 30),) + original.days[1:],
            "bad_count": (ClimateNormalDay(1, 1, 1, 11, 0),) + original.days[1:],
        }
        for name, days in cases.items():
            with self.subTest(name=name), self.assertRaises(ClimateCacheError):
                SQLiteClimateNormalsCache(self.path).save(
                    ClimateNormals(55.75, 37.62, "Europe/Moscow", BASELINE_START, BASELINE_END, days),
                    generated_at=self.generated_at,
                )

    def test_validation_rejects_bad_metadata_and_timestamp(self) -> None:
        for value in (
            datetime(2026, 8, 13, 12, 0),
            "2026-08-13T12:00:00Z",
        ):
            with self.subTest(value=value), self.assertRaises(ClimateCacheError):
                SQLiteClimateNormalsCache(self.path).save(normals(), generated_at=value)  # type: ignore[arg-type]
        for value in (float("nan"), True, "UTC", ""):
            with self.subTest(value=value), self.assertRaises(ClimateCacheError):
                SQLiteClimateNormalsCache(self.path).save(
                    ClimateNormals(value, 37.62, "Europe/Moscow", BASELINE_START, BASELINE_END, normals().days),  # type: ignore[arg-type]
                    generated_at=self.generated_at,
                )

    def test_corruption_incomplete_invalid_version_timestamp_and_values_raises(self) -> None:
        corruption_cases = (
            ("DELETE FROM climate_normal_days WHERE month = 2 AND day = 29",),
            ("UPDATE climate_normal_sets SET schema_version = 99",),
            ("UPDATE climate_normal_sets SET generated_at = 'bad'",),
            ("UPDATE climate_normal_days SET normal_temperature_min = 20 WHERE month = 1 AND day = 1",),
            ("UPDATE climate_normal_days SET sample_count = 0 WHERE month = 1 AND day = 1",),
            ("UPDATE climate_normal_days SET month = 13 WHERE month = 1 AND day = 1",),
        )
        for (statement,) in corruption_cases:
            with self.subTest(statement=statement):
                cache = self.save()
                with sqlite3.connect(self.path) as connection:
                    connection.execute(statement)
                with self.assertRaises(ClimateCacheError):
                    cache.get(55.75, 37.62, "Europe/Moscow")

    def test_read_only_behaviour(self) -> None:
        cache = self.save()
        read_only = SQLiteClimateNormalsCache(self.path, read_only=True)
        self.assertIsNotNone(read_only.get(55.75, 37.62, "Europe/Moscow"))
        with self.assertRaises(ClimateCacheError):
            read_only.save(normals(), generated_at=self.generated_at)
        missing = Path(self.temporary_directory.name) / "missing.sqlite3"
        with self.assertRaises(ClimateCacheError):
            SQLiteClimateNormalsCache(missing, read_only=True)
        self.assertFalse(missing.exists())

    def test_orchestration_hit_miss_and_failure_paths(self) -> None:
        cache = SQLiteClimateNormalsCache(self.path)
        client = type("FakeHistorical", (), {"fetch": lambda self, *args: historical_records()})()
        with patch("weather_alert_bot.climate_cache.calculate_climate_normals", wraps=calculate_climate_normals) as calculate:
            first = get_or_create_climate_normals(cache, client, 55.75, 37.62, "Europe/Moscow", self.generated_at)
            second = get_or_create_climate_normals(cache, client, 55.75, 37.62, "Europe/Moscow", self.generated_at)
        self.assertEqual(first, second)
        self.assertEqual(calculate.call_count, 1)

        failing_client = type("FailingHistorical", (), {"fetch": lambda self, *args: (_ for _ in ()).throw(RuntimeError("network"))})()
        with self.assertRaises(RuntimeError):
            get_or_create_climate_normals(SQLiteClimateNormalsCache(self.path.with_name("failed.sqlite3")), failing_client, 55.75, 37.63, "Europe/Moscow", self.generated_at)
        with sqlite3.connect(self.path.with_name("failed.sqlite3")) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM climate_normal_sets").fetchone()[0], 0)

    def test_refresh_always_fetches_and_replaces_snapshot(self) -> None:
        cache = self.save()
        calls = 0

        class FakeHistorical:
            def fetch(self, *args):
                nonlocal calls
                calls += 1
                return historical_records()

        refreshed = refresh_climate_normals(cache, FakeHistorical(), 55.75, 37.62, "Europe/Moscow", self.generated_at + timedelta(days=2))
        self.assertEqual(calls, 1)
        self.assertEqual(refreshed, normals(55.75, 37.62, "Europe/Moscow"))
        loaded = cache.get(55.75, 37.62, "Europe/Moscow")
        assert loaded is not None
        self.assertEqual(loaded.generated_at, self.generated_at + timedelta(days=2))

    def test_failed_replacement_rolls_back_and_calculation_failure_saves_nothing(self) -> None:
        cache = self.save()
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TRIGGER fail_climate_day_insert
                BEFORE INSERT ON climate_normal_days
                BEGIN
                    SELECT RAISE(ABORT, 'test write failure');
                END
                """
            )
        replacement = tuple(
            ClimateNormalDay(day.month, day.day, 2.0, 12.0, day.sample_count)
            for day in normals().days
        )
        with self.assertRaises(ClimateCacheError):
            cache.save(
                ClimateNormals(55.75, 37.62, "Europe/Moscow", BASELINE_START, BASELINE_END, replacement),
                generated_at=self.generated_at + timedelta(days=1),
            )
        loaded = cache.get(55.75, 37.62, "Europe/Moscow")
        assert loaded is not None
        self.assertEqual(loaded.normals.days[0].normal_temperature_min, 1.0)
        failed_path = self.path.with_name("calculation-failed.sqlite3")
        failed_cache = SQLiteClimateNormalsCache(failed_path)
        with patch("weather_alert_bot.climate_cache.calculate_climate_normals", side_effect=ClimateCacheError("calculation")):
            with self.assertRaises(ClimateCacheError):
                get_or_create_climate_normals(
                    failed_cache,
                    type("FakeHistorical", (), {"fetch": lambda self, *args: historical_records()})(),
                    55.75,
                    37.62,
                    "Europe/Moscow",
                    self.generated_at,
                )
        self.assertIsNone(failed_cache.get(55.75, 37.62, "Europe/Moscow"))

    def test_config_climate_path_environment_is_separate(self) -> None:
        configured = Path(self.temporary_directory.name) / "configured.sqlite3"
        with patch.dict(os.environ, {"WEATHER_ALERT_BOT_CLIMATE_DB_PATH": str(configured)}, clear=True):
            settings = load_settings()
        self.assertEqual(settings.climate_db_path, configured)
        self.assertEqual(settings.db_path, DEFAULT_DB_PATH)


if __name__ == "__main__":
    unittest.main()
