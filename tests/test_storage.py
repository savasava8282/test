from pathlib import Path
import sqlite3
import tempfile
import unittest

from weather_alert_bot.geocoding import GeocodingLocation
from weather_alert_bot.storage import (
    DAILY_SEND_DAYS_DEFAULT,
    DAILY_SEND_TIME_DEFAULT,
    URGENT_WARNINGS_ENABLED_DEFAULT,
    SQLiteSettingsStore,
    StorageError,
    UserSettings,
    normalize_daily_send_days,
)


def candidate(name: str, latitude: float, longitude: float, timezone: str) -> GeocodingLocation:
    return GeocodingLocation(
        id=1,
        name=name,
        latitude=latitude,
        longitude=longitude,
        timezone=timezone,
        country_code="RU",
        country="Россия",
    )


class SQLiteSettingsStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "nested" / "settings.sqlite3"
        self.store = SQLiteSettingsStore(self.path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_creates_schema_and_upserts_one_chat(self) -> None:
        self.store.save_confirmed_city(42, candidate("Москва", 55.75, 37.61, "Europe/Moscow"))
        self.store.save_confirmed_city(42, candidate("Сочи", 43.58, 39.72, "Europe/Moscow"))

        self.assertEqual(
            self.store.get_user_settings(42),
            UserSettings(42, "Сочи", 43.58, 39.72, "Europe/Moscow"),
        )
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM user_settings").fetchone()[0],
                1,
            )

    def test_new_schema_has_default_settings(self) -> None:
        with sqlite3.connect(self.path) as connection:
            columns = {
                row[1]: row[4]
                for row in connection.execute("PRAGMA table_info(user_settings)")
            }

        self.assertEqual(columns["daily_send_time"], "'07:00'")
        self.assertEqual(columns["urgent_warnings_enabled"], "1")

        self.store.save_confirmed_city(42, candidate("Москва", 55.75, 37.61, "Europe/Moscow"))
        settings = self.store.get_user_settings(42)
        self.assertEqual(settings.daily_send_time, DAILY_SEND_TIME_DEFAULT)
        self.assertEqual(settings.daily_send_days, DAILY_SEND_DAYS_DEFAULT)
        self.assertIs(settings.urgent_warnings_enabled, URGENT_WARNINGS_ENABLED_DEFAULT)

    def test_new_schema_has_default_daily_send_days(self) -> None:
        with sqlite3.connect(self.path) as connection:
            columns = {
                row[1]: row[4]
                for row in connection.execute("PRAGMA table_info(user_settings)")
            }

        self.assertEqual(columns["daily_send_days"], "'1,2,3,4,5,6,7'")

    def test_current_schema_migrates_days_and_preserves_0830_and_city_data(self) -> None:
        current_path = Path(self.temporary_directory.name) / "current.sqlite3"
        with sqlite3.connect(current_path) as connection:
            connection.execute(
                """
                CREATE TABLE user_settings (
                    telegram_chat_id INTEGER PRIMARY KEY,
                    city_name TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    timezone TEXT NOT NULL,
                    daily_send_time TEXT NOT NULL DEFAULT '07:00',
                    daily_send_days TEXT NOT NULL DEFAULT '1,2,3,4,5,6,7'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO user_settings (
                    telegram_chat_id, city_name, latitude, longitude, timezone,
                    daily_send_time, daily_send_days
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    42,
                    "Москва",
                    55.75204,
                    37.61781,
                    "Europe/Moscow",
                    "08:30",
                    "1,3,5",
                ),
            )

        migrated_store = SQLiteSettingsStore(current_path)
        settings = migrated_store.get_user_settings(42)

        self.assertEqual(settings.city_name, "Москва")
        self.assertEqual(settings.latitude, 55.75204)
        self.assertEqual(settings.longitude, 37.61781)
        self.assertEqual(settings.timezone, "Europe/Moscow")
        self.assertEqual(settings.daily_send_time, "08:30")
        self.assertEqual(settings.daily_send_days, "1,3,5")
        self.assertIs(settings.urgent_warnings_enabled, True)
        with sqlite3.connect(current_path) as connection:
            columns = [
                row[1]
                for row in connection.execute("PRAGMA table_info(user_settings)")
            ]
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM user_settings").fetchone()[0], 1)
        self.assertIn("daily_send_days", columns)
        self.assertIn("urgent_warnings_enabled", columns)

    def test_migration_is_idempotent(self) -> None:
        SQLiteSettingsStore(self.path)
        SQLiteSettingsStore(self.path)

        with sqlite3.connect(self.path) as connection:
            columns = [
                row[1]
                for row in connection.execute("PRAGMA table_info(user_settings)")
            ]
        self.assertEqual(columns.count("daily_send_days"), 1)
        self.assertEqual(columns.count("urgent_warnings_enabled"), 1)

    def test_old_schema_migrates_without_changing_existing_city_data(self) -> None:
        old_path = Path(self.temporary_directory.name) / "old.sqlite3"
        with sqlite3.connect(old_path) as connection:
            connection.execute(
                """
                CREATE TABLE user_settings (
                    telegram_chat_id INTEGER PRIMARY KEY,
                    city_name TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    timezone TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO user_settings (
                    telegram_chat_id, city_name, latitude, longitude, timezone
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (42, "Москва", 55.75204, 37.61781, "Europe/Moscow"),
            )

        migrated_store = SQLiteSettingsStore(old_path)

        self.assertEqual(
            migrated_store.get_user_settings(42),
            UserSettings(42, "Москва", 55.75204, 37.61781, "Europe/Moscow", "07:00"),
        )
        with sqlite3.connect(old_path) as connection:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(user_settings)")
            }
            self.assertIn("daily_send_time", columns)
            self.assertIn("daily_send_days", columns)
            self.assertIn("urgent_warnings_enabled", columns)

    def test_schema_with_days_but_without_time_migrates_remaining_fields(self) -> None:
        old_path = Path(self.temporary_directory.name) / "without-time.sqlite3"
        with sqlite3.connect(old_path) as connection:
            connection.execute(
                """
                CREATE TABLE user_settings (
                    telegram_chat_id INTEGER PRIMARY KEY,
                    city_name TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    timezone TEXT NOT NULL,
                    daily_send_days TEXT NOT NULL DEFAULT '1,2,3,4,5,6,7'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO user_settings (
                    telegram_chat_id, city_name, latitude, longitude, timezone,
                    daily_send_days
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (42, "Москва", 55.75204, 37.61781, "Europe/Moscow", "1,3,5"),
            )

        migrated_store = SQLiteSettingsStore(old_path)
        settings = migrated_store.get_user_settings(42)

        self.assertEqual(settings.daily_send_time, DAILY_SEND_TIME_DEFAULT)
        self.assertEqual(settings.daily_send_days, "1,3,5")
        self.assertIs(settings.urgent_warnings_enabled, True)

    def test_save_daily_send_time_updates_existing_row(self) -> None:
        self.store.save_confirmed_city(42, candidate("Москва", 55.75, 37.61, "Europe/Moscow"))

        self.store.save_daily_send_time(42, " 18:30 ")
        self.store.save_daily_send_time(42, "23:59")

        self.assertEqual(self.store.get_user_settings(42).daily_send_time, "23:59")

    def test_save_daily_send_time_does_not_create_missing_user(self) -> None:
        with self.assertRaises(StorageError):
            self.store.save_daily_send_time(42, "07:00")

        self.assertIsNone(self.store.get_user_settings(42))

    def test_save_daily_send_days_updates_existing_row_and_can_repeat(self) -> None:
        self.store.save_confirmed_city(42, candidate("Москва", 55.75, 37.61, "Europe/Moscow"))
        self.store.save_daily_send_time(42, "08:30")

        self.store.save_daily_send_days(42, "5,1,3")
        self.store.save_daily_send_days(42, "6,7")

        settings = self.store.get_user_settings(42)
        self.assertEqual(settings.daily_send_days, "6,7")
        self.assertEqual(settings.daily_send_time, "08:30")
        self.assertEqual(settings.city_name, "Москва")
        self.assertEqual(settings.latitude, 55.75)
        self.assertEqual(settings.longitude, 37.61)
        self.assertEqual(settings.timezone, "Europe/Moscow")

    def test_save_daily_send_days_does_not_create_missing_user(self) -> None:
        with self.assertRaises(StorageError):
            self.store.save_daily_send_days(42, "1,2")

        self.assertIsNone(self.store.get_user_settings(42))

    def test_get_user_settings_converts_sqlite_zero_and_one_to_bool(self) -> None:
        self.store.save_confirmed_city(42, candidate("Москва", 55.75, 37.61, "Europe/Moscow"))

        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "UPDATE user_settings SET urgent_warnings_enabled = 0 WHERE telegram_chat_id = 42"
            )
        self.assertIs(self.store.get_user_settings(42).urgent_warnings_enabled, False)

        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "UPDATE user_settings SET urgent_warnings_enabled = 1 WHERE telegram_chat_id = 42"
            )
        self.assertIs(self.store.get_user_settings(42).urgent_warnings_enabled, True)

    def test_save_urgent_warnings_enabled_toggles_and_preserves_all_other_fields(self) -> None:
        self.store.save_confirmed_city(42, candidate("Москва", 55.75204, 37.61781, "Europe/Moscow"))
        self.store.save_daily_send_time(42, "08:30")
        self.store.save_daily_send_days(42, "1,3,5")

        self.store.save_urgent_warnings_enabled(42, False)
        self.assertIs(self.store.get_user_settings(42).urgent_warnings_enabled, False)
        self.store.save_urgent_warnings_enabled(42, True)

        self.assertEqual(
            self.store.get_user_settings(42),
            UserSettings(
                42,
                "Москва",
                55.75204,
                37.61781,
                "Europe/Moscow",
                "08:30",
                "1,3,5",
                True,
            ),
        )

    def test_save_urgent_warnings_enabled_does_not_create_missing_user(self) -> None:
        with self.assertRaises(StorageError):
            self.store.save_urgent_warnings_enabled(42, False)

        self.assertIsNone(self.store.get_user_settings(42))

    def test_save_urgent_warnings_enabled_accepts_only_boolean(self) -> None:
        self.store.save_confirmed_city(42, candidate("Москва", 55.75, 37.61, "Europe/Moscow"))

        for value in (0, 1, "Да", None):
            with self.subTest(value=value), self.assertRaises(StorageError):
                self.store.save_urgent_warnings_enabled(42, value)

        self.assertIs(self.store.get_user_settings(42).urgent_warnings_enabled, True)

    def test_save_confirmed_city_preserves_existing_urgent_warnings_setting(self) -> None:
        self.store.save_confirmed_city(42, candidate("Москва", 55.75204, 37.61781, "Europe/Moscow"))
        self.store.save_daily_send_time(42, "08:30")
        self.store.save_daily_send_days(42, "1,3,5")
        self.store.save_urgent_warnings_enabled(42, False)

        self.store.save_confirmed_city(42, candidate("Сочи", 43.58, 39.72, "Europe/Moscow"))

        settings = self.store.get_user_settings(42)
        self.assertEqual(settings.city_name, "Сочи")
        self.assertEqual(settings.daily_send_time, "08:30")
        self.assertEqual(settings.daily_send_days, "1,3,5")
        self.assertIs(settings.urgent_warnings_enabled, False)

    def test_save_confirmed_city_preserves_existing_daily_send_days(self) -> None:
        self.store.save_confirmed_city(42, candidate("Москва", 55.75, 37.61, "Europe/Moscow"))
        self.store.save_daily_send_time(42, "08:30")
        self.store.save_daily_send_days(42, "1,3,5")

        self.store.save_confirmed_city(42, candidate("Сочи", 43.58, 39.72, "Europe/Moscow"))

        settings = self.store.get_user_settings(42)
        self.assertEqual(settings.city_name, "Сочи")
        self.assertEqual(settings.daily_send_time, "08:30")
        self.assertEqual(settings.daily_send_days, "1,3,5")

    def test_save_confirmed_city_preserves_existing_daily_send_time(self) -> None:
        self.store.save_confirmed_city(42, candidate("Москва", 55.75, 37.61, "Europe/Moscow"))
        self.store.save_daily_send_time(42, "18:30")

        self.store.save_confirmed_city(42, candidate("Сочи", 43.58, 39.72, "Europe/Moscow"))

        self.assertEqual(
            self.store.get_user_settings(42),
            UserSettings(42, "Сочи", 43.58, 39.72, "Europe/Moscow", "18:30"),
        )

    def test_different_chats_keep_independent_rows(self) -> None:
        self.store.save_confirmed_city(42, candidate("Москва", 55.75, 37.61, "Europe/Moscow"))
        self.store.save_confirmed_city(43, candidate("Казань", 55.79, 49.12, "Europe/Moscow"))

        self.assertEqual(self.store.get_user_settings(42).city_name, "Москва")
        self.assertEqual(self.store.get_user_settings(43).city_name, "Казань")

    def test_different_chats_keep_independent_daily_send_times(self) -> None:
        self.store.save_confirmed_city(42, candidate("Москва", 55.75, 37.61, "Europe/Moscow"))
        self.store.save_confirmed_city(43, candidate("Казань", 55.79, 49.12, "Europe/Moscow"))

        self.store.save_daily_send_time(42, "00:00")
        self.store.save_daily_send_time(43, "23:59")

        self.assertEqual(self.store.get_user_settings(42).daily_send_time, "00:00")
        self.assertEqual(self.store.get_user_settings(43).daily_send_time, "23:59")

    def test_invalid_storage_time_does_not_change_existing_value(self) -> None:
        self.store.save_confirmed_city(42, candidate("Москва", 55.75, 37.61, "Europe/Moscow"))
        self.store.save_daily_send_time(42, "18:30")

        with self.assertRaises(StorageError):
            self.store.save_daily_send_time(42, "24:00")

        self.assertEqual(self.store.get_user_settings(42).daily_send_time, "18:30")

    def test_invalid_storage_days_do_not_change_existing_value(self) -> None:
        self.store.save_confirmed_city(42, candidate("Москва", 55.75, 37.61, "Europe/Moscow"))
        self.store.save_daily_send_days(42, "6,7")

        with self.assertRaises(StorageError):
            self.store.save_daily_send_days(42, "1,1")

        self.assertEqual(self.store.get_user_settings(42).daily_send_days, "6,7")


class DailySendDaysNormalizationTest(unittest.TestCase):
    def test_valid_values_are_canonicalized(self) -> None:
        for value, expected in (
            ("1,2,3,4,5,6,7", "1,2,3,4,5,6,7"),
            ("1,2,3,4,5", "1,2,3,4,5"),
            ("6,7", "6,7"),
            ("1, 3, 5", "1,3,5"),
            ("5,1,3", "1,3,5"),
        ):
            with self.subTest(value=value):
                self.assertEqual(normalize_daily_send_days(value), expected)

    def test_invalid_values_are_rejected(self) -> None:
        for value in (
            "",
            "   ",
            "0",
            "8",
            "1,8",
            "1,,2",
            "1-5",
            "Пн",
            "abc",
            "/start",
            "/help",
            "1,1",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_daily_send_days(value)


if __name__ == "__main__":
    unittest.main()
