from datetime import date, datetime, timedelta, timezone
import io
import json
import math
import unittest
from unittest.mock import patch

from weather_alert_bot.climate_normals import (
    BASELINE_END,
    BASELINE_START,
    ClimateNormalDay,
    ClimateNormalsError,
    OpenMeteoHistoricalWeatherClient,
    HistoricalTemperatureDay,
    calculate_climate_normals,
    calculate_temperature_deviation,
    format_climate_normal,
    get_climate_normal_for_date,
    local_calendar_date,
)


def all_dates() -> tuple[date, ...]:
    return tuple(
        BASELINE_START + timedelta(days=offset)
        for offset in range((BASELINE_END - BASELINE_START).days + 1)
    )


def complete_records() -> tuple[HistoricalTemperatureDay, ...]:
    return tuple(
        HistoricalTemperatureDay(
            current_date,
            100.0 if (current_date.month, current_date.day) == (2, 29) else float(current_date.month),
            110.0 if (current_date.month, current_date.day) == (2, 29) else float(current_date.month + 10),
        )
        for current_date in all_dates()
    )


def payload_for(*, dates: tuple[str, ...] = ("1991-01-01",)) -> dict[str, object]:
    return {
        "latitude": 55.75,
        "longitude": 37.62,
        "timezone": "Europe/Moscow",
        "daily": {
            "time": list(dates),
            "temperature_2m_min": [1.0] * len(dates),
            "temperature_2m_max": [2.0] * len(dates),
        },
    }


