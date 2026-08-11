import json
import math
from datetime import datetime
import urllib.error
import urllib.parse
import unittest
from unittest.mock import patch

from weather_alert_bot.weather_forecast import (
    DailyForecast,
    HourlyForecast,
    OpenMeteoWeatherClient,
    WeatherForecast,
    WeatherForecastError,
)


class MockResponse:
    def __init__(self, payload: object, *, status: int = 200) -> None:
        self.status = status
        self._body = json.dumps(payload, allow_nan=True).encode("utf-8")

    def __enter__(self) -> "MockResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status


def forecast_payload(*, days: int = 5, hours: int = 3) -> dict[str, object]:
    daily: dict[str, object] = {
        "time": [f"2026-08-{12 + index:02d}" for index in range(days)],
        "weather_code": [1 + index for index in range(days)],
        "temperature_2m_max": [25.0 + index for index in range(days)],
        "temperature_2m_min": [15.0 + index for index in range(days)],
        "precipitation_probability_max": [40 + index for index in range(days)],
        "precipitation_sum": [2.5 + index for index in range(days)],
        "wind_speed_10m_max": [10.0 + index for index in range(days)],
        "wind_gusts_10m_max": [18.0 + index for index in range(days)],
    }
    hourly: dict[str, object] = {
        "time": [f"2026-08-12T{index:02d}:00" for index in range(hours)],
        "temperature_2m": [20.0 + index for index in range(hours)],
        "precipitation_probability": [10 + index for index in range(hours)],
        "precipitation": [0.1 * index for index in range(hours)],
        "weather_code": [1 for _ in range(hours)],
        "wind_speed_10m": [5.0 + index for index in range(hours)],
        "wind_gusts_10m": [8.0 + index for index in range(hours)],
    }
    return {
        "latitude": 55.75204,
        "longitude": 37.61781,
        "timezone": "Europe/Moscow",
        "generationtime_ms": 0.42,
        "daily": daily,
        "hourly": hourly,
    }


class WeatherForecastRequestTest(unittest.TestCase):
    def test_request_contains_saved_coordinates_timezone_and_required_fields(self) -> None:
        with patch(
            "weather_alert_bot.weather_forecast.urllib.request.urlopen",
            return_value=MockResponse(forecast_payload()),
        ) as urlopen:
            OpenMeteoWeatherClient().fetch(55.75204, 37.61781, "Europe/Moscow")

        urlopen.assert_called_once()
        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(
            request.full_url.split("?", 1)[0],
            "https://api.open-meteo.com/v1/forecast",
        )
        query = urllib.parse.parse_qs(request.full_url.split("?", 1)[1])
        self.assertEqual(query["latitude"], ["55.75204"])
        self.assertEqual(query["longitude"], ["37.61781"])
        self.assertEqual(query["timezone"], ["Europe/Moscow"])
        self.assertEqual(query["forecast_days"], ["5"])
        self.assertEqual(
            query["daily"],
            ["weather_code,temperature_2m_max,temperature_2m_min,"
             "precipitation_probability_max,precipitation_sum,"
             "wind_speed_10m_max,wind_gusts_10m_max"],
        )
        self.assertEqual(
            query["hourly"],
            ["temperature_2m,precipitation_probability,precipitation,"
             "weather_code,wind_speed_10m,wind_gusts_10m"],
        )
        self.assertEqual(request.headers["Accept"], "application/json")
        self.assertEqual(
            request.headers["User-agent"],
            "weather-alert-bot-weather/0.1",
        )
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 10)

    def test_only_five_forecast_days_are_allowed(self) -> None:
        with patch("weather_alert_bot.weather_forecast.urllib.request.urlopen") as urlopen:
            with self.assertRaises(WeatherForecastError):
                OpenMeteoWeatherClient().fetch(
                    55.75204,
                    37.61781,
                    "Europe/Moscow",
                    forecast_days=4,
                )
        urlopen.assert_not_called()


