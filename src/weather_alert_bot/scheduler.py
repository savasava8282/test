from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import sys
from threading import Event
from typing import Literal, Protocol

from weather_alert_bot.climate_cache import SQLiteClimateNormalsCache
from weather_alert_bot.climate_normals import OpenMeteoHistoricalWeatherClient
from weather_alert_bot.daily_dispatch import (
    DailyDispatchError,
    DailyDispatchResult,
    run_daily_dispatch_once,
)
from weather_alert_bot.geomagnetic_forecast import NoaaSwpcGeomagneticClient
from weather_alert_bot.runtime_state import SQLiteRuntimeStateStore
from weather_alert_bot.storage import StorageError, UserSettings
from weather_alert_bot.telegram_api import TelegramClient
from weather_alert_bot.weather_forecast import OpenMeteoWeatherClient


SCHEDULER_ERROR_DIAGNOSTIC = (
    "Ошибка планового запуска; следующая попытка будет выполнена позже."
)
SCHEDULED_REPORT_SENT_DIAGNOSTIC = "Ежедневная сводка отправлена по расписанию."


class SchedulerTickError(RuntimeError):
    """Raised when scheduler orchestration receives an invalid clock value."""


SchedulerTickStatus = Literal["sent", "not_due", "already_sent", "failed"]


@dataclass(frozen=True, slots=True)
class SchedulerTickResult:
    """Safe outcome of one scheduler invocation."""

    status: SchedulerTickStatus
    dispatch_result: DailyDispatchResult | None = None


class SettingsReader(Protocol):
    def get_single_user_settings(self) -> UserSettings | None: ...


Waiter = Callable[[Event, float], bool]
Now = Callable[[], datetime]
Emitter = Callable[[str], None]


def _require_aware_utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise SchedulerTickError("Время scheduler должно быть aware datetime в UTC.")
    if value.utcoffset() != timedelta(0):
        raise SchedulerTickError("Время scheduler должно быть указано в UTC.")
    return value.astimezone(timezone.utc)


def next_utc_minute_boundary(current_time: datetime) -> datetime:
    """Return the first future UTC minute boundary after ``current_time``."""
    current_time = _require_aware_utc(current_time)
    truncated = current_time.replace(second=0, microsecond=0)
    return truncated + timedelta(minutes=1)


def seconds_until_next_utc_minute(current_time: datetime) -> float:
    """Return the positive delay from now until the next UTC minute boundary."""
    current_time = _require_aware_utc(current_time)
    return (next_utc_minute_boundary(current_time) - current_time).total_seconds()


def wait_for_stop_or_timeout(stop_event: Event, timeout: float) -> bool:
    """Wait interruptibly and report whether the stop event was set."""
    return stop_event.wait(timeout)


def wait_until_next_utc_minute(
    current_time: datetime,
    stop_event: Event,
    *,
    waiter: Waiter = wait_for_stop_or_timeout,
) -> bool:
    """Wait until the next UTC boundary, or return early when stopping."""
    return waiter(stop_event, seconds_until_next_utc_minute(current_time))


def run_scheduler_tick(
    *,
    settings_store: SettingsReader,
    runtime_state: SQLiteRuntimeStateStore,
    weather_client: OpenMeteoWeatherClient,
    geomagnetic_client: NoaaSwpcGeomagneticClient,
    climate_cache: SQLiteClimateNormalsCache,
    historical_client: OpenMeteoHistoricalWeatherClient,
    telegram_client: TelegramClient,
    current_time: datetime,
) -> SchedulerTickResult:
    """Read current settings and run exactly one existing daily dispatch tick."""
    current_time = _require_aware_utc(current_time)
    try:
        owner = settings_store.get_single_user_settings()
        if owner is None:
            return SchedulerTickResult("failed")

        dispatch_result = run_daily_dispatch_once(
            owner=owner,
            runtime_state=runtime_state,
            weather_client=weather_client,
            geomagnetic_client=geomagnetic_client,
            climate_cache=climate_cache,
            historical_client=historical_client,
            telegram_client=telegram_client,
            current_time=current_time,
        )
    except (StorageError, DailyDispatchError):
        return SchedulerTickResult("failed")
    except Exception:
        # Provider, SQLite and injected dependency failures must not escape one tick.
        return SchedulerTickResult("failed")

    return SchedulerTickResult(dispatch_result.status, dispatch_result)


def _emit_tick_result(
    result: SchedulerTickResult,
    *,
    emit: Emitter,
    error_emit: Emitter,
) -> None:
    if result.status == "sent":
        emit(SCHEDULED_REPORT_SENT_DIAGNOSTIC)
    elif result.status == "failed":
        error_emit(SCHEDULER_ERROR_DIAGNOSTIC)


def run_scheduler_loop(
    *,
    settings_store: SettingsReader,
    runtime_state: SQLiteRuntimeStateStore,
    weather_client: OpenMeteoWeatherClient,
    geomagnetic_client: NoaaSwpcGeomagneticClient,
    climate_cache: SQLiteClimateNormalsCache,
    historical_client: OpenMeteoHistoricalWeatherClient,
    telegram_client: TelegramClient,
    stop_event: Event | None = None,
    now: Now | None = None,
    waiter: Waiter = wait_for_stop_or_timeout,
    emit: Emitter = print,
    error_emit: Emitter | None = None,
) -> None:
    """Run the sequential permanent scheduler with an immediate first tick."""
    if stop_event is None:
        stop_event = Event()
    if now is None:
        now = lambda: datetime.now(timezone.utc)
    if error_emit is None:
        error_emit = lambda message: print(message, file=sys.stderr)

    try:
        while not stop_event.is_set():
            current_time = _require_aware_utc(now())
            result = run_scheduler_tick(
                settings_store=settings_store,
                runtime_state=runtime_state,
                weather_client=weather_client,
                geomagnetic_client=geomagnetic_client,
                climate_cache=climate_cache,
                historical_client=historical_client,
                telegram_client=telegram_client,
                current_time=current_time,
            )
            _emit_tick_result(result, emit=emit, error_emit=error_emit)

            if stop_event.is_set():
                break
            completed_at = _require_aware_utc(now())
            if wait_until_next_utc_minute(
                completed_at,
                stop_event,
                waiter=waiter,
            ):
                break
    except KeyboardInterrupt:
        stop_event.set()
