from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from weather_alert_bot.climate_normals import ClimateNormalDay
from weather_alert_bot.geomagnetic_forecast import GeomagneticForecast
from weather_alert_bot.weather_forecast import WeatherForecast


RISK_CATEGORY_ORDER: tuple[str, ...] = (
    "magnetic_storm",
    "heat",
    "cold",
    "ice",
    "heavy_rain",
    "thunderstorm",
    "strong_wind",
    "storm",
)
UNSUPPORTED_CATEGORIES: tuple[str, ...] = ("heat", "cold")

# The mapping is intentionally based on lower bounds.  It must not round a
# fractional Kp value up to the next G level.
KP_TO_G_LEVEL: tuple[tuple[float, str], ...] = (
    (5.0, "G1"),
    (6.0, "G2"),
    (7.0, "G3"),
    (8.0, "G4"),
    (9.0, "G5"),
)
_THUNDERSTORM_WMO_CODES = frozenset((95, 96, 99))
_FREEZING_DRIZZLE_WMO_CODES = frozenset((56, 57))
_FREEZING_RAIN_WMO_CODES = frozenset((66, 67))


class RiskAssessmentError(RuntimeError):
    """Raised when current-day risk assessment inputs are unsafe to use."""


@dataclass(frozen=True, slots=True)
class RiskAssessmentPolicy:
    """Immutable technical thresholds for the base risk detectors."""

    magnetic_kp_threshold: float = 7.0
    heavy_rain_daily_mm: float = 30.0
    heavy_rain_hourly_mm: float = 15.0
    strong_wind_gust_kmh: float = 72.0
    storm_gust_kmh: float = 90.0
    heat_deviation_c: float = 7.0
    cold_deviation_c: float = 7.0

    def __post_init__(self) -> None:
        fields = (
            ("magnetic_kp_threshold", self.magnetic_kp_threshold, 0.0, 9.0),
            ("heavy_rain_daily_mm", self.heavy_rain_daily_mm, 0.0, None),
            ("heavy_rain_hourly_mm", self.heavy_rain_hourly_mm, 0.0, None),
            ("strong_wind_gust_kmh", self.strong_wind_gust_kmh, 0.0, None),
            ("storm_gust_kmh", self.storm_gust_kmh, 0.0, None),
        )
        for name, value, minimum, maximum in fields:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < minimum
                or (maximum is not None and float(value) > maximum)
            ):
                raise RiskAssessmentError(f"Некорректный порог policy: {name}.")
        for name, value in (
            ("heat_deviation_c", self.heat_deviation_c),
            ("cold_deviation_c", self.cold_deviation_c),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0.0
            ):
                raise RiskAssessmentError(f"Некорректный порог policy: {name}.")


@dataclass(frozen=True, slots=True)
class RiskSignal:
    """One deterministic physical risk signal."""

    category: str
    reason: str
    value: float | None = None


@dataclass(frozen=True, slots=True)
class CurrentDayRiskAssessment:
    """Structured assessment for one local calendar day."""

    local_date: date
    signals: tuple[RiskSignal, ...]
    unsupported_categories: tuple[str, ...] = ()


def g_level_for_kp(kp: float) -> str | None:
    """Return the NOAA G level for Kp, without rounding fractional values."""
    for lower_bound, level in reversed(KP_TO_G_LEVEL):
        if kp >= lower_bound:
            return level
    return None


