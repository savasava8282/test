from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from weather_alert_bot.daily_report import build_production_daily_report
from weather_alert_bot.geomagnetic_forecast import (
    GeomagneticForecastError,
    NoaaSwpcGeomagneticClient,
)
from weather_alert_bot.runtime_state import (
    DailyDeliveryState,
    RuntimeStateError,
    SQLiteRuntimeStateStore,
)
from weather_alert_bot.storage import (
    UserSettings,
    normalize_daily_send_days,
    normalize_daily_send_time,
)
from weather_alert_bot.telegram_api import TelegramApiError, TelegramClient
from weather_alert_bot.weather_forecast import OpenMeteoWeatherClient, WeatherForecastError
from weather_alert_bot.climate_cache import SQLiteClimateNormalsCache
from weather_alert_bot.climate_normals import OpenMeteoHistoricalWeatherClient
from weather_alert_bot.daily_summary import DailySummaryError
from weather_alert_bot.risk_assessment import RiskAssessmentError


DispatchStatus = Literal["due", "not_due", "already_sent", "sent"]


class DailyDispatchError(RuntimeError):
    """Raised when a scheduled dispatch tick cannot complete safely."""


@dataclass(frozen=True, slots=True)
class DailyDispatchDecision:
    status: Literal["due", "not_due", "already_sent"]
    local_date: date
    local_time: str
    reason: str


@dataclass(frozen=True, slots=True)
class DailyDispatchResult:
    status: DispatchStatus
    local_date: date
    report_text: str | None = None


def _validate_current_time(current_time: datetime) -> None:
    if (
        not isinstance(current_time, datetime)
        or current_time.tzinfo is None
        or current_time.utcoffset() is None
    ):
        raise DailyDispatchError("Время dispatch должно быть aware datetime.")


def _localize(current_time: datetime, timezone_name: str) -> datetime:
    try:
        return current_time.astimezone(ZoneInfo(timezone_name))
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        raise DailyDispatchError("Некорректный часовой пояс расписания.") from None


def _validate_schedule(settings: UserSettings) -> tuple[str, str]:
    try:
        normalized_time = normalize_daily_send_time(settings.daily_send_time)
        normalized_days = normalize_daily_send_days(settings.daily_send_days)
    except (TypeError, ValueError) as exc:
        raise DailyDispatchError("Сохранённое расписание имеет некорректный формат.") from exc
    if normalized_time != settings.daily_send_time or normalized_days != settings.daily_send_days:
        raise DailyDispatchError("Сохранённое расписание имеет некорректный формат.")
    return normalized_time, normalized_days


def evaluate_daily_dispatch_due(
    settings: UserSettings,
    current_time: datetime,
    last_successful_local_date: date | None,
) -> DailyDispatchDecision:
    """Evaluate exact-minute scheduled delivery in the user's local timezone."""
    if not isinstance(settings, UserSettings):
        raise DailyDispatchError("Настройки scheduled dispatch имеют недопустимый тип.")
    _validate_current_time(current_time)
    if last_successful_local_date is not None and (
        isinstance(last_successful_local_date, datetime)
        or not isinstance(last_successful_local_date, date)
    ):
        raise DailyDispatchError("Дата последней scheduled delivery имеет недопустимый тип.")
    configured_time, configured_days = _validate_schedule(settings)
    local_time = _localize(current_time, settings.timezone)
    local_date = local_time.date()
    local_hhmm = local_time.strftime("%H:%M")

    if not settings.onboarding_completed:
        return DailyDispatchDecision("not_due", local_date, local_hhmm, "onboarding_incomplete")
    if not settings.daily_sending_enabled:
        return DailyDispatchDecision("not_due", local_date, local_hhmm, "daily_sending_disabled")
    if str(local_time.isoweekday()) not in configured_days.split(","):
        return DailyDispatchDecision("not_due", local_date, local_hhmm, "weekday_not_selected")
    if local_hhmm != configured_time:
        return DailyDispatchDecision("not_due", local_date, local_hhmm, "minute_mismatch")
    if last_successful_local_date == local_date:
        return DailyDispatchDecision("already_sent", local_date, local_hhmm, "already_sent")
    return DailyDispatchDecision("due", local_date, local_hhmm, "scheduled_minute")


def run_daily_dispatch_once(
    *,
    owner: UserSettings,
    runtime_state: SQLiteRuntimeStateStore,
    weather_client: OpenMeteoWeatherClient,
    geomagnetic_client: NoaaSwpcGeomagneticClient,
    climate_cache: SQLiteClimateNormalsCache,
    historical_client: OpenMeteoHistoricalWeatherClient,
    telegram_client: TelegramClient,
    current_time: datetime,
) -> DailyDispatchResult:
    """Run exactly one scheduled tick; never polls or sleeps."""
    try:
        state: DailyDeliveryState | None = runtime_state.get_daily_delivery_state(
            owner.telegram_chat_id
        )
        decision = evaluate_daily_dispatch_due(
            owner,
            current_time,
            None if state is None else state.last_successful_local_date,
        )
    except (DailyDispatchError, RuntimeStateError) as exc:
        if isinstance(exc, DailyDispatchError):
            raise
        raise DailyDispatchError("Ошибка чтения состояния scheduled delivery.") from exc

    if decision.status != "due":
        return DailyDispatchResult(decision.status, decision.local_date)

    try:
        report_text = build_production_daily_report(
            owner=owner,
            weather_client=weather_client,
            geomagnetic_client=geomagnetic_client,
            climate_cache=climate_cache,
            historical_client=historical_client,
            formed_at=current_time,
        )
    except (
        WeatherForecastError,
        GeomagneticForecastError,
        DailySummaryError,
        RiskAssessmentError,
    ) as exc:
        raise DailyDispatchError("Не удалось сформировать ежедневную сводку.") from exc

    try:
        telegram_client.send_message(chat_id=owner.telegram_chat_id, text=report_text)
    except TelegramApiError as exc:
        raise DailyDispatchError("Не удалось отправить ежедневную сводку Telegram.") from exc

    try:
        runtime_state.mark_daily_delivery_success(
            owner.telegram_chat_id,
            decision.local_date,
            current_time,
        )
    except RuntimeStateError as exc:
        raise DailyDispatchError(
            "Сводка отправлена, но scheduled delivery не удалось безопасно записать."
        ) from exc
    return DailyDispatchResult("sent", decision.local_date, report_text)
