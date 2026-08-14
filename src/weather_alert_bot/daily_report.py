from __future__ import annotations

from datetime import datetime
import sys
from collections.abc import Callable
from typing import Protocol

from weather_alert_bot.climate_cache import (
    ClimateCacheError,
    SQLiteClimateNormalsCache,
    get_or_create_climate_normals,
)
from weather_alert_bot.climate_normals import (
    ClimateNormalsError,
    OpenMeteoHistoricalWeatherClient,
    get_climate_normal_for_date,
    local_calendar_date,
)
from weather_alert_bot.daily_summary import (
    DailySummaryError,
    build_daily_summary,
    format_daily_risk_section,
    format_daily_summary,
)
from weather_alert_bot.geomagnetic_forecast import (
    GeomagneticForecast,
    NoaaSwpcGeomagneticClient,
)
from weather_alert_bot.risk_assessment import RiskAssessmentError, assess_current_day_risks
from weather_alert_bot.storage import UserSettings
from weather_alert_bot.weather_forecast import OpenMeteoWeatherClient, WeatherForecast


CLIMATE_FALLBACK_DIAGNOSTIC = (
    "Климатическая норма недоступна; жара и холод временно не оценены."
)


class DailyReportError(RuntimeError):
    """Raised when the shared production daily report cannot be built."""


class WeatherFetcher(Protocol):
    def fetch(self, latitude: float, longitude: float, timezone: str) -> WeatherForecast: ...


class GeomagneticFetcher(Protocol):
    def fetch(self) -> GeomagneticForecast: ...


def build_production_daily_report(
    *,
    owner: UserSettings,
    weather_client: OpenMeteoWeatherClient | WeatherFetcher,
    geomagnetic_client: NoaaSwpcGeomagneticClient | GeomagneticFetcher,
    climate_cache: SQLiteClimateNormalsCache,
    historical_client: OpenMeteoHistoricalWeatherClient,
    formed_at: datetime,
    summary_builder: Callable | None = None,
    risk_assessor: Callable | None = None,
) -> str:
    """Build the one production report shared by manual and scheduled delivery."""
    if summary_builder is None:
        summary_builder = build_daily_summary
    if risk_assessor is None:
        risk_assessor = assess_current_day_risks

    weather = weather_client.fetch(
        owner.latitude,
        owner.longitude,
        owner.timezone,
    )
    geomagnetic = geomagnetic_client.fetch()
    summary = summary_builder(owner, weather, geomagnetic, formed_at)

    climate_normal = None
    try:
        normals = get_or_create_climate_normals(
            climate_cache,
            historical_client,
            owner.latitude,
            owner.longitude,
            owner.timezone,
            formed_at,
        )
        target_date = local_calendar_date(formed_at, owner.timezone)
        climate_normal = get_climate_normal_for_date(normals, target_date)
    except (ClimateCacheError, ClimateNormalsError):
        print(CLIMATE_FALLBACK_DIAGNOSTIC, file=sys.stderr)

    assessment = risk_assessor(
        weather,
        geomagnetic,
        owner.timezone,
        formed_at,
        climate_normal=climate_normal,
    )
    risk_section = format_daily_risk_section(assessment, owner)
    return format_daily_summary(summary, risk_section=risk_section)