class FakeResponse:
    status = 200

    def __init__(self, body: object) -> None:
        self.body = json.dumps(body).encode()

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class ClimateNormalsHttpTest(unittest.TestCase):
    def test_request_has_exact_endpoint_period_model_timezone_daily_fields_and_celsius(self) -> None:
        response = FakeResponse(payload_for())
        with patch(
            "weather_alert_bot.climate_normals.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            OpenMeteoHistoricalWeatherClient().fetch(55.75, 37.62, "Europe/Moscow")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url.split("?", 1)[0], OpenMeteoHistoricalWeatherClient.ENDPOINT)
        from urllib.parse import parse_qs, urlparse

        query = parse_qs(urlparse(request.full_url).query)
        self.assertEqual(query["start_date"], ["1991-01-01"])
        self.assertEqual(query["end_date"], ["2020-12-31"])
        self.assertEqual(query["models"], ["era5_land"])
        self.assertEqual(query["timezone"], ["Europe/Moscow"])
        self.assertEqual(query["daily"], ["temperature_2m_min,temperature_2m_max"])
        self.assertEqual(query["temperature_unit"], ["celsius"])
        urlopen.assert_called_once_with(request, timeout=15)

    def test_valid_historical_parsing_is_immutable(self) -> None:
        parsed = OpenMeteoHistoricalWeatherClient._parse_historical_response(
            payload_for(dates=("1991-01-01", "2020-12-31"))
        )
        self.assertEqual(parsed[0], HistoricalTemperatureDay(date(1991, 1, 1), 1.0, 2.0))
        self.assertIsInstance(parsed, tuple)
        with self.assertRaises((TypeError, AttributeError)):
            parsed[0].temperature_min = 3.0  # type: ignore[misc]

    def test_timeout_and_url_error_are_safe(self) -> None:
        import urllib.error

        for error in (TimeoutError(), urllib.error.URLError("private reason")):
            with self.subTest(error=type(error).__name__):
                with patch(
                    "weather_alert_bot.climate_normals.urllib.request.urlopen",
                    side_effect=error,
                ):
                    with self.assertRaises(ClimateNormalsError) as raised:
                        OpenMeteoHistoricalWeatherClient().fetch(55, 37, "UTC")
                self.assertNotIn("private reason", str(raised.exception))

    def test_api_error_non_object_json_and_http_timeout_are_safe(self) -> None:
        client = OpenMeteoHistoricalWeatherClient()
        with self.assertRaises(ClimateNormalsError) as raised:
            client._parse_historical_response({"error": True})
        self.assertNotIn("secret", str(raised.exception))

        with patch(
            "weather_alert_bot.climate_normals.urllib.request.urlopen",
            return_value=FakeResponse(["not", "object"]),
        ):
            with self.assertRaises(ClimateNormalsError):
                client.fetch(55, 37, "UTC")

        import urllib.error

        with patch(
            "weather_alert_bot.climate_normals.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError("url", 500, "private", {}, io.BytesIO()),
        ):
            with self.assertRaises(ClimateNormalsError) as raised:
                client.fetch(55, 37, "UTC")
        self.assertNotIn("private", str(raised.exception))


class ClimateNormalsValidationTest(unittest.TestCase):
    def assert_invalid_payload(self, payload: dict[str, object]) -> None:
        with self.assertRaises(ClimateNormalsError):
            OpenMeteoHistoricalWeatherClient._parse_historical_response(payload)

    def test_missing_daily_and_arrays_and_mismatched_arrays(self) -> None:
        base = payload_for()
        base.pop("daily")
        self.assert_invalid_payload(base)
        for field in ("time", "temperature_2m_min", "temperature_2m_max"):
            missing = payload_for()
            missing["daily"] = dict(missing["daily"])  # type: ignore[arg-type]
            missing["daily"].pop(field)  # type: ignore[union-attr]
            self.assert_invalid_payload(missing)
        mismatch = payload_for(dates=("1991-01-01", "1991-01-02"))
        mismatch["daily"]["temperature_2m_max"] = [2.0]  # type: ignore[index]
        self.assert_invalid_payload(mismatch)

    def test_invalid_dates_duplicates_and_outside_baseline(self) -> None:
        for value in ("bad", "1991-02-30", "19910101", None):
            payload = payload_for()
            payload["daily"]["time"] = [value]  # type: ignore[index]
            self.assert_invalid_payload(payload)
        for value in ("1991-01-01", "2020-12-31"):
            payload = payload_for(dates=(value, value))
            self.assert_invalid_payload(payload)
        for value in ("1990-12-31", "2021-01-01"):
            self.assert_invalid_payload(payload_for(dates=(value,)))

    def test_null_bool_nan_infinity_and_min_above_max_are_rejected(self) -> None:
        for field, value in (
            ("temperature_2m_min", None),
            ("temperature_2m_min", True),
            ("temperature_2m_min", math.nan),
            ("temperature_2m_max", math.inf),
        ):
            payload = payload_for()
            payload["daily"][field] = [value]  # type: ignore[index]
            self.assert_invalid_payload(payload)
        payload = payload_for()
        payload["daily"]["temperature_2m_min"] = [3.0]  # type: ignore[index]
        self.assert_invalid_payload(payload)

    def test_missing_one_ordinary_date_is_rejected_by_calculation(self) -> None:
        records = complete_records()
        missing = records[:-1]
        with self.assertRaises(ClimateNormalsError):
            calculate_climate_normals(missing, 55, 37, "UTC")


class ClimateNormalsCalculationTest(unittest.TestCase):
    def test_grouping_means_counts_order_and_leap_day_are_exact(self) -> None:
        records = list(complete_records())
        records[0] = HistoricalTemperatureDay(date(1991, 1, 1), 0, 10)
        records[365] = HistoricalTemperatureDay(date(1992, 1, 1), 2, 12)
        records[59] = HistoricalTemperatureDay(date(1991, 3, 1), 30, 40)
        normals = calculate_climate_normals(records, 55.75, 37.62, "Europe/Moscow")

        self.assertEqual(normals.days[0].month, 1)
        self.assertEqual((normals.days[0].month, normals.days[0].day), (1, 1))
        self.assertEqual((normals.days[-1].month, normals.days[-1].day), (12, 31))
        jan_1 = get_climate_normal_for_date(normals, date(2005, 1, 1))
        self.assertEqual(jan_1.sample_count, 30)
        self.assertAlmostEqual(jan_1.normal_temperature_min, (0 + 2 + 28 * 1) / 30)
        self.assertAlmostEqual(jan_1.normal_temperature_max, (10 + 12 + 28 * 11) / 30)

        feb_28 = get_climate_normal_for_date(normals, date(2020, 2, 28))
        feb_29 = get_climate_normal_for_date(normals, date(2020, 2, 29))
        self.assertEqual(feb_28.sample_count, 30)
        self.assertEqual(feb_29.sample_count, 8)
        self.assertEqual((feb_28.month, feb_28.day), (2, 28))
        self.assertEqual((feb_29.month, feb_29.day), (2, 29))
        self.assertNotEqual(feb_28.normal_temperature_min, feb_29.normal_temperature_min)

    def test_complete_dates_are_required_and_result_is_immutable(self) -> None:
        normals = calculate_climate_normals(complete_records(), 55, 37, "UTC")
        self.assertEqual(normals.period_start, BASELINE_START)
        self.assertEqual(normals.period_end, BASELINE_END)
        self.assertEqual(len(normals.days), 366)
        with self.assertRaises((TypeError, AttributeError)):
            normals.days = ()  # type: ignore[misc]

    def test_lookup_missing_and_deviation_have_no_threshold_logic(self) -> None:
        normals = calculate_climate_normals(complete_records(), 55, 37, "UTC")
        with self.assertRaises(ClimateNormalsError):
            get_climate_normal_for_date(
                normals.__class__(55, 37, "UTC", BASELINE_START, BASELINE_END, ()),
                date(2020, 2, 29),
            )
        normal = get_climate_normal_for_date(normals, date(2020, 2, 29))
        deviation = calculate_temperature_deviation(normal, normal.normal_temperature_min + 7, normal.normal_temperature_max - 7)
        self.assertEqual(deviation.min_deviation, 7)
        self.assertEqual(deviation.max_deviation, -7)

    def test_formatter_is_stable(self) -> None:
        normals = calculate_climate_normals(complete_records(), 55, 37, "UTC")
        self.assertEqual(
            format_climate_normal(normals, date(2026, 8, 12)),
            "\n".join(
                (
                    "Климатическая норма: 12 августа",
                    "Период: 1991–2020",
                    "Источник: Open-Meteo ERA5-Land",
                    "",
                    "Обычный минимум: +8.0 °C",
                    "Обычный максимум: +18.0 °C",
                    "Наблюдений: 30",
                )
            ),
        )

    def test_local_date_requires_aware_time_and_valid_timezone(self) -> None:
        current = datetime(2026, 8, 11, 21, tzinfo=timezone.utc)
        self.assertEqual(local_calendar_date(current, "Europe/Moscow"), date(2026, 8, 12))
        for invalid in (datetime(2026, 8, 11, 21), datetime(2026, 8, 11, 21, tzinfo=timezone.utc)):
            timezone_name = "No/Such_Zone" if invalid.tzinfo is not None else "UTC"
            if invalid.tzinfo is None or timezone_name != "No/Such_Zone":
                with self.assertRaises(ClimateNormalsError):
                    local_calendar_date(invalid, timezone_name)
        with self.assertRaises(ClimateNormalsError):
            local_calendar_date(current, "No/Such_Zone")


if __name__ == "__main__":
    unittest.main()
