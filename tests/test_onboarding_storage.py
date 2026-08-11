from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from weather_alert_bot.geocoding import GeocodingLocation
from weather_alert_bot.storage import (
    ONBOARDING_COMPLETED_DEFAULT,
    SQLiteSettingsStore,
    StorageError,
)


def candidate(name: str = "Москва") -> GeocodingLocation:
    return GeocodingLocation(
        id=1,
        name=name,
        latitude=55.75204,
        longitude=37.61781,
        timezone="Europe/Moscow",
        country_code="RU",
        country="Россия",
    )


class OnboardingStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "settings.sqlite3"
        self.store = SQLiteSettingsStore(self.path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_new_schema_has_onboarding_column_and_default_zero(self) -> None:
        with sqlite3.connect(self.path) as connection:
            column_info = {
                row[1]: row[4]
                for row in connection.execute("PRAGMA table_info(user_settings)")
            }

        self.assertEqual(column_info["onboarding_completed"], "0")
        self.store.save_confirmed_city(42, candidate())
        settings = self.store.get_user_settings(42)
        self.assertIs(settings.onboarding_completed, ONBOARDING_COMPLETED_DEFAULT)

    def test_current_schema_migration_adds_only_onboarding_column_and_preserves_data(self) -> None:
        path = Path(self.temporary_directory.name) / "current.sqlite3"
        with sqlite3.connect(path) as connection:
            connection.execute(
                """
                CREATE TABLE user_settings (
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
                    warning_storm_enabled INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            connection.execute(
                """
                INSERT INTO user_settings VALUES (
                    42, 'Москва', 55.75204, 37.61781, 'Europe/Moscow',
                    '08:30', '1,3,5', 0, 0, 1, 0, 1, 0, 1, 0, 1, 0
                )
                """
            )
            before_columns = [
                row[1] for row in connection.execute("PRAGMA table_info(user_settings)")
            ]
            before_values = connection.execute(
                "SELECT * FROM user_settings WHERE telegram_chat_id = 42"
            ).fetchone()

        SQLiteSettingsStore(path)

        with sqlite3.connect(path) as connection:
            after_columns = [
                row[1] for row in connection.execute("PRAGMA table_info(user_settings)")
            ]
            after_values = connection.execute(
                "SELECT * FROM user_settings WHERE telegram_chat_id = 42"
            ).fetchone()

        self.assertEqual(after_columns, before_columns + ["onboarding_completed"])
        self.assertEqual(after_values[: len(before_values)], before_values)
        self.assertEqual(after_values[-1], 0)

        SQLiteSettingsStore(path)
        with sqlite3.connect(path) as connection:
            self.assertEqual(
                [row[1] for row in connection.execute("PRAGMA table_info(user_settings)")],
                after_columns,
            )

    def test_mark_changes_zero_to_one_and_repeat_is_safe(self) -> None:
        self.store.save_confirmed_city(42, candidate())

        self.store.mark_onboarding_completed(42)
        self.store.mark_onboarding_completed(42)

        self.assertIs(self.store.get_user_settings(42).onboarding_completed, True)

    def test_mark_updates_only_completion_flag(self) -> None:
        self.store.save_confirmed_city(42, candidate())
        self.store.save_daily_send_time(42, "08:30")
        self.store.save_daily_send_days(42, "1,3,5")

        with sqlite3.connect(self.path) as connection:
            before = connection.execute(
                "SELECT * FROM user_settings WHERE telegram_chat_id = 42"
            ).fetchone()

        self.store.mark_onboarding_completed(42)

        with sqlite3.connect(self.path) as connection:
            after = connection.execute(
                "SELECT * FROM user_settings WHERE telegram_chat_id = 42"
            ).fetchone()

        self.assertEqual(after[:-1], before[:-1])
        self.assertEqual(before[-1], 0)
        self.assertEqual(after[-1], 1)

    def test_missing_user_is_not_created(self) -> None:
        with self.assertRaises(StorageError):
            self.store.mark_onboarding_completed(42)

        self.assertIsNone(self.store.get_user_settings(42))

    def test_save_confirmed_city_does_not_reset_completed_flag(self) -> None:
        self.store.save_confirmed_city(42, candidate())
        self.store.mark_onboarding_completed(42)
        self.store.save_confirmed_city(42, candidate("Сочи"))

        settings = self.store.get_user_settings(42)
        self.assertEqual(settings.city_name, "Сочи")
        self.assertIs(settings.onboarding_completed, True)

    def test_sqlite_and_os_errors_become_storage_error(self) -> None:
        with patch("weather_alert_bot.storage.sqlite3.connect", side_effect=OSError("private")):
            with self.assertRaises(StorageError):
                self.store.mark_onboarding_completed(42)


if __name__ == "__main__":
    unittest.main()
