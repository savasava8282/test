from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from weather_alert_bot.geomagnetic_forecast import GeomagneticForecast
from weather_alert_bot.storage import UserSettings
from weather_alert_bot.weather_forecast import WeatherForecast


class DailySummaryError(RuntimeError):
    """Raised when a daily summary cannot be built from the supplied data."""


@dataclass(frozen=True, slots=True)
class DailySummary:
    city_name: str
    date: date
    weather_description: str
    temperature_min: float
    temperature_max: float
    morning_temperature: float
    daytime_temperature: float
    precipitation_probability_max: float
    precipitation_time: time | None
    precipitation_sum: float
    wind_speed_max: float
    wind_gusts_max: float
    kp_max_24h: float
    formed_at: datetime


_WMO_DESCRIPTIONS: dict[int, str] = {
    0: "ясно",
    1: "преимущественно ясно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "туман",
    51: "морось",
    53: "морось",
    55: "морось",
    56: "замерзающая морось",
    57: "замерзающая морось",
    61: "дождь",
    63: "дождь",
    65: "дождь",
    66: "ледяной дождь",
    67: "ледяной дождь",
    71: "снег",
    73: "снег",
    75: "снег",
    77: "снежные зёрна",
    80: "ливневый дождь",
    81: "ливневый дождь",
    82: "ливневый дождь",
    85: "снегопад",
    86: "снегопад",
    95: "гроза",
    96: "гроза с градом",
    99: "гроза с градом",
}
_MONTH_NAMES = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def build_daily_summary(
    settings: UserSettings,
    weather: WeatherForecast,
    geomagnetic: GeomagneticForecast,
    formed_at: datetime,
) -> DailySummary:
    """Build a deterministic summary for the user's current local date."""
    if not isinstance(formed_at, datetime) or not _is_aware(formed_at):
        raise DailySummaryError("Время формирования сводки должно быть aware datetime.")
    if not isinstance(settings.city_name, str) or not settings.city_name.strip():
        raise DailySummaryError("У пользователя отсутствует корректное название города.")

    try:
        user_zone = ZoneInfo(settings.timezone)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        raise DailySummaryError("Не удалось определить часовой пояс города.") from None

    local_formed_at = formed_at.astimezone(user_zone)
    local_date = local_formed_at.date()
    daily_matches = [item for item in weather.daily if item.date == local_date]
    if len(daily_matches) != 1:
        raise DailySummaryError("В прогнозе погоды отсутствует единственная запись текущего дня.")
    daily = daily_matches[0]

    hourly = [item for item in weather.hourly if item.time.date() == local_date]
    if not hourly:
        raise DailySummaryError("В прогнозе погоды отсутствуют почасовые данные текущего дня.")

    morning = _hourly_value(hourly, time(9, 0), "09:00")
    daytime = _hourly_value(hourly, time(15, 0), "15:00")
    precipitation_time = _choose_precipitation_time(
        hourly,
        daily.precipitation_probability_max,
        daily.precipitation_sum,
    )
    predicted = [item for item in geomagnetic.intervals if item.status == "predicted"][:8]
    if not predicted:
        raise DailySummaryError("В прогнозе Kp отсутствуют predicted-интервалы.")

    return DailySummary(
        city_name=settings.city_name.strip(),
        date=local_date,
        weather_description=_weather_description(daily.weather_code),
        temperature_min=daily.temperature_2m_min,
        temperature_max=daily.temperature_2m_max,
        morning_temperature=morning,
        daytime_temperature=daytime,
        precipitation_probability_max=daily.precipitation_probability_max,
        precipitation_time=precipitation_time,
        precipitation_sum=daily.precipitation_sum,
        wind_speed_max=daily.wind_speed_10m_max,
        wind_gusts_max=daily.wind_gusts_10m_max,
        kp_max_24h=max(item.kp for item in predicted),
        formed_at=local_formed_at,
    )


def format_daily_summary(summary: DailySummary) -> str:
    """Format a stable Russian user-facing daily summary."""
    if not isinstance(summary, DailySummary):
        raise DailySummaryError("Некорректная модель ежедневной сводки.")

    if summary.precipitation_time is None:
        precipitation_line = "Осадки: не ожидаются"
    else:
        precipitation_line = (
            f"Осадки: до {_format_number(summary.precipitation_probability_max)}%, "
            f"наиболее вероятно около {summary.precipitation_time:%H:%M}"
        )

    return "\n".join(
        (
            f"📍 {summary.city_name}",
            f"📅 {summary.date.day} {_MONTH_NAMES[summary.date.month - 1]} {summary.date.year}",
            "",
            f"Погода: {summary.weather_description}",
            "Температура: "
            f"{_format_temperature(summary.temperature_min)}…"
            f"{_format_temperature(summary.temperature_max)} °C",
            f"Утром: {_format_temperature(summary.morning_temperature)} °C",
            f"Днём: {_format_temperature(summary.daytime_temperature)} °C",
            "",
            precipitation_line,
            f"За сутки: {_format_number(summary.precipitation_sum)} мм",
            "",
            f"Ветер: до {_format_number(summary.wind_speed_max)} км/ч",
            f"Порывы: до {_format_number(summary.wind_gusts_max)} км/ч",
            "",
            "Магнитная активность: "
            f"Kp до {_format_number(summary.kp_max_24h)} в ближайшие 24 ч",
            "",
            f"Сводка сформирована: {summary.formed_at:%d.%m.%Y %H:%M}",
        )
    )


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _hourly_value(hourly: list[object], expected: time, label: str) -> float:
    matches = [item for item in hourly if getattr(item, "time", None).time() == expected]
    if len(matches) != 1:
        raise DailySummaryError(f"В прогнозе погоды отсутствует точное значение {label}.")
    value = getattr(matches[0], "temperature_2m", None)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise DailySummaryError(f"В прогнозе погоды отсутствует корректная температура {label}.")
    return float(value)


def _choose_precipitation_time(
    hourly: list[object],
    daily_probability: float,
    daily_sum: float,
) -> time | None:
    if daily_sum == 0 and daily_probability == 0:
        return None

    probabilities = [getattr(item, "precipitation_probability", None) for item in hourly]
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in probabilities):
        raise DailySummaryError("В прогнозе осадков отсутствуют корректные вероятности.")
    maximum = max(probabilities)
    if maximum > 0:
        for item in hourly:
            if item.precipitation_probability == maximum:
                return item.time.time().replace(second=0, microsecond=0)

    if daily_sum > 0:
        for item in hourly:
            if item.precipitation > 0:
                return item.time.time().replace(second=0, microsecond=0)
        raise DailySummaryError("В прогнозе осадков отсутствует время осадков.")
    return None


def _weather_description(weather_code: int) -> str:
    try:
        return _WMO_DESCRIPTIONS[weather_code]
    except (KeyError, TypeError):
        raise DailySummaryError("Неизвестный код погоды Open-Meteo.") from None


def _format_number(value: float) -> str:
    if value == 0:
        return "0"
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text


def _format_temperature(value: float) -> str:
    number = _format_number(value)
    if value > 0:
        return f"+{number}"
    return number
