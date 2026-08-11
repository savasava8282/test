import json
import math
from datetime import datetime
import urllib.error
import unittest
from unittest.mock import patch

from weather_alert_bot.geomagnetic_forecast import (
    GeomagneticForecast,
    GeomagneticForecastError,
    GeomagneticForecastInterval,
    NoaaSwpcGeomagneticClient,
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


def kp_record(
    timestamp: object = "2026-08-04T00:00:00",
    kp: object = 4.0,
    observed: object = "observed",
    noaa_scale: object = None,
) -> dict[str, object]:
    return {
        "time_tag": timestamp,
        "kp": kp,
        "observed": observed,
        "noaa_scale": noaa_scale,
    }


def kp_payload(records: list[dict[str, object]] | None = None) -> list[dict[str, object]]:
    return records or [
        kp_record(),
        kp_record("2026-08-04T03:00:00", 3.0),
        kp_record("2026-08-04T09:00:00", 2.33),
    ]


class GeomagneticForecastRequestTest(unittest.TestCase):
    def test_official_endpoint_timeout_and_headers_are_used(self) -> None:
        with patch(
            "weather_alert_bot.geomagnetic_forecast.urllib.request.urlopen",
            return_value=MockResponse(kp_payload()),
        ) as urlopen:
            NoaaSwpcGeomagneticClient().fetch()

        urlopen.assert_called_once()
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://services.swpc.noaa.gov/products/"
            "noaa-planetary-k-index-forecast.json",
        )
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.headers["Accept"], "application/json")
        self.assertEqual(
            request.headers["User-agent"],
            "weather-alert-bot-geomagnetic/0.1",
        )
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 10)


class GeomagneticForecastParsingTest(unittest.TestCase):
    def parse(self, payload: object) -> GeomagneticForecast:
        with patch(
            "weather_alert_bot.geomagnetic_forecast.urllib.request.urlopen",
            return_value=MockResponse(payload),
        ):
            return NoaaSwpcGeomagneticClient().fetch()

    def test_parses_actual_noaa_object_list_and_status(self) -> None:
        result = self.parse(kp_payload())

        self.assertIsInstance(result, GeomagneticForecast)
        self.assertIsInstance(result.intervals[0], GeomagneticForecastInterval)
        self.assertEqual(len(result.intervals), 3)
        self.assertEqual(
            result.intervals[0].timestamp,
            datetime(2026, 8, 4, 0, 0),
        )
        self.assertEqual(result.intervals[0].kp, 4.0)
        self.assertEqual(result.intervals[0].status, "observed")
        self.assertIsNone(result.intervals[0].noaa_scale)
        with self.assertRaises(AttributeError):
            result.intervals = ()

    def test_preserves_fractional_kp_without_rounding(self) -> None:
        result = self.parse(
            [kp_record("2026-08-04T09:00:00", 2.33, "observed", None)]
        )

        self.assertEqual(result.intervals[0].kp, 2.33)

    def test_parses_timestamp_without_inventing_timezone(self) -> None:
        result = self.parse([kp_record()])

        self.assertIsNone(result.intervals[0].timestamp.tzinfo)

    def test_parses_string_noaa_scale_without_business_interpretation(self) -> None:
        result = self.parse([kp_record(noaa_scale="G1")])

        self.assertEqual(result.intervals[0].noaa_scale, "G1")

    def test_root_empty_and_non_object_elements_are_rejected(self) -> None:
        cases: tuple[object, ...] = (
            {},
            "not a list",
            [],
            ["not an object"],
            [[]],
            [["time_tag", "kp", "observed"]],
        )
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(GeomagneticForecastError):
                    self.parse(payload)

    def test_required_fields_are_required(self) -> None:
        for field in ("time_tag", "kp", "observed"):
            record = kp_record()
            del record[field]
            with self.subTest(field=field):
                with self.assertRaises(GeomagneticForecastError):
                    self.parse([record])

    def test_invalid_timestamp_is_rejected(self) -> None:
        for timestamp in ("not-a-timestamp", "2026-08-04", "2026-02-30T00:00:00"):
            with self.subTest(timestamp=timestamp):
                with self.assertRaises(GeomagneticForecastError):
                    self.parse([kp_record(timestamp=timestamp)])

    def test_invalid_kp_types_nan_infinity_and_range_are_rejected(self) -> None:
        values: tuple[object, ...] = (
            None,
            "2.33",
            True,
            math.nan,
            math.inf,
            -0.1,
            9.1,
        )
        for value in values:
            with self.subTest(value=value):
                with self.assertRaises(GeomagneticForecastError):
                    self.parse([kp_record(kp=value)])

    def test_invalid_observed_values_are_rejected(self) -> None:
        for value in (None, True, 1, "", "unknown"):
            with self.subTest(value=value):
                with self.assertRaises(GeomagneticForecastError):
                    self.parse([kp_record(observed=value)])

    def test_invalid_noaa_scale_types_are_rejected(self) -> None:
        for value in (1, True, [], ""):
            with self.subTest(value=value):
                with self.assertRaises(GeomagneticForecastError):
                    self.parse([kp_record(noaa_scale=value)])


class GeomagneticForecastNetworkErrorTest(unittest.TestCase):
    def assert_safe_error(self, side_effect: BaseException) -> None:
        with patch(
            "weather_alert_bot.geomagnetic_forecast.urllib.request.urlopen",
            side_effect=side_effect,
        ) as urlopen:
            with self.assertRaises(GeomagneticForecastError) as raised:
                NoaaSwpcGeomagneticClient().fetch()
        urlopen.assert_called_once()
        self.assertNotIn("internal body", str(raised.exception))
        self.assertNotIn("Traceback", str(raised.exception))

    def test_http_timeout_and_network_errors_are_safe(self) -> None:
        self.assert_safe_error(
            urllib.error.HTTPError(
                NoaaSwpcGeomagneticClient.ENDPOINT,
                503,
                "internal body",
                None,
                None,
            )
        )
        self.assert_safe_error(TimeoutError("internal body"))
        self.assert_safe_error(urllib.error.URLError("internal body"))

    def test_malformed_json_and_non_success_status_are_safe(self) -> None:
        response = MockResponse(kp_payload())
        response._body = b"not-json"
        with patch(
            "weather_alert_bot.geomagnetic_forecast.urllib.request.urlopen",
            return_value=response,
        ):
            with self.assertRaises(GeomagneticForecastError):
                NoaaSwpcGeomagneticClient().fetch()

        with patch(
            "weather_alert_bot.geomagnetic_forecast.urllib.request.urlopen",
            return_value=MockResponse(kp_payload(), status=503),
        ):
            with self.assertRaises(GeomagneticForecastError):
                NoaaSwpcGeomagneticClient().fetch()


if __name__ == "__main__":
    unittest.main()
