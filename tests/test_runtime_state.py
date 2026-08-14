import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from weather_alert_bot.runtime_state import (
    RuntimeStateError,
    SQLiteRuntimeStateStore,
)


class RuntimeStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "runtime.sqlite3"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_creation_and_missing_state(self) -> None:
        store = SQLiteRuntimeStateStore(self.path)
        self.assertTrue(self.path.exists())
        self.assertIsNone(store.get_daily_delivery_state(42))
        with sqlite3.connect(self.path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertEqual(tables, {"daily_delivery_state"})

    def test_save_read_roundtrip_converts_timestamp_to_utc(self) -> None:
        store = SQLiteRuntimeStateStore(self.path)
        sent_at = datetime(2026, 8, 10, 12, 34, 56, tzinfo=ZoneInfo("Europe/Moscow"))
        store.mark_daily_delivery_success(42, date(2026, 8, 10), sent_at)

        state = store.get_daily_delivery_state(42)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.last_successful_local_date, date(2026, 8, 10))
        self.assertEqual(
            state.last_successful_at_utc,
            datetime(2026, 8, 10, 9, 34, 56, tzinfo=timezone.utc),
        )

    def test_multiple_chat_ids_and_overwrite(self) -> None:
        store = SQLiteRuntimeStateStore(self.path)
        first = datetime(2026, 8, 10, 7, tzinfo=timezone.utc)
        second = datetime(2026, 8, 11, 7, tzinfo=timezone.utc)
        store.mark_daily_delivery_success(42, date(2026, 8, 10), first)
        store.mark_daily_delivery_success(99, date(2026, 8, 10), first)
        store.mark_daily_delivery_success(42, date(2026, 8, 11), second)

        self.assertEqual(
            store.get_daily_delivery_state(42).last_successful_local_date,
            date(2026, 8, 11),
        )
        self.assertEqual(
            store.get_daily_delivery_state(99).last_successful_local_date,
            date(2026, 8, 10),
        )

    def test_invalid_chat_id_is_rejected(self) -> None:
        store = SQLiteRuntimeStateStore(self.path)
        with self.assertRaises(RuntimeStateError):
            store.get_daily_delivery_state(True)  # type: ignore[arg-type]
        with self.assertRaises(RuntimeStateError):
            store.mark_daily_delivery_success("42", date.today(), datetime.now(timezone.utc))  # type: ignore[arg-type]

    def test_naive_sent_at_is_rejected(self) -> None:
        store = SQLiteRuntimeStateStore(self.path)
        with self.assertRaises(RuntimeStateError):
            store.mark_daily_delivery_success(42, date.today(), datetime(2026, 8, 10, 7))

    def test_datetime_local_date_is_rejected(self) -> None:
        store = SQLiteRuntimeStateStore(self.path)
        with self.assertRaises(RuntimeStateError):
            store.mark_daily_delivery_success(
                42,
                datetime(2026, 8, 10, tzinfo=timezone.utc),  # type: ignore[arg-type]
                datetime.now(timezone.utc),
            )

    def test_malformed_stored_date_is_rejected(self) -> None:
        SQLiteRuntimeStateStore(self.path)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO daily_delivery_state VALUES (?, ?, ?)",
                (42, "not-a-date", "2026-08-10T07:00:00+00:00"),
            )
        with self.assertRaises(RuntimeStateError):
            SQLiteRuntimeStateStore(self.path).get_daily_delivery_state(42)

    def test_malformed_stored_timestamp_is_rejected(self) -> None:
        SQLiteRuntimeStateStore(self.path)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO daily_delivery_state VALUES (?, ?, ?)",
                (42, "2026-08-10", "not-a-timestamp"),
            )
        with self.assertRaises(RuntimeStateError):
            SQLiteRuntimeStateStore(self.path).get_daily_delivery_state(42)

    def test_naive_stored_timestamp_is_rejected(self) -> None:
        SQLiteRuntimeStateStore(self.path)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO daily_delivery_state VALUES (?, ?, ?)",
                (42, "2026-08-10", "2026-08-10T07:00:00"),
            )
        with self.assertRaises(RuntimeStateError):
            SQLiteRuntimeStateStore(self.path).get_daily_delivery_state(42)

    def test_read_only_store_reads_existing_state(self) -> None:
        writable = SQLiteRuntimeStateStore(self.path)
        writable.mark_daily_delivery_success(42, date(2026, 8, 10), datetime.now(timezone.utc))
        read_only = SQLiteRuntimeStateStore(self.path, read_only=True)
        self.assertIsNotNone(read_only.get_daily_delivery_state(42))


if __name__ == "__main__":
    unittest.main()
