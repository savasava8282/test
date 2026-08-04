import io
import json
import unittest
import urllib.error
import urllib.parse
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

from weather_alert_bot.app import main
from weather_alert_bot.geocoding import (
    GeocodingError,
    GeocodingLocation,
    OpenMeteoGeocodingClient,
)


def location_payload(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "id": 524901,
        "name": "Москва",
        "latitude": 55.75222,
        "longitude": 37.61556,
        "timezone": "Europe/Moscow",
        "country_code": "RU",
        "country": "Россия",
        "admin1": "Москва",
        "population": 10381222,
    }
    result.update(overrides)
    return result


class MockResponse:
    def __init__(self, payload: object, *, status: int = 200) -> None:
        self.status = status
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self) -> "MockResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status


class GeocodingClientRequestTest(unittest.TestCase):
    def test_request_is_encoded_and_has_safe_headers(self) -> None:
        response = MockResponse({"results": []})
        with patch(
            "weather_alert_bot.geocoding.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            result = OpenMeteoGeocodingClient().search("  Санкт-Петербург  ")

        self.assertEqual(result, ())
        urlopen.assert_called_once()
        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(
            request.full_url.split("?", 1)[0],
            "https://geocoding-api.open-meteo.com/v1/search",
        )
        encoded_query = request.full_url.split("?", 1)[1]
        self.assertIn("%D0", encoded_query)
        query = urllib.parse.parse_qs(encoded_query)
        self.assertEqual(query["name"], ["Санкт-Петербург"])
        self.assertEqual(query["count"], ["5"])
        self.assertEqual(query["language"], ["ru"])
        self.assertEqual(query["format"], ["json"])
        self.assertEqual(request.headers["Accept"], "application/json")
        self.assertEqual(request.headers["User-agent"], "weather-alert-bot-geocoder/0.1")
        self.assertNotIn("key", request.full_url.lower())
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 10)

    def test_custom_count_limits_results_and_one_request_is_made(self) -> None:
        response = MockResponse({"results": [location_payload(id=index) for index in range(4)]})
        with patch(
            "weather_alert_bot.geocoding.urllib.request.urlopen",
            return_value=response,
        ) as urlopen:
            result = OpenMeteoGeocodingClient().search("Москва", count=2)

        self.assertEqual(len(result), 2)
        self.assertEqual(urlopen.call_count, 1)


class GeocodingInputTest(unittest.TestCase):
    def test_invalid_queries_are_rejected_without_http(self) -> None:
        invalid_queries = (
            "",
            "   ",
            "Я",
            "A" * 101,
            "12345",
            "Москва\nЦентр",
            "Москва\tЦентр",
            "/start",
        )
        for query in invalid_queries:
            with self.subTest(query=query):
                with patch("weather_alert_bot.geocoding.urllib.request.urlopen") as urlopen:
                    with self.assertRaises(GeocodingError):
                        OpenMeteoGeocodingClient().search(query)
                urlopen.assert_not_called()

    def test_valid_examples_are_accepted(self) -> None:
        with patch(
            "weather_alert_bot.geocoding.urllib.request.urlopen",
            return_value=MockResponse({"results": []}),
        ):
            for query in (
                "Москва",
                "Санкт-Петербург",
                "New York",
                "'s-Hertogenbosch",
                "Ростов-на-Дону",
            ):
                with self.subTest(query=query):
                    OpenMeteoGeocodingClient().search(query)


