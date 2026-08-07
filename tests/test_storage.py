from pathlib import Path
import sqlite3
import tempfile
import unittest

from weather_alert_bot.geocoding import GeocodingLocation
from weather_alert_bot.storage import (
    DAILY_SEND_TIME_DEFAULT,
    SQLiteSettingsStore,
    StorageError,
    UserSettings,
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

    def test_new_schema_has_default_daily_send_time(self) -> None:
        with sqlite3.connect(self.path) as connection:
            columns = {
                row[1]: row[4]
                for row in connection.execute("PRAGMA table_info(user_settings)")
            }

        self.assertEqual(columns["daily_send_time"], "'07:00'")

        self.store.save_confirmed_city(42, candidate("Москва", 55.75, 37.61, "Europe/Moscow"))
        self.assertEqual(self.store.get_user_settings(42).daily_send_time, DAILY_SEND_TIME_DEFAULT)

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

    def test_save_daily_send_time_updates_existing_row(self) -> None:
        self.store.save_confirmed_city(42, candidate("Москва", 55.75, 37.61, "Europe/Moscow"))

        self.store.save_daily_send_time(42, " 18:30 ")
        self.store.save_daily_send_time(42, "23:59")

        self.assertEqual(self.store.get_user_settings(42).daily_send_time, "23:59")

    def test_save_daily_send_time_does_not_create_missing_user(self) -> None:
        with self.assertRaises(StorageError):
            self.store.save_daily_send_time(42, "07:00")

        self.assertIsNone(self.store.get_user_settings(42))

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


if __name__ == "__main__":
    unittest.main()
