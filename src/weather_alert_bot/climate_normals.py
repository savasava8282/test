from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


BASELINE_START = date(1991, 1, 1)
BASELINE_END = date(2020, 12, 31)
HISTORICAL_ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"
HISTORICAL_MODEL = "era5_land"
HISTORICAL_TIMEZONE = "timezone"


class ClimateNormalsError(RuntimeError):
    """Raised when historical climate-normal data is unsafe or incomplete."""


@dataclass(frozen=True, slots=True)
class HistoricalTemperatureDay:
    date: date
    temperature_min: float
    temperature_max: float


@dataclass(frozen=True, slots=True)
class ClimateNormalDay:
    month: int
    day: int
    normal_temperature_min: float
    normal_temperature_max: float
    sample_count: int


@dataclass(frozen=True, slots=True)
class ClimateNormals:
    latitude: float
    longitude: float
    timezone: str
    period_start: date
    period_end: date
    days: tuple[ClimateNormalDay, ...]


@dataclass(frozen=True, slots=True)
class TemperatureDeviation:
    min_deviation: float
    max_deviation: float


class OpenMeteoHistoricalWeatherClient:
    """One-shot client for the Open-Meteo Historical Weather API."""

    ENDPOINT = HISTORICAL_ENDPOINT
    TIMEOUT = 15
    USER_AGENT = "weather-alert-bot-climate-normals/0.1"
    DAILY_FIELDS = ("temperature_2m_min", "temperature_2m_max")

    def fetch(
        self,
        latitude: float,
        longitude: float,
        timezone: str,
    ) -> tuple[HistoricalTemperatureDay, ...]:
        normalized_latitude = self._validate_coordinate(
            latitude, "широта", -90, 90
        )
        normalized_longitude = self._validate_coordinate(
            longitude, "долгота", -180, 180
        )
        normalized_timezone = self._validate_timezone(timezone)
        parameters = {
            "latitude": normalized_latitude,
            "longitude": normalized_longitude,
            "start_date": BASELINE_START.isoformat(),
            "end_date": BASELINE_END.isoformat(),
            HISTORICAL_TIMEZONE: normalized_timezone,
            "daily": ",".join(self.DAILY_FIELDS),
            "temperature_unit": "celsius",
            "models": HISTORICAL_MODEL,
        }
        request_url = f"{self.ENDPOINT}?{urllib.parse.urlencode(parameters)}"
        request = urllib.request.Request(
            request_url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.USER_AGENT,
            },
            method="GET",
        )
        payload = self._request_json(request)
        if payload.get("error") is True:
            raise ClimateNormalsError(
                "Сервис исторической погоды вернул ошибку."
            )
        return self._parse_historical_response(payload)

    @staticmethod
    def _validate_coordinate(
        value: float,
        label: str,
        minimum: float,
        maximum: float,
    ) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not minimum <= value <= maximum
        ):
            raise ClimateNormalsError(f"Некорректная {label} сохранённого города.")
        return float(value)

    @staticmethod
    def _validate_timezone(timezone_name: str) -> str:
        if not isinstance(timezone_name, str) or not timezone_name.strip():
            raise ClimateNormalsError("Некорректный часовой пояс сохранённого города.")
        if any(ord(character) < 32 or ord(character) == 127 for character in timezone_name):
            raise ClimateNormalsError("Некорректный часовой пояс сохранённого города.")
        return timezone_name.strip()

    @classmethod
    def _request_json(cls, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=cls.TIMEOUT) as response:
                status = getattr(response, "status", None)
                if isinstance(status, bool) or not isinstance(status, int):
                    getcode = getattr(response, "getcode", None)
                    status = getcode() if callable(getcode) else None
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            raise ClimateNormalsError(
                f"Сервис исторической погоды вернул HTTP-ошибку ({exc.code})."
            ) from None
        except TimeoutError:
            raise ClimateNormalsError(
                "Истекло время ожидания сервиса исторической погоды."
            ) from None
        except (urllib.error.URLError, OSError):
            raise ClimateNormalsError(
                "Не удалось подключиться к сервису исторической погоды."
            ) from None

        if isinstance(status, bool) or not isinstance(status, int) or not 200 <= status < 300:
            raise ClimateNormalsError(
                "Сервис исторической погоды вернул недопустимый HTTP-статус."
            )

        try:
            payload = json.loads(response_body)
        except (TypeError, ValueError):
            raise ClimateNormalsError(
                "Сервис исторической погоды вернул некорректный JSON."
            ) from None
        if not isinstance(payload, dict):
            raise ClimateNormalsError(
                "Сервис исторической погоды вернул некорректную структуру ответа."
            )
        return payload

    @classmethod
    def _parse_historical_response(
        cls,
        payload: dict[str, Any],
    ) -> tuple[HistoricalTemperatureDay, ...]:
        if not isinstance(payload, dict):
            raise ClimateNormalsError(
                "Сервис исторической погоды вернул некорректную структуру ответа."
            )
        cls._parse_coordinate_field(payload, "latitude", -90, 90)
        cls._parse_coordinate_field(payload, "longitude", -180, 180)
        timezone_name = payload.get("timezone")
        cls._validate_timezone(timezone_name)

        daily = payload.get("daily")
        if not isinstance(daily, dict):
            raise ClimateNormalsError(
                "Ответ исторической погоды не содержит обязательный daily-раздел."
            )
        times = cls._required_array(daily, "time")
        minimums = cls._required_array(daily, "temperature_2m_min")
        maximums = cls._required_array(daily, "temperature_2m_max")
        if not len(times) == len(minimums) == len(maximums):
            raise ClimateNormalsError(
                "Массивы исторической температуры имеют разную длину."
            )

        records: list[HistoricalTemperatureDay] = []
        seen_dates: set[date] = set()
        for index, raw_date in enumerate(times):
            parsed_date = cls._parse_date(raw_date)
            if not BASELINE_START <= parsed_date <= BASELINE_END:
                raise ClimateNormalsError(
                    "Ответ исторической погоды содержит дату вне базового периода."
                )
            if parsed_date in seen_dates:
                raise ClimateNormalsError(
                    "Ответ исторической погоды содержит повторяющуюся дату."
                )
            seen_dates.add(parsed_date)
            temperature_min = cls._parse_temperature(
                minimums[index], "daily.temperature_2m_min"
            )
            temperature_max = cls._parse_temperature(
                maximums[index], "daily.temperature_2m_max"
            )
            if temperature_min > temperature_max:
                raise ClimateNormalsError(
                    "Ответ исторической погоды содержит minimum выше maximum."
                )
            records.append(
                HistoricalTemperatureDay(
                    date=parsed_date,
                    temperature_min=temperature_min,
                    temperature_max=temperature_max,
                )
            )
        return tuple(records)

    @classmethod
    def _parse_coordinate_field(
        cls,
        payload: dict[str, Any],
        field: str,
        minimum: float,
        maximum: float,
    ) -> float:
        value = payload.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not minimum <= value <= maximum
        ):
            raise ClimateNormalsError(
                f"Ответ исторической погоды содержит некорректное поле {field}."
            )
        return float(value)

    @staticmethod
    def _required_array(section: dict[str, Any], field: str) -> list[object]:
        values = section.get(field)
        if not isinstance(values, list):
            raise ClimateNormalsError(
                f"Ответ исторической погоды не содержит обязательный массив daily.{field}."
            )
        return values

    @staticmethod
    def _parse_date(value: object) -> date:
        if not isinstance(value, str):
            raise ClimateNormalsError(
                "Ответ исторической погоды содержит некорректную дату."
            )
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise ClimateNormalsError(
                "Ответ исторической погоды содержит некорректную дату."
            ) from None
        if parsed.isoformat() != value:
            raise ClimateNormalsError(
                "Ответ исторической погоды содержит некорректную дату."
            )
        return parsed

    @staticmethod
    def _parse_temperature(value: object, field: str) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ClimateNormalsError(
                f"Ответ исторической погоды содержит некорректную температуру {field}."
            )
        return float(value)