def assess_current_day_risks(
    weather: WeatherForecast,
    geomagnetic: GeomagneticForecast,
    timezone_name: str,
    formation_time: datetime,
    policy: RiskAssessmentPolicy | None = None,
    climate_normal: ClimateNormalDay | None = None,
) -> CurrentDayRiskAssessment:
    """Assess supported current-day risks using only supplied parsed data."""
    local_zone = _load_timezone(timezone_name)
    if (
        not isinstance(formation_time, datetime)
        or formation_time.tzinfo is None
        or formation_time.utcoffset() is None
    ):
        raise RiskAssessmentError("Время формирования должно быть aware datetime.")
    local_date = formation_time.astimezone(local_zone).date()
    active_policy = policy if policy is not None else RiskAssessmentPolicy()
    if not isinstance(active_policy, RiskAssessmentPolicy):
        raise RiskAssessmentError("Policy оценки рисков имеет недопустимый тип.")
    if climate_normal is not None:
        _validate_climate_normal(climate_normal, local_date)

    local_hourly = tuple(
        item
        for item in weather.hourly
        if _weather_local_timestamp(item.time, weather.timezone, local_zone).date()
        == local_date
    )
    daily = next((item for item in weather.daily if item.date == local_date), None)
    if climate_normal is not None and daily is None:
        raise RiskAssessmentError(
            "Текущий день отсутствует в daily-прогнозе для оценки жары и холода."
        )

    evidence: dict[str, RiskSignal] = {}

    local_geomagnetic = tuple(
        item
        for item in geomagnetic.intervals
        if item.status in {"observed", "estimated", "predicted"}
        and _geomagnetic_local_timestamp(item.timestamp, local_zone).date()
        == local_date
    )
    if local_geomagnetic:
        maximum_kp = max(item.kp for item in local_geomagnetic)
        if maximum_kp >= active_policy.magnetic_kp_threshold:
            g_level = g_level_for_kp(maximum_kp)
            level_text = f" ({g_level})" if g_level is not None else ""
            evidence["magnetic_storm"] = RiskSignal(
                category="magnetic_storm",
                reason=(
                    f"Максимальный Kp за текущий местный день: "
                    f"{_number(maximum_kp)}{level_text}; "
                    f"порог Kp {_number(active_policy.magnetic_kp_threshold)}."
                ),
                value=maximum_kp,
            )

    if climate_normal is not None and daily is not None:
        heat_deviation = daily.temperature_2m_max - climate_normal.normal_temperature_max
        if heat_deviation >= active_policy.heat_deviation_c:
            evidence["heat"] = RiskSignal(
                category="heat",
                reason=(
                    f"Прогнозируемый максимум {_temperature_one_decimal(daily.temperature_2m_max)} °C, "
                    f"климатическая норма {_temperature_one_decimal(climate_normal.normal_temperature_max)} °C: "
                    f"выше нормы на {_number_one_decimal(heat_deviation)} °C; "
                    f"порог {_number_one_decimal(active_policy.heat_deviation_c)} °C."
                ),
                value=heat_deviation,
            )

        cold_deviation = daily.temperature_2m_min - climate_normal.normal_temperature_min
        if cold_deviation <= -active_policy.cold_deviation_c:
            evidence["cold"] = RiskSignal(
                category="cold",
                reason=(
                    f"Прогнозируемый минимум {_temperature_one_decimal(daily.temperature_2m_min)} °C, "
                    f"климатическая норма {_temperature_one_decimal(climate_normal.normal_temperature_min)} °C: "
                    f"ниже нормы на {_number_one_decimal(-cold_deviation)} °C; "
                    f"порог {_number_one_decimal(active_policy.cold_deviation_c)} °C."
                ),
                value=cold_deviation,
            )

    if daily is not None and daily.precipitation_sum >= active_policy.heavy_rain_daily_mm:
        evidence["heavy_rain"] = RiskSignal(
            category="heavy_rain",
            reason=(
                f"Суточные осадки: {_number(daily.precipitation_sum)} мм; "
                f"порог {_number(active_policy.heavy_rain_daily_mm)} мм."
            ),
            value=daily.precipitation_sum,
        )
    else:
        hourly_rain = max(
            (item.precipitation for item in local_hourly),
            default=0.0,
        )
        if hourly_rain >= active_policy.heavy_rain_hourly_mm:
            evidence["heavy_rain"] = RiskSignal(
                category="heavy_rain",
                reason=(
                    f"Часовые осадки: {_number(hourly_rain)} мм/ч; "
                    f"порог {_number(active_policy.heavy_rain_hourly_mm)} мм/ч."
                ),
                value=hourly_rain,
            )

    if local_hourly:
        thunderstorm = min(
            (item for item in local_hourly if item.weather_code in _THUNDERSTORM_WMO_CODES),
            key=lambda item: (
                _weather_local_timestamp(item.time, weather.timezone, local_zone),
                item.weather_code,
            ),
            default=None,
        )
        if thunderstorm is not None:
            evidence["thunderstorm"] = RiskSignal(
                category="thunderstorm",
                reason=(
                    f"В почасовом прогнозе присутствует WMO-код "
                    f"{thunderstorm.weather_code}, соответствующий грозе."
                ),
                value=float(thunderstorm.weather_code),
            )

        ice_candidates: list[tuple[datetime, int, str, float | None]] = []
        for item in local_hourly:
            timestamp = _weather_local_timestamp(item.time, weather.timezone, local_zone)
            if item.weather_code in _FREEZING_DRIZZLE_WMO_CODES:
                ice_candidates.append(
                    (timestamp, 0, f"WMO-код {item.weather_code}: переохлаждённая морось", None)
                )
            elif item.weather_code in _FREEZING_RAIN_WMO_CODES:
                ice_candidates.append(
                    (timestamp, 1, f"WMO-код {item.weather_code}: переохлаждённый дождь", None)
                )
            elif item.precipitation > 0 and item.temperature_2m < 0:
                ice_candidates.append(
                    (
                        timestamp,
                        2,
                        (
                            f"осадки {_number(item.precipitation)} мм/ч при "
                            f"температуре {_temperature(item.temperature_2m)} °C"
                        ),
                        item.precipitation,
                    )
                )
        if ice_candidates:
            _, _, description, value = min(ice_candidates, key=lambda candidate: candidate[:2])
            evidence["ice"] = RiskSignal(
                category="ice",
                reason=(
                    f"Риск условий для гололёда/обледенения: {description}. "
                    "Это не подтверждает состояние поверхности."
                ),
                value=value,
            )

    gust_values = [item.wind_gusts_10m for item in local_hourly]
    if daily is not None:
        gust_values.append(daily.wind_gusts_10m_max)
    maximum_gust = max(gust_values, default=0.0)
    if maximum_gust >= active_policy.strong_wind_gust_kmh:
        evidence["strong_wind"] = RiskSignal(
            category="strong_wind",
            reason=(
                f"Максимальный порыв: {_number(maximum_gust)} км/ч; "
                f"порог {_number(active_policy.strong_wind_gust_kmh)} км/ч "
                "(20 м/с = 72 км/ч)."
            ),
            value=maximum_gust,
        )
    if maximum_gust >= active_policy.storm_gust_kmh:
        evidence["storm"] = RiskSignal(
            category="storm",
            reason=(
                f"Максимальный порыв: {_number(maximum_gust)} км/ч; "
                f"численный порог шторма {_number(active_policy.storm_gust_kmh)} км/ч "
                "(25 м/с = 90 км/ч). Официальные regional warnings не подключены."
            ),
            value=maximum_gust,
        )

    return CurrentDayRiskAssessment(
        local_date=local_date,
        signals=tuple(evidence[category] for category in RISK_CATEGORY_ORDER if category in evidence),
        unsupported_categories=() if climate_normal is not None else UNSUPPORTED_CATEGORIES,
    )


