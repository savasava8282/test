from pathlib import Path
import sqlite3
import tempfile
import unittest

from weather_alert_bot.geocoding import GeocodingLocation
from weather_alert_bot.storage import SQLiteSettingsStore, UserSettings


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

    def test_different_chats_keep_independent_rows(self) -> None:
        self.store.save_confirmed_city(42, candidate("Москва", 55.75, 37.61, "Europe/Moscow"))
        self.store.save_confirmed_city(43, candidate("Казань", 55.79, 49.12, "Europe/Moscow"))

        self.assertEqual(self.store.get_user_settings(42).city_name, "Москва")
        self.assertEqual(self.store.get_user_settings(43).city_name, "Казань")


if __name__ == "__main__":
    unittest.main()