def _expected_dates() -> tuple[date, ...]:
    count = (BASELINE_END - BASELINE_START).days + 1
    return tuple(BASELINE_START + timedelta(days=offset) for offset in range(count))


def _validate_calculation_inputs(
    historical_days: Iterable[HistoricalTemperatureDay],
) -> tuple[HistoricalTemperatureDay, ...]:
    try:
        records = tuple(historical_days)
    except TypeError as exc:
        raise ClimateNormalsError("Исторические данные имеют недопустимый формат.") from exc

    seen_dates: set[date] = set()
    for record in records:
        if not isinstance(record, HistoricalTemperatureDay):
            raise ClimateNormalsError("Исторические данные имеют недопустимый формат.")
        if not isinstance(record.date, date):
            raise ClimateNormalsError("Исторические данные содержат некорректную дату.")
        if record.date in seen_dates:
            raise ClimateNormalsError("Исторические данные содержат повторяющуюся дату.")
        if not BASELINE_START <= record.date <= BASELINE_END:
            raise ClimateNormalsError(
                "Исторические данные содержат дату вне базового периода."
            )
        seen_dates.add(record.date)
        minimum = OpenMeteoHistoricalWeatherClient._parse_temperature(
            record.temperature_min, "temperature_min"
        )
        maximum = OpenMeteoHistoricalWeatherClient._parse_temperature(
            record.temperature_max, "temperature_max"
        )
        if minimum > maximum:
            raise ClimateNormalsError(
                "Исторические данные содержат minimum выше maximum."
            )

    expected = _expected_dates()
    if len(records) != len(expected) or seen_dates != set(expected):
        raise ClimateNormalsError(
            "Исторические данные не покрывают полностью период 1991–2020."
        )
    return records