def format_current_day_risk_assessment(
    assessment: CurrentDayRiskAssessment,
) -> str:
    """Format a stable diagnostic preview, not a Telegram user message."""
    lines = [
        f"Дата: {assessment.local_date:%d.%m.%Y}",
        "",
        "Риски по подключённым категориям:",
    ]
    if assessment.signals:
        lines.extend(f"- {signal.category}: {signal.reason}" for signal in assessment.signals)
    else:
        lines.append("значимых не выявлено.")
    if assessment.unsupported_categories:
        display_names = {
            "heat": "жара",
            "cold": "холод",
        }
        unsupported = ", ".join(
            display_names.get(category, category)
            for category in assessment.unsupported_categories
        )
        lines.extend(("", f"Не оцениваются на этом этапе: {unsupported}"))
    return "\n".join(lines)


def _validate_climate_normal(
    climate_normal: ClimateNormalDay,
    local_date: date,
) -> None:
    if not isinstance(climate_normal, ClimateNormalDay):
        raise RiskAssessmentError("Климатическая норма имеет недопустимый тип.")
    if (
        type(climate_normal.month) is not int
        or type(climate_normal.day) is not int
        or (climate_normal.month, climate_normal.day) != (local_date.month, local_date.day)
    ):
        raise RiskAssessmentError(
            "Климатическая норма не соответствует текущей календарной дате."
        )
    for name, value in (
        ("normal_temperature_min", climate_normal.normal_temperature_min),
        ("normal_temperature_max", climate_normal.normal_temperature_max),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise RiskAssessmentError(f"Некорректное значение климатической нормы: {name}.")
    if climate_normal.normal_temperature_min > climate_normal.normal_temperature_max:
        raise RiskAssessmentError(
            "Климатическая норма содержит minimum выше maximum."
        )
    if type(climate_normal.sample_count) is not int or climate_normal.sample_count <= 0:
        raise RiskAssessmentError(
            "Климатическая норма содержит некорректное число наблюдений."
        )


def _load_timezone(timezone_name: str) -> ZoneInfo:
    if not isinstance(timezone_name, str) or not timezone_name.strip():
        raise RiskAssessmentError("Некорректный часовой пояс города.")
    try:
        return ZoneInfo(timezone_name.strip())
    except (ZoneInfoNotFoundError, ValueError):
        raise RiskAssessmentError("Некорректный часовой пояс города.") from None


def _weather_local_timestamp(
    timestamp: datetime,
    source_timezone: str,
    local_zone: ZoneInfo,
) -> datetime:
    if timestamp.tzinfo is None:
        source_zone = _load_timezone(source_timezone)
        return timestamp.replace(tzinfo=source_zone).astimezone(local_zone)
    return timestamp.astimezone(local_zone)


def _geomagnetic_local_timestamp(timestamp: datetime, local_zone: ZoneInfo) -> datetime:
    # NOAA time_tag values in the existing parsed model are UTC when naive.
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc).astimezone(local_zone)
    return timestamp.astimezone(local_zone)


def _number(value: float) -> str:
    return f"{value:g}"


def _temperature(value: float) -> str:
    return _number(value).replace("-", "−")


def _number_one_decimal(value: float) -> str:
    return f"{value:.1f}"


def _temperature_one_decimal(value: float) -> str:
    return f"{value:+.1f}".replace("-", "−")