class WeatherForecastParsingTest(unittest.TestCase):
    def fetch_payload(self, payload: object) -> WeatherForecast:
        with patch(
            "weather_alert_bot.weather_forecast.urllib.request.urlopen",
            return_value=MockResponse(payload),
        ):
            return OpenMeteoWeatherClient().fetch(55.75204, 37.61781, "Europe/Moscow")

    def test_parses_five_daily_and_hourly_values_into_immutable_models(self) -> None:
        result = self.fetch_payload(forecast_payload(hours=4))

        self.assertIsInstance(result, WeatherForecast)
        self.assertIsInstance(result.daily[0], DailyForecast)
        self.assertIsInstance(result.hourly[0], HourlyForecast)
        self.assertEqual(result.latitude, 55.75204)
        self.assertEqual(result.longitude, 37.61781)
        self.assertEqual(result.timezone, "Europe/Moscow")
        self.assertEqual(result.generation_time_ms, 0.42)
        self.assertEqual(len(result.daily), 5)
        self.assertEqual(result.daily[0].date.isoformat(), "2026-08-12")
        self.assertEqual(result.daily[0].temperature_2m_min, 15.0)
        self.assertEqual(result.daily[0].temperature_2m_max, 25.0)
        self.assertEqual(result.daily[0].precipitation_probability_max, 40.0)
        self.assertEqual(result.daily[0].precipitation_sum, 2.5)
        self.assertEqual(result.daily[0].wind_speed_10m_max, 10.0)
        self.assertEqual(result.daily[0].wind_gusts_10m_max, 18.0)
        self.assertEqual(len(result.hourly), 4)
        self.assertEqual(result.hourly[0].time, datetime.fromisoformat("2026-08-12T00:00"))
        self.assertEqual(result.hourly[1].precipitation, 0.1)

        with self.assertRaises(AttributeError):
            result.daily = ()

    def test_null_generation_time_is_allowed_as_optional(self) -> None:
        payload = forecast_payload()
        payload["generationtime_ms"] = None
        self.assertIsNone(self.fetch_payload(payload).generation_time_ms)

    def test_missing_sections_and_required_fields_are_rejected(self) -> None:
        cases: list[dict[str, object]] = []

        missing_daily = forecast_payload()
        missing_daily.pop("daily")
        cases.append(missing_daily)

        missing_hourly = forecast_payload()
        missing_hourly.pop("hourly")
        cases.append(missing_hourly)

        missing_field = forecast_payload()
        del missing_field["daily"]["temperature_2m_max"]  # type: ignore[index]
        cases.append(missing_field)

        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(WeatherForecastError):
                    self.fetch_payload(payload)

    def test_root_shapes_and_api_error_are_rejected_safely(self) -> None:
        for payload in ([], {"daily": None, "hourly": {}}):
            with self.subTest(payload=payload):
                with self.assertRaises(WeatherForecastError):
                    self.fetch_payload(payload)

        with self.assertRaises(WeatherForecastError) as raised:
            self.fetch_payload({"error": True, "reason": "private details"})
        self.assertNotIn("private details", str(raised.exception))

    def test_daily_and_hourly_array_lengths_must_match(self) -> None:
        daily_mismatch = forecast_payload()
        daily_mismatch["daily"]["precipitation_sum"] = [1.0] * 4  # type: ignore[index]
        hourly_mismatch = forecast_payload()
        hourly_mismatch["hourly"]["wind_speed_10m"] = [1.0] * 2  # type: ignore[index]

        for payload in (daily_mismatch, hourly_mismatch):
            with self.subTest(payload=payload):
                with self.assertRaises(WeatherForecastError):
                    self.fetch_payload(payload)

    def test_daily_must_contain_five_days_and_hourly_must_not_be_empty(self) -> None:
        with self.assertRaises(WeatherForecastError):
            self.fetch_payload(forecast_payload(days=4))
        with self.assertRaises(WeatherForecastError):
            self.fetch_payload(forecast_payload(hours=0))

    def test_null_invalid_number_and_invalid_timestamp_are_rejected(self) -> None:
        null_value = forecast_payload()
        null_value["daily"]["temperature_2m_max"][0] = None  # type: ignore[index]
        invalid_number = forecast_payload()
        invalid_number["hourly"]["precipitation"][0] = "rain"  # type: ignore[index]
        nan_value = forecast_payload()
        nan_value["daily"]["temperature_2m_min"][0] = math.nan  # type: ignore[index]
        invalid_daily_time = forecast_payload()
        invalid_daily_time["daily"]["time"][0] = "not-a-date"  # type: ignore[index]
        invalid_hourly_time = forecast_payload()
        invalid_hourly_time["hourly"]["time"][0] = "not-a-timestamp"  # type: ignore[index]

        for payload in (
            null_value,
            invalid_number,
            nan_value,
            invalid_daily_time,
            invalid_hourly_time,
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(WeatherForecastError):
                    self.fetch_payload(payload)

    def test_invalid_coordinates_timezone_and_ranges_are_rejected_before_http(self) -> None:
        invalid_calls = (
            (91, 37.6, "Europe/Moscow"),
            (55.7, 181, "Europe/Moscow"),
            (55.7, 37.6, ""),
            (55.7, 37.6, "Europe/\nMoscow"),
        )
        for arguments in invalid_calls:
            with self.subTest(arguments=arguments):
                with patch("weather_alert_bot.weather_forecast.urllib.request.urlopen") as urlopen:
                    with self.assertRaises(WeatherForecastError):
                        OpenMeteoWeatherClient().fetch(*arguments)
                urlopen.assert_not_called()


class WeatherForecastNetworkErrorTest(unittest.TestCase):
    def assert_safe_error(self, side_effect: BaseException) -> None:
        with patch(
            "weather_alert_bot.weather_forecast.urllib.request.urlopen",
            side_effect=side_effect,
        ) as urlopen:
            with self.assertRaises(WeatherForecastError) as raised:
                OpenMeteoWeatherClient().fetch(55.75204, 37.61781, "Europe/Moscow")
        urlopen.assert_called_once()
        message = str(raised.exception)
        self.assertNotIn("api.open-meteo.com", message)
        self.assertNotIn("internal details", message)
        self.assertNotIn("Traceback", message)

    def test_http_timeout_and_network_errors_are_safe(self) -> None:
        self.assert_safe_error(
            urllib.error.HTTPError(
                "https://api.open-meteo.com/v1/forecast",
                503,
                "internal details",
                None,
                None,
            )
        )
        self.assert_safe_error(TimeoutError("internal details"))
        self.assert_safe_error(urllib.error.URLError("internal details"))

    def test_malformed_json_and_non_success_status_are_safe(self) -> None:
        response = MockResponse(forecast_payload(), status=200)
        response._body = b"not-json"
        with patch(
            "weather_alert_bot.weather_forecast.urllib.request.urlopen",
            return_value=response,
        ):
            with self.assertRaises(WeatherForecastError):
                OpenMeteoWeatherClient().fetch(55.75204, 37.61781, "Europe/Moscow")

        with patch(
            "weather_alert_bot.weather_forecast.urllib.request.urlopen",
            return_value=MockResponse({"error": True}, status=503),
        ):
            with self.assertRaises(WeatherForecastError):
                OpenMeteoWeatherClient().fetch(55.75204, 37.61781, "Europe/Moscow")


if __name__ == "__main__":
    unittest.main()
