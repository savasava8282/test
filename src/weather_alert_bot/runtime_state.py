from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote


class RuntimeStateError(RuntimeError):
    """Raised when scheduled-delivery state cannot be used safely."""


@dataclass(frozen=True, slots=True)
class DailyDeliveryState:
    telegram_chat_id: int
    last_successful_local_date: date | None
    last_successful_at_utc: datetime | None


class SQLiteRuntimeStateStore:
    """Small separate SQLite store for operational scheduled-delivery state."""

    _TABLE_SCHEMA = """
        CREATE TABLE IF NOT EXISTS daily_delivery_state (
            telegram_chat_id INTEGER PRIMARY KEY,
            last_successful_local_date TEXT,
            last_successful_at_utc TEXT
        )
    """

    def __init__(self, path: Path | str, *, read_only: bool = False) -> None:
        self.path = Path(path).expanduser()
        self._read_only = read_only
        try:
            if self._read_only:
                with self._connect() as connection:
                    connection.execute("SELECT 1 FROM daily_delivery_state").fetchone()
                return

            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute(self._TABLE_SCHEMA)
        except (OSError, sqlite3.Error) as exc:
            raise RuntimeStateError("Не удалось инициализировать operational state.") from exc

    def _connect(self) -> sqlite3.Connection:
        if not self._read_only:
            return sqlite3.connect(self.path)
        database_uri = f"file:{quote(str(self.path.resolve()), safe='/')}?mode=ro"
        return sqlite3.connect(database_uri, uri=True)

    @staticmethod
    def _validate_chat_id(telegram_chat_id: int) -> int:
        if isinstance(telegram_chat_id, bool) or not isinstance(telegram_chat_id, int):
            raise RuntimeStateError("Telegram chat ID имеет недопустимый тип.")
        return telegram_chat_id

    @staticmethod
    def _validate_local_date(value: date) -> date:
        if isinstance(value, datetime) or not isinstance(value, date):
            raise RuntimeStateError("Локальная дата delivery имеет недопустимый тип.")
        return value

    @staticmethod
    def _validate_aware_datetime(value: datetime) -> datetime:
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise RuntimeStateError("Время delivery должно быть aware datetime.")
        return value

    def get_daily_delivery_state(
        self,
        telegram_chat_id: int,
    ) -> DailyDeliveryState | None:
        chat_id = self._validate_chat_id(telegram_chat_id)
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT telegram_chat_id, last_successful_local_date,
                           last_successful_at_utc
                    FROM daily_delivery_state
                    WHERE telegram_chat_id = ?
                    """,
                    (chat_id,),
                ).fetchone()
        except (OSError, sqlite3.Error) as exc:
            raise RuntimeStateError("Не удалось прочитать operational state.") from exc

        if row is None:
            return None
        stored_chat_id, stored_date, stored_timestamp = row
        if (
            isinstance(stored_chat_id, bool)
            or not isinstance(stored_chat_id, int)
            or stored_chat_id != chat_id
        ):
            raise RuntimeStateError("Operational state содержит некорректный chat ID.")
        if (stored_date is None) != (stored_timestamp is None):
            raise RuntimeStateError("Operational state содержит неполную delivery запись.")

        parsed_date: date | None = None
        parsed_timestamp: datetime | None = None
        if stored_date is not None:
            if not isinstance(stored_date, str):
                raise RuntimeStateError("Operational state содержит некорректную дату.")
            try:
                parsed_date = date.fromisoformat(stored_date)
            except ValueError as exc:
                raise RuntimeStateError("Operational state содержит некорректную дату.") from exc
        if stored_timestamp is not None:
            if not isinstance(stored_timestamp, str):
                raise RuntimeStateError("Operational state содержит некорректное время.")
            try:
                parsed_timestamp = datetime.fromisoformat(stored_timestamp)
            except ValueError as exc:
                raise RuntimeStateError("Operational state содержит некорректное время.") from exc
            self._validate_aware_datetime(parsed_timestamp)
            parsed_timestamp = parsed_timestamp.astimezone(timezone.utc)

        return DailyDeliveryState(
            telegram_chat_id=chat_id,
            last_successful_local_date=parsed_date,
            last_successful_at_utc=parsed_timestamp,
        )

    def mark_daily_delivery_success(
        self,
        telegram_chat_id: int,
        local_date: date,
        sent_at: datetime,
    ) -> None:
        chat_id = self._validate_chat_id(telegram_chat_id)
        valid_date = self._validate_local_date(local_date)
        valid_sent_at = self._validate_aware_datetime(sent_at)
        timestamp = valid_sent_at.astimezone(timezone.utc).isoformat()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO daily_delivery_state (
                        telegram_chat_id, last_successful_local_date,
                        last_successful_at_utc
                    ) VALUES (?, ?, ?)
                    ON CONFLICT(telegram_chat_id) DO UPDATE SET
                        last_successful_local_date = excluded.last_successful_local_date,
                        last_successful_at_utc = excluded.last_successful_at_utc
                    """,
                    (chat_id, valid_date.isoformat(), timestamp),
                )
        except (OSError, sqlite3.Error) as exc:
            raise RuntimeStateError("Не удалось сохранить scheduled delivery state.") from exc