def calculate_climate_normals(
    historical_days: Iterable[HistoricalTemperatureDay],
    latitude: float,
    longitude: float,
    timezone: str,
) -> ClimateNormals:
    """Build exact calendar-day arithmetic means from the full baseline."""
    records = _validate_calculation_inputs(historical_days)
    normalized_latitude = OpenMeteoHistoricalWeatherClient._validate_coordinate(
        latitude, "широта", -90, 90
    )
    normalized_longitude = OpenMeteoHistoricalWeatherClient._validate_coordinate(
        longitude, "долгота", -180, 180
    )
    normalized_timezone = OpenMeteoHistoricalWeatherClient._validate_timezone(
        timezone
    )

    grouped: dict[tuple[int, int], list[HistoricalTemperatureDay]] = defaultdict(list)
    for record in records:
        grouped[(record.date.month, record.date.day)].append(record)

    normal_days = tuple(
        ClimateNormalDay(
            month=month_day[0],
            day=month_day[1],
            normal_temperature_min=sum(
                record.temperature_min for record in grouped[month_day]
            )
            / len(grouped[month_day]),
            normal_temperature_max=sum(
                record.temperature_max for record in grouped[month_day]
            )
            / len(grouped[month_day]),
            sample_count=len(grouped[month_day]),
        )
        for month_day in sorted(grouped)
    )
    return ClimateNormals(
        latitude=normalized_latitude,
        longitude=normalized_longitude,
        timezone=normalized_timezone,
        period_start=BASELINE_START,
        period_end=BASELINE_END,
        days=normal_days,
    )


def get_climate_normal_for_date(
    normals: ClimateNormals,
    target_date: date,
) -> ClimateNormalDay:
    """Return the normal for target month/day; target year is not used."""
    if not isinstance(normals, ClimateNormals) or not isinstance(target_date, date):
        raise ClimateNormalsError("Норма климата или дата имеют недопустимый формат.")
    for normal_day in normals.days:
        if normal_day.month == target_date.month and normal_day.day == target_date.day:
            return normal_day
    raise ClimateNormalsError("Для указанной календарной даты норма не найдена.")


def calculate_temperature_deviation(
    normal: ClimateNormalDay,
    forecast_min: float,
    forecast_max: float,
) -> TemperatureDeviation:
    """Calculate neutral forecast-minus-normal deviations without classification."""
    if not isinstance(normal, ClimateNormalDay):
        raise ClimateNormalsError("Норма климата имеет недопустимый формат.")
    parsed_min = OpenMeteoHistoricalWeatherClient._parse_temperature(
        forecast_min, "forecast_min"
    )
    parsed_max = OpenMeteoHistoricalWeatherClient._parse_temperature(
        forecast_max, "forecast_max"
    )
    return TemperatureDeviation(
        min_deviation=parsed_min - normal.normal_temperature_min,
        max_deviation=parsed_max - normal.normal_temperature_max,
    )


_MONTH_NAMES = (
    "",
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


def format_climate_normal(normals: ClimateNormals, target_date: date) -> str:
    """Format one stable human-readable diagnostic for a calendar date."""
    if not isinstance(normals, ClimateNormals) or not isinstance(target_date, date):
        raise ClimateNormalsError("Норма климата или дата имеют недопустимый формат.")
    normal_day = get_climate_normal_for_date(normals, target_date)
    return "\n".join(
        (
            f"Климатическая норма: {target_date.day} {_MONTH_NAMES[target_date.month]}",
            f"Период: {normals.period_start.year}–{normals.period_end.year}",
            "Источник: Open-Meteo ERA5-Land",
            "",
            f"Обычный минимум: {_format_temperature(normal_day.normal_temperature_min)}",
            f"Обычный максимум: {_format_temperature(normal_day.normal_temperature_max)}",
            f"Наблюдений: {normal_day.sample_count}",
        )
    )


def local_calendar_date(current_time: datetime, timezone: str) -> date:
    """Convert an explicit aware instant to a saved timezone's local date."""
    if (
        not isinstance(current_time, datetime)
        or current_time.tzinfo is None
        or current_time.utcoffset() is None
    ):
        raise ClimateNormalsError("Текущее время должно быть aware datetime.")
    try:
        local_zone = ZoneInfo(OpenMeteoHistoricalWeatherClient._validate_timezone(timezone))
    except (ZoneInfoNotFoundError, ValueError):
        raise ClimateNormalsError("Некорректный часовой пояс сохранённого города.") from None
    return current_time.astimezone(local_zone).date()


def _format_temperature(value: float) -> str:
    return f"{value:+.1f} °C"
