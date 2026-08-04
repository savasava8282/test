import json
import math
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class GeocodingError(RuntimeError):
    """Raised when a city geocoding request or response is unsafe to use."""


@dataclass(frozen=True, slots=True)
class GeocodingLocation:
    id: int
    name: str
    latitude: float
    longitude: float
    timezone: str
    country_code: str
    country: str
    admin1: str | None = None
    population: int | None = None


class OpenMeteoGeocodingClient:
    """One-shot client for the Open-Meteo Geocoding API."""

    ENDPOINT = "https://geocoding-api.open-meteo.com/v1/search"
    TIMEOUT = 10
    USER_AGENT = "weather-alert-bot-geocoder/0.1"

    def search(
        self,
        query: str,
        *,
        count: int = 5,
        language: str = "ru",
    ) -> tuple[GeocodingLocation, ...]:
        normalized_query = self._validate_query(query)
        self._validate_options(count, language)

        parameters = {
            "name": normalized_query,
            "count": count,
            "language": language,
            "format": "json",
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
            raise GeocodingError("Сервис геокодирования вернул ошибку.")

        if "results" not in payload:
            return ()
        raw_results = payload["results"]
        if not isinstance(raw_results, list):
            raise GeocodingError("Сервис геокодирования вернул некорректный список результатов.")

        locations: list[GeocodingLocation] = []
        for raw_result in raw_results[:count]:
            locations.append(self._parse_location(raw_result))
        return tuple(locations)

    @staticmethod
    def _validate_query(query: str) -> str:
        if not isinstance(query, str):
            raise GeocodingError("Название города должно быть текстом.")
        if any(
            character in "\r\n\t\u2028\u2029"
            or unicodedata.category(character).startswith("C")
            for character in query
        ):
            raise GeocodingError("Название города содержит недопустимые управляющие символы.")

        query = query.strip()
        if not query:
            raise GeocodingError("Название города не должно быть пустым.")
        if len(query) < 2 or len(query) > 100:
            raise GeocodingError("Название города должно содержать от 2 до 100 символов.")
        if not any(character.isalpha() for character in query):
            raise GeocodingError("Название города должно содержать хотя бы одну букву.")
        if query.startswith("/"):
            raise GeocodingError("Название города не должно начинаться с команды.")
        return query

    @staticmethod
    def _validate_options(count: int, language: str) -> None:
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 5:
            raise GeocodingError("Количество вариантов должно быть целым числом от 1 до 5.")
        if not isinstance(language, str) or not language.strip():
            raise GeocodingError("Язык запроса геокодирования задан некорректно.")

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
            raise GeocodingError(f"Сервис геокодирования вернул HTTP-ошибку ({exc.code}).") from None
        except TimeoutError:
            raise GeocodingError("Истекло время ожидания сервиса геокодирования.") from None
        except (urllib.error.URLError, OSError):
            raise GeocodingError("Не удалось подключиться к сервису геокодирования.") from None

        if isinstance(status, bool) or not isinstance(status, int) or not 200 <= status < 300:
            raise GeocodingError("Сервис геокодирования вернул недопустимый HTTP-статус.")

        try:
            payload = json.loads(response_body)
        except (TypeError, ValueError):
            raise GeocodingError("Сервис геокодирования вернул некорректный JSON.") from None

        if not isinstance(payload, dict):
            raise GeocodingError("Сервис геокодирования вернул некорректную структуру ответа.")
        return payload

    @staticmethod
    def _parse_location(raw_result: object) -> GeocodingLocation:
        if not isinstance(raw_result, dict):
            raise GeocodingError("Результат геокодирования имеет некорректную структуру.")

        location_id = raw_result.get("id")
        name = raw_result.get("name")
        latitude = raw_result.get("latitude")
        longitude = raw_result.get("longitude")
        timezone = raw_result.get("timezone")
        country_code = raw_result.get("country_code")
        country = raw_result.get("country")
        admin1 = raw_result.get("admin1")
        population = raw_result.get("population")

        if (
            isinstance(location_id, bool)
            or not isinstance(location_id, int)
            or not isinstance(name, str)
            or not isinstance(timezone, str)
            or not isinstance(country_code, str)
            or not isinstance(country, str)
        ):
            raise GeocodingError("Результат геокодирования не содержит обязательные поля.")
        if (
            isinstance(latitude, bool)
            or not isinstance(latitude, (int, float))
            or not math.isfinite(latitude)
            or not -90 <= latitude <= 90
            or isinstance(longitude, bool)
            or not isinstance(longitude, (int, float))
            or not math.isfinite(longitude)
            or not -180 <= longitude <= 180
        ):
            raise GeocodingError("Результат геокодирования содержит недопустимые координаты.")
        if admin1 is not None and not isinstance(admin1, str):
            raise GeocodingError("Результат геокодирования содержит некорректный регион.")
        if population is not None and (
            isinstance(population, bool) or not isinstance(population, int)
        ):
            raise GeocodingError("Результат геокодирования содержит некорректную численность.")

        return GeocodingLocation(
            id=location_id,
            name=name,
            latitude=float(latitude),
            longitude=float(longitude),
            timezone=timezone,
            country_code=country_code,
            country=country,
            admin1=admin1,
            population=population,
        )
