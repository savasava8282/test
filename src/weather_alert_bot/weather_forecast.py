from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class WeatherForecastError(RuntimeError):
    """Raised when a weather forecast request or response is unsafe to use."""


@dataclass(frozen=True, slots=True)
class HourlyForecast:
    time: datetime
    temperature_2m: float
    precipitation_probability: float
    precipitation: float
    weather_code: int
    wind_speed_10m: float
    wind_gusts_10m: float


@dataclass(frozen=True, slots=True)
class DailyForecast:
    date: date
    weather_code: int
    temperature_2m_max: float
    temperature_2m_min: float
    precipitation_probability_max: float
    precipitation_sum: float
    wind_speed_10m_max: float
    wind_gusts_10m_max: float


@dataclass(frozen=True, slots=True)
class WeatherForecast:
    latitude: float
    longitude: float
    timezone: str
    generation_time_ms: float | None
    daily: tuple[DailyForecast, ...]
    hourly: tuple[HourlyForecast, ...]


class OpenMeteoWeatherClient:
    """One-shot client for the Open-Meteo Weather Forecast API."""

    ENDPOINT = "https://api.open-meteo.com/v1/forecast"
    TIMEOUT = 10
    USER_AGENT = "weather-alert-bot-weather/0.1"
    FORECAST_DAYS = 5
    DAILY_FIELDS = (
        "weather_code",
        "temperature_2m_max",
        "temperature_2m_min",
        "precipitation_probability_max",
        "precipitation_sum",
        "wind_speed_10m_max",
        "wind_gusts_10m_max",
    )
    HOURLY_FIELDS = (
        "temperature_2m",
        "precipitation_probability",
        "precipitation",
        "weather_code",
        "wind_speed_10m",
        "wind_gusts_10m",
    )

    def fetch(
        self,
        latitude: float,
        longitude: float,
        timezone: str,
        *,
        forecast_days: int = FORECAST_DAYS,
    ) -> WeatherForecast:
        normalized_latitude = self._validate_coordinate(latitude, "широта", -90, 90)
        normalized_longitude = self._validate_coordinate(longitude, "долгота", -180, 180)
        normalized_timezone = self._validate_timezone(timezone)
        if type(forecast_days) is not int or forecast_days != self.FORECAST_DAYS:
            raise WeatherForecastError("Прогноз должен запрашиваться ровно на 5 суток.")

        parameters = {
            "latitude": normalized_latitude,
            "longitude": normalized_longitude,
            "daily": ",".join(self.DAILY_FIELDS),
            "hourly": ",".join(self.HOURLY_FIELDS),
            "forecast_days": self.FORECAST_DAYS,
            "timezone": normalized_timezone,
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
            raise WeatherForecastError("Сервис прогноза погоды вернул ошибку.")
        return self._parse_forecast(payload)

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
            raise WeatherForecastError(f"Некорректная {label} сохранённого города.")
        return float(value)

    @staticmethod
    def _validate_timezone(timezone: str) -> str:
        if not isinstance(timezone, str) or not timezone.strip():
            raise WeatherForecastError("Некорректный часовой пояс сохранённого города.")
        if any(ord(character) < 32 or ord(character) == 127 for character in timezone):
            raise WeatherForecastError("Некорректный часовой пояс сохранённого города.")
        return timezone.strip()

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
            raise WeatherForecastError(
                f"Сервис прогноза погоды вернул HTTP-ошибку ({exc.code})."
            ) from None
        except TimeoutError:
            raise WeatherForecastError(
                "Истекло время ожидания сервиса прогноза погоды."
            ) from None
        except (urllib.error.URLError, OSError):
            raise WeatherForecastError(
                "Не удалось подключиться к сервису прогноза погоды."
            ) from None

        if isinstance(status, bool) or not isinstance(status, int) or not 200 <= status < 300:
            raise WeatherForecastError(
                "Сервис прогноза погоды вернул недопустимый HTTP-статус."
            )

        try:
            payload = json.loads(response_body)
        except (TypeError, ValueError):
            raise WeatherForecastError(
                "Сервис прогноза погоды вернул некорректный JSON."
            ) from None

        if not isinstance(payload, dict):
            raise WeatherForecastError(
                "Сервис прогноза погоды вернул некорректную структуру ответа."
            )
        return payload

    @classmethod
    def _parse_forecast(cls, payload: dict[str, Any]) -> WeatherForecast:
        latitude = cls._parse_coordinate_field(payload, "latitude", -90, 90)
        longitude = cls._parse_coordinate_field(payload, "longitude", -180, 180)
        timezone = payload.get("timezone")
        if not isinstance(timezone, str) or not timezone.strip():
            raise WeatherForecastError(
                "Ответ прогноза погоды не содержит обязательный часовой пояс."
            )
        timezone = cls._validate_timezone(timezone)

        generation_time_ms = payload.get("generationtime_ms")
        if generation_time_ms is not None:
            generation_time_ms = cls._parse_finite_number(
                generation_time_ms,
                "время генерации",
            )

        daily = payload.get("daily")
        hourly = payload.get("hourly")
        if not isinstance(daily, dict):
            raise WeatherForecastError(
                "Ответ прогноза погоды не содержит обязательный daily-раздел."
            )
        if not isinstance(hourly, dict):
            raise WeatherForecastError(
                "Ответ прогноза погоды не содержит обязательный hourly-раздел."
            )

        daily_arrays = cls._required_arrays(daily, cls.DAILY_FIELDS, "daily")
        daily_times = cls._required_array(daily, "time", "daily")
        if len(daily_times) != cls.FORECAST_DAYS:
            raise WeatherForecastError("Ответ прогноза погоды содержит не 5 дней.")
        if any(len(values) != len(daily_times) for values in daily_arrays.values()):
            raise WeatherForecastError(
                "Массивы daily-прогноза погоды имеют разную длину."
            )

        daily_forecasts = tuple(
            DailyForecast(
                date=cls._parse_date(daily_times[index], "daily.time"),
                weather_code=cls._parse_weather_code(
                    daily_arrays["weather_code"][index],
                    "daily.weather_code",
                ),
                temperature_2m_max=cls._parse_finite_number(
                    daily_arrays["temperature_2m_max"][index],
                    "daily.temperature_2m_max",
                ),
                temperature_2m_min=cls._parse_finite_number(
                    daily_arrays["temperature_2m_min"][index],
                    "daily.temperature_2m_min",
                ),
                precipitation_probability_max=cls._parse_probability(
                    daily_arrays["precipitation_probability_max"][index],
                    "daily.precipitation_probability_max",
                ),
                precipitation_sum=cls._parse_nonnegative_number(
                    daily_arrays["precipitation_sum"][index],
                    "daily.precipitation_sum",
                ),
                wind_speed_10m_max=cls._parse_nonnegative_number(
                    daily_arrays["wind_speed_10m_max"][index],
                    "daily.wind_speed_10m_max",
                ),
                wind_gusts_10m_max=cls._parse_nonnegative_number(
                    daily_arrays["wind_gusts_10m_max"][index],
                    "daily.wind_gusts_10m_max",
                ),
            )
            for index in range(len(daily_times))
        )

        hourly_arrays = cls._required_arrays(hourly, cls.HOURLY_FIELDS, "hourly")
        hourly_times = cls._required_array(hourly, "time", "hourly")
        if not hourly_times:
            raise WeatherForecastError("Ответ прогноза погоды не содержит hourly-значений.")
        if any(len(values) != len(hourly_times) for values in hourly_arrays.values()):
            raise WeatherForecastError(
                "Массивы hourly-прогноза погоды имеют разную длину."
            )

        hourly_forecasts = tuple(
            HourlyForecast(
                time=cls._parse_timestamp(hourly_times[index], "hourly.time"),
                temperature_2m=cls._parse_finite_number(
                    hourly_arrays["temperature_2m"][index],
                    "hourly.temperature_2m",
                ),
                precipitation_probability=cls._parse_probability(
                    hourly_arrays["precipitation_probability"][index],
                    "hourly.precipitation_probability",
                ),
                precipitation=cls._parse_nonnegative_number(
                    hourly_arrays["precipitation"][index],
                    "hourly.precipitation",
                ),
                weather_code=cls._parse_weather_code(
                    hourly_arrays["weather_code"][index],
                    "hourly.weather_code",
                ),
                wind_speed_10m=cls._parse_nonnegative_number(
                    hourly_arrays["wind_speed_10m"][index],
                    "hourly.wind_speed_10m",
                ),
                wind_gusts_10m=cls._parse_nonnegative_number(
                    hourly_arrays["wind_gusts_10m"][index],
                    "hourly.wind_gusts_10m",
                ),
            )
            for index in range(len(hourly_times))
        )

        return WeatherForecast(
            latitude=latitude,
            longitude=longitude,
            timezone=timezone,
            generation_time_ms=generation_time_ms,
            daily=daily_forecasts,
            hourly=hourly_forecasts,
        )

    @classmethod
    def _required_arrays(
        cls,
        section: dict[str, Any],
        fields: tuple[str, ...],
        section_name: str,
    ) -> dict[str, list[object]]:
        return {
            field: cls._required_array(section, field, section_name)
            for field in fields
        }

    @staticmethod
    def _required_array(
        section: dict[str, Any],
        field: str,
        section_name: str,
    ) -> list[object]:
        values = section.get(field)
        if not isinstance(values, list):
            raise WeatherForecastError(
                f"Ответ прогноза погоды не содержит обязательный массив {section_name}.{field}."
            )
        return values

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
            raise WeatherForecastError(
                f"Ответ прогноза погоды содержит некорректное поле {field}."
            )
        return float(value)

    @staticmethod
    def _parse_finite_number(value: object, field: str) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise WeatherForecastError(
                f"Ответ прогноза погоды содержит некорректное числовое поле {field}."
            )
        return float(value)

    @classmethod
    def _parse_nonnegative_number(cls, value: object, field: str) -> float:
        parsed = cls._parse_finite_number(value, field)
        if parsed < 0:
            raise WeatherForecastError(
                f"Ответ прогноза погоды содержит отрицательное поле {field}."
            )
        return parsed

    @classmethod
    def _parse_probability(cls, value: object, field: str) -> float:
        parsed = cls._parse_finite_number(value, field)
        if not 0 <= parsed <= 100:
            raise WeatherForecastError(
                f"Ответ прогноза погоды содержит некорректную вероятность {field}."
            )
        return parsed

    @staticmethod
    def _parse_weather_code(value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise WeatherForecastError(
                f"Ответ прогноза погоды содержит некорректный код {field}."
            )
        return value

    @staticmethod
    def _parse_date(value: object, field: str) -> date:
        if not isinstance(value, str):
            raise WeatherForecastError(
                f"Ответ прогноза погоды содержит некорректную дату {field}."
            )
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise WeatherForecastError(
                f"Ответ прогноза погоды содержит некорректную дату {field}."
            ) from None

    @staticmethod
    def _parse_timestamp(value: object, field: str) -> datetime:
        if not isinstance(value, str) or "T" not in value:
            raise WeatherForecastError(
                f"Ответ прогноза погоды содержит некорректное время {field}."
            )
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise WeatherForecastError(
                f"Ответ прогноза погоды содержит некорректное время {field}."
            ) from None