class GeocodingResponseTest(unittest.TestCase):
    def search_payload(self, payload: object) -> tuple[GeocodingLocation, ...]:
        with patch(
            "weather_alert_bot.geocoding.urllib.request.urlopen",
            return_value=MockResponse(payload),
        ):
            return OpenMeteoGeocodingClient().search("Москва")

    def test_one_localized_result_and_optional_fields(self) -> None:
        result = self.search_payload(
            {"results": [location_payload(name="Москва", country="Россия")]}
        )
        self.assertEqual(
            result,
            (
                GeocodingLocation(
                    id=524901,
                    name="Москва",
                    latitude=55.75222,
                    longitude=37.61556,
                    timezone="Europe/Moscow",
                    country_code="RU",
                    country="Россия",
                    admin1="Москва",
                    population=10381222,
                ),
            ),
        )

        result_without_optional = self.search_payload(
            {"results": [location_payload(admin1=None, population=None)]}
        )
        self.assertIsNone(result_without_optional[0].admin1)
        self.assertIsNone(result_without_optional[0].population)

    def test_empty_or_missing_results_means_no_matches(self) -> None:
        self.assertEqual(self.search_payload({"results": []}), ())
        self.assertEqual(self.search_payload({}), ())

    def test_coordinate_boundaries_are_allowed(self) -> None:
        result = self.search_payload(
            {
                "results": [
                    location_payload(latitude=-90, longitude=-180),
                    location_payload(id=2, latitude=90, longitude=180),
                ]
            }
        )
        self.assertEqual((result[0].latitude, result[0].longitude), (-90.0, -180.0))
        self.assertEqual((result[1].latitude, result[1].longitude), (90.0, 180.0))

    def test_invalid_json_and_top_level_shapes_are_rejected(self) -> None:
        with patch(
            "weather_alert_bot.geocoding.urllib.request.urlopen",
            return_value=MockResponse({"results": []}),
        ) as urlopen:
            urlopen.return_value._body = b"not-json"
            with self.assertRaises(GeocodingError):
                OpenMeteoGeocodingClient().search("Москва")

        with self.assertRaises(GeocodingError):
            self.search_payload([])
        with self.assertRaises(GeocodingError):
            self.search_payload({"results": {}})

    def test_invalid_results_are_rejected(self) -> None:
        invalid_payloads = (
            {"results": [{}]},
            {"results": [location_payload(latitude=91)]},
            {"results": [location_payload(longitude=-181)]},
            {"results": [location_payload(id=True)]},
            {"results": [location_payload(latitude="55")]},
            {"results": [location_payload(population="many")]},
            {"results": [location_payload(admin1=42)]},
            {"results": ["not an object"]},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(GeocodingError):
                    self.search_payload(payload)

    def test_api_error_is_safe(self) -> None:
        with self.assertRaises(GeocodingError) as raised:
            self.search_payload({"error": True, "reason": "internal details"})
        self.assertEqual(str(raised.exception), "Сервис геокодирования вернул ошибку.")


class GeocodingNetworkErrorTest(unittest.TestCase):
    def assert_safe_error(self, side_effect: BaseException) -> None:
        with patch(
            "weather_alert_bot.geocoding.urllib.request.urlopen",
            side_effect=side_effect,
        ) as urlopen:
            with self.assertRaises(GeocodingError) as raised:
                OpenMeteoGeocodingClient().search("Москва")
        urlopen.assert_called_once()
        message = str(raised.exception)
        self.assertNotIn("geocoding-api.open-meteo.com", message)
        self.assertNotIn("Москва", message)
        self.assertNotIn("internal details", message)
        self.assertNotIn("Traceback", message)

    def test_http_error(self) -> None:
        self.assert_safe_error(
            urllib.error.HTTPError(
                "https://geocoding-api.open-meteo.com/v1/search?name=%D0%9C%D0%BE%D1%81%D0%BA%D0%B2%D0%B0",
                503,
                "internal details",
                None,
                None,
            )
        )

    def test_url_error_and_timeout(self) -> None:
        self.assert_safe_error(urllib.error.URLError("internal details"))
        self.assert_safe_error(TimeoutError("internal details"))

    def test_non_2xx_response_is_safe(self) -> None:
        with patch(
            "weather_alert_bot.geocoding.urllib.request.urlopen",
            return_value=MockResponse({"error": True}, status=503),
        ):
            with self.assertRaises(GeocodingError) as raised:
                OpenMeteoGeocodingClient().search("Москва")
        self.assertNotIn("Москва", str(raised.exception))
        self.assertNotIn("https://", str(raised.exception))


class GeocodingCliTest(unittest.TestCase):
    def test_success_output_skips_missing_region_and_hides_internal_fields(self) -> None:
        client = Mock()
        client.search.return_value = (
            GeocodingLocation(
                id=1,
                name="Москва",
                latitude=55.75222222,
                longitude=37.61556666,
                timezone="Europe/Moscow",
                country_code="RU",
                country="Россия",
                admin1=None,
                population=100,
            ),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("weather_alert_bot.app.OpenMeteoGeocodingClient", return_value=client):
            with patch("weather_alert_bot.app.load_settings") as load_settings:
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    return_code = main(["--geocode-city", "  Москва  "])

        self.assertEqual(return_code, 0)
        client.search.assert_called_once_with("Москва")
        load_settings.assert_not_called()
        self.assertEqual(
            stdout.getvalue(),
            "Найденные варианты:\n"
            "1. Москва, Россия — 55.752222, 37.615567 — Europe/Moscow\n"
            "Источник геокодирования: Open-Meteo; данные о локациях: GeoNames.\n",
        )
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn("\"id\"", stdout.getvalue())
        self.assertNotIn("100", stdout.getvalue())
        self.assertNotIn("http", stdout.getvalue().lower())

    def test_no_matches_returns_two(self) -> None:
        client = Mock()
        client.search.return_value = ()
        stdout = io.StringIO()
        with patch("weather_alert_bot.app.OpenMeteoGeocodingClient", return_value=client):
            with redirect_stdout(stdout):
                return_code = main(["--geocode-city", "Москва"])
        self.assertEqual(return_code, 2)
        self.assertEqual(stdout.getvalue(), "Подходящие города не найдены.\n")

    def test_error_returns_one_without_unsafe_output(self) -> None:
        client = Mock()
        client.search.side_effect = GeocodingError("безопасная ошибка")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("weather_alert_bot.app.OpenMeteoGeocodingClient", return_value=client):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                return_code = main(["--geocode-city", "Москва"])
        self.assertEqual(return_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "Ошибка геокодирования: безопасная ошибка\n")
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
