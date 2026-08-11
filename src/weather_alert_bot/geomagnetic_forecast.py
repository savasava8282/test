from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
import urllib.error
import urllib.request


class GeomagneticForecastError(RuntimeError):
    """Raised when the NOAA SWPC Kp forecast is unsafe to use."""


@dataclass(frozen=True, slots=True)
class GeomagneticForecastInterval:
    """One forecast interval from the NOAA planetary K-index product."""

    timestamp: datetime
    kp: float
    status: str
    noaa_scale: str | None = None


@dataclass(frozen=True, slots=True)
class GeomagneticForecast:
    """Safely parsed NOAA SWPC planetary K-index forecast."""

    intervals: tuple[GeomagneticForecastInterval, ...]


class NoaaSwpcGeomagneticClient:
    """One-shot client for the official NOAA SWPC planetary K-index product."""

    ENDPOINT = (
        "https://services.swpc.noaa.gov/products/"
        "noaa-planetary-k-index-forecast.json"
    )
    TIMEOUT = 10
    USER_AGENT = "weather-alert-bot-geomagnetic/0.1"
    KNOWN_STATUSES = frozenset(("observed", "estimated", "predicted"))

    def fetch(self) -> GeomagneticForecast:
        request = urllib.request.Request(
            self.ENDPOINT,
            headers={
                "Accept": "application/json",
                "User-Agent": self.USER_AGENT,
            },
            method="GET",
        )
        payload = self._request_json(request)
        return self._parse_forecast(payload)

    @classmethod
    def _request_json(cls, request: urllib.request.Request) -> object:
        try:
            with urllib.request.urlopen(request, timeout=cls.TIMEOUT) as response:
                status = getattr(response, "status", None)
                if isinstance(status, bool) or not isinstance(status, int):
                    getcode = getattr(response, "getcode", None)
                    status = getcode() if callable(getcode) else None
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            raise GeomagneticForecastError(
                f"Сервис NOAA SWPC вернул HTTP-ошибку ({exc.code})."
            ) from None
        except TimeoutError:
            raise GeomagneticForecastError(
                "Истекло время ожидания сервиса NOAA SWPC."
            ) from None
        except (urllib.error.URLError, OSError):
            raise GeomagneticForecastError(
                "Не удалось подключиться к сервису NOAA SWPC."
            ) from None

        if isinstance(status, bool) or not isinstance(status, int) or not 200 <= status < 300:
            raise GeomagneticForecastError(
                "Сервис NOAA SWPC вернул недопустимый HTTP-статус."
            )

        try:
            return json.loads(response_body)
        except (TypeError, ValueError):
            raise GeomagneticForecastError(
                "Сервис NOAA SWPC вернул некорректный JSON."
            ) from None

    @classmethod
    def _parse_forecast(cls, payload: object) -> GeomagneticForecast:
        if not isinstance(payload, list) or not payload:
            raise GeomagneticForecastError(
                "Ответ NOAA SWPC должен быть непустым списком объектов."
            )

        intervals: list[GeomagneticForecastInterval] = []

        for row_number, row in enumerate(payload, start=1):
            if not isinstance(row, dict):
                raise GeomagneticForecastError(
                    f"Ответ NOAA SWPC содержит некорректный объект {row_number}."
                )

            for field in ("time_tag", "kp", "observed"):
                if field not in row:
                    raise GeomagneticForecastError(
                        f"Ответ NOAA SWPC не содержит поле {field}."
                    )
            timestamp = cls._parse_timestamp(
                row["time_tag"],
                f"объект {row_number}, time_tag",
            )
            kp = cls._parse_kp(row["kp"], f"объект {row_number}, kp")
            status = cls._parse_status(
                row["observed"],
                f"объект {row_number}, observed",
            )
            noaa_scale = cls._parse_noaa_scale(
                row.get("noaa_scale"),
                f"объект {row_number}, noaa_scale",
            )
            intervals.append(
                GeomagneticForecastInterval(
                    timestamp=timestamp,
                    kp=kp,
                    status=status,
                    noaa_scale=noaa_scale,
                )
            )

        if not intervals:
            raise GeomagneticForecastError("Ответ NOAA SWPC не содержит интервалов прогноза.")
        return GeomagneticForecast(intervals=tuple(intervals))

    @staticmethod
    def _parse_timestamp(value: object, field: str) -> datetime:
        if not isinstance(value, str):
            raise GeomagneticForecastError(
                f"Ответ NOAA SWPC содержит некорректный timestamp ({field})."
            )
        normalized = value.strip()
        if not normalized or ("T" not in normalized and " " not in normalized):
            raise GeomagneticForecastError(
                f"Ответ NOAA SWPC содержит некорректный timestamp ({field})."
            )
        if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
            raise GeomagneticForecastError(
                f"Ответ NOAA SWPC содержит некорректный timestamp ({field})."
            )
        try:
            return datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError:
            raise GeomagneticForecastError(
                f"Ответ NOAA SWPC содержит некорректный timestamp ({field})."
            ) from None

    @staticmethod
    def _parse_kp(value: object, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise GeomagneticForecastError(
                f"Ответ NOAA SWPC содержит некорректный Kp ({field})."
            )
        try:
            parsed = float(value)
        except (OverflowError, ValueError):
            raise GeomagneticForecastError(
                f"Ответ NOAA SWPC содержит некорректный Kp ({field})."
            ) from None
        if not math.isfinite(parsed):
            raise GeomagneticForecastError(
                f"Ответ NOAA SWPC содержит некорректный Kp ({field})."
            )
        if not 0 <= parsed <= 9:
            raise GeomagneticForecastError(
                f"Ответ NOAA SWPC содержит Kp вне допустимого диапазона ({field})."
            )
        return parsed

    @staticmethod
    def _parse_status(value: object, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise GeomagneticForecastError(
                f"Ответ NOAA SWPC содержит некорректный status ({field})."
            )
        normalized = value.strip().lower()
        if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
            raise GeomagneticForecastError(
                f"Ответ NOAA SWPC содержит некорректный status ({field})."
            )
        if normalized not in NoaaSwpcGeomagneticClient.KNOWN_STATUSES:
            raise GeomagneticForecastError(
                f"Ответ NOAA SWPC содержит неизвестный status ({field})."
            )
        return normalized

    @staticmethod
    def _parse_noaa_scale(value: object, field: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise GeomagneticForecastError(
                f"Ответ NOAA SWPC содержит некорректный noaa_scale ({field})."
            )
        normalized = value.strip()
        if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
            raise GeomagneticForecastError(
                f"Ответ NOAA SWPC содержит некорректный noaa_scale ({field})."
            )
        return normalized
