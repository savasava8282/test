from datetime import date, datetime, timezone
import unittest
from zoneinfo import ZoneInfo

from weather_alert_bot.geomagnetic_forecast import (
    GeomagneticForecast,
    GeomagneticForecastInterval,
)
from weather_alert_bot.risk_assessment import (
    CurrentDayRiskAssessment,
    RiskAssessmentError,
    RiskAssessmentPolicy,
    assess_current_day_risks,
    format_current_day_risk_assessment,
    g_level_for_kp,
)
from weather_alert_bot.weather_forecast import (
    DailyForecast,
    HourlyForecast,
    WeatherForecast,
)


LOCAL_DATE = date(2026, 8, 12)
FORMATION_TIME = datetime(2026, 8, 11, 21, tzinfo=timezone.utc)


def hourly(
    hour: int = 12,
    *,
    precipitation: float = 0.0,
    temperature: float = 10.0,
    weather_code: int = 0,
    gust: float = 0.0,
) -> HourlyForecast:
    return HourlyForecast(
        time=datetime(2026, 8, 12, hour),
        temperature_2m=temperature,
        precipitation_probability=0.0,
        precipitation=precipitation,
        weather_code=weather_code,
        wind_speed_10m=0.0,
        wind_gusts_10m=gust,
    )


def weather(
    *,
    daily_precipitation: float = 0.0,
    daily_gust: float = 0.0,
    hours: tuple[HourlyForecast, ...] = (),
    extra_daily: tuple[DailyForecast, ...] = (),
) -> WeatherForecast:
    current = DailyForecast(
        date=LOCAL_DATE,
        weather_code=0,
        temperature_2m_max=10.0,
        temperature_2m_min=0.0,
        precipitation_probability_max=0.0,
        precipitation_sum=daily_precipitation,
        wind_speed_10m_max=0.0,
        wind_gusts_10m_max=daily_gust,
    )
    return WeatherForecast(
        latitude=55.0,
        longitude=37.0,
        timezone="Europe/Moscow",
        generation_time_ms=None,
        daily=(current, *extra_daily),
        hourly=hours,
    )


def geomagnetic(*intervals: GeomagneticForecastInterval) -> GeomagneticForecast:
    return GeomagneticForecast(intervals=tuple(intervals))


def kp(
    value: float,
    *,
    timestamp: datetime = datetime(2026, 8, 11, 22),
    status: str = "predicted",
) -> GeomagneticForecastInterval:
    return GeomagneticForecastInterval(
        timestamp=timestamp,
        kp=value,
        status=status,
    )


class RiskAssessmentTest(unittest.TestCase):
    def assess(self, *, current_weather: WeatherForecast | None = None, forecast=None, **kwargs):
        return assess_current_day_risks(
            current_weather or weather(),
            forecast or geomagnetic(),
            "Europe/Moscow",
            FORMATION_TIME,
            **kwargs,
        )

    def categories(self, assessment):
        return tuple(signal.category for signal in assessment.signals)

    def test_local_date_comes_from_city_timezone(self) -> None:
        result = self.assess()
        self.assertEqual(result.local_date, LOCAL_DATE)

    def test_naive_formation_time_is_rejected(self) -> None:
        with self.assertRaises(RiskAssessmentError):
            assess_current_day_risks(weather(), geomagnetic(), "Europe/Moscow", datetime(2026, 8, 12))

    def test_invalid_timezone_is_rejected(self) -> None:
        with self.assertRaises(RiskAssessmentError):
            assess_current_day_risks(weather(), geomagnetic(), "Not/A_Timezone", FORMATION_TIME)

    def test_only_current_local_day_weather_is_used(self) -> None:
        other_day = DailyForecast(
            date=date(2026, 8, 13), weather_code=95, temperature_2m_max=10,
            temperature_2m_min=0, precipitation_probability_max=0,
            precipitation_sum=100, wind_speed_10m_max=0, wind_gusts_10m_max=100,
        )
        result = self.assess(
            current_weather=weather(
                extra_daily=(other_day,),
                hours=(HourlyForecast(
                    time=datetime(2026, 8, 13, 12), temperature_2m=-2,
                    precipitation_probability=0, precipitation=20, weather_code=95,
                    wind_speed_10m=0, wind_gusts_10m=100,
                ),),
            ),
        )
        self.assertEqual(result.signals, ())

    def test_only_current_local_day_kp_is_used(self) -> None:
        result = self.assess(forecast=geomagnetic(kp(8), kp(9, timestamp=datetime(2026, 8, 12, 22))))
        self.assertEqual(self.categories(result), ("magnetic_storm",))
        self.assertIn(": 8 (G4)", result.signals[0].reason)

    def test_all_supported_geomagnetic_statuses_are_used(self) -> None:
        for status in ("observed", "estimated", "predicted"):
            with self.subTest(status=status):
                result = self.assess(forecast=geomagnetic(kp(7, status=status)))
                self.assertEqual(self.categories(result), ("magnetic_storm",))

    def test_unknown_geomagnetic_status_is_ignored(self) -> None:
        result = self.assess(forecast=geomagnetic(kp(9, status="official-warning")))
        self.assertEqual(result.signals, ())

    def test_kp_6_99_does_not_cross_threshold_7(self) -> None:
        result = self.assess(forecast=geomagnetic(kp(6.99)))
        self.assertEqual(result.signals, ())

    def test_kp_7_crosses_threshold(self) -> None:
        result = self.assess(forecast=geomagnetic(kp(7.0)))
        self.assertEqual(self.categories(result), ("magnetic_storm",))

    def test_g_level_mapping(self) -> None:
        for value, expected in ((5, "G1"), (6, "G2"), (7, "G3"), (8, "G4"), (9, "G5")):
            with self.subTest(value=value):
                self.assertEqual(g_level_for_kp(value), expected)

    def test_fractional_kp_is_not_rounded_up(self) -> None:
        self.assertEqual(g_level_for_kp(6.99), "G2")
        result = self.assess(forecast=geomagnetic(kp(6.99)), policy=RiskAssessmentPolicy(magnetic_kp_threshold=6.0))
        self.assertIn("(G2)", result.signals[0].reason)
        self.assertNotIn("G3", result.signals[0].reason)

    def test_daily_heavy_rain_threshold_is_inclusive(self) -> None:
        self.assertEqual(self.categories(self.assess(current_weather=weather(daily_precipitation=30))), ("heavy_rain",))

    def test_daily_heavy_rain_below_threshold_is_ignored(self) -> None:
        self.assertNotIn("heavy_rain", self.categories(self.assess(current_weather=weather(daily_precipitation=29.99))))

    def test_hourly_heavy_rain_threshold_is_inclusive(self) -> None:
        self.assertIn("heavy_rain", self.categories(self.assess(current_weather=weather(hours=(hourly(precipitation=15),)))))

    def test_hourly_heavy_rain_below_threshold_is_ignored(self) -> None:
        self.assertNotIn("heavy_rain", self.categories(self.assess(current_weather=weather(hours=(hourly(precipitation=14.99),)))))

    def test_precipitation_probability_does_not_trigger_heavy_rain(self) -> None:
        item = HourlyForecast(
            time=datetime(2026, 8, 12, 12), temperature_2m=10,
            precipitation_probability=100, precipitation=0, weather_code=0,
            wind_speed_10m=0, wind_gusts_10m=0,
        )
        self.assertNotIn("heavy_rain", self.categories(self.assess(current_weather=weather(hours=(item,)))))

    def test_thunderstorm_codes_are_supported(self) -> None:
        for code in (95, 96, 99):
            with self.subTest(code=code):
                self.assertIn("thunderstorm", self.categories(self.assess(current_weather=weather(hours=(hourly(weather_code=code),)))))

    def test_non_thunderstorm_code_is_ignored(self) -> None:
        self.assertNotIn("thunderstorm", self.categories(self.assess(current_weather=weather(hours=(hourly(weather_code=61),)))))

    def test_freezing_drizzle_codes_are_supported(self) -> None:
        for code in (56, 57):
            with self.subTest(code=code):
                self.assertIn("ice", self.categories(self.assess(current_weather=weather(hours=(hourly(weather_code=code),)))))

    def test_freezing_rain_codes_are_supported(self) -> None:
        for code in (66, 67):
            with self.subTest(code=code):
                self.assertIn("ice", self.categories(self.assess(current_weather=weather(hours=(hourly(weather_code=code),)))))

    def test_positive_precipitation_with_negative_temperature_is_ice_risk(self) -> None:
        result = self.assess(current_weather=weather(hours=(hourly(precipitation=0.1, temperature=-1),)))
        self.assertIn("ice", self.categories(result))
        self.assertIn("Риск условий для гололёда/обледенения", result.signals[0].reason)

    def test_negative_temperature_without_precipitation_is_not_ice(self) -> None:
        self.assertNotIn("ice", self.categories(self.assess(current_weather=weather(hours=(hourly(temperature=-5),)))))

    def test_strong_wind_exactly_72_kmh_is_supported(self) -> None:
        self.assertIn("strong_wind", self.categories(self.assess(current_weather=weather(hours=(hourly(gust=72),)))))

    def test_strong_wind_71_99_kmh_is_ignored(self) -> None:
        self.assertNotIn("strong_wind", self.categories(self.assess(current_weather=weather(hours=(hourly(gust=71.99),)))))

    def test_storm_exactly_90_kmh_is_supported(self) -> None:
        self.assertIn("storm", self.categories(self.assess(current_weather=weather(hours=(hourly(gust=90),)))))

    def test_gust_90_produces_two_independent_signals(self) -> None:
        self.assertEqual(self.categories(self.assess(current_weather=weather(hours=(hourly(gust=90),)))), ("strong_wind", "storm"))

    def test_duplicate_evidence_produces_one_signal_per_category(self) -> None:
        result = self.assess(current_weather=weather(daily_precipitation=30, hours=(hourly(precipitation=15, weather_code=95, gust=90), hourly(precipitation=16, weather_code=96, gust=95))))
        self.assertEqual(len(result.signals), len(set(self.categories(result))))
        self.assertEqual(self.categories(result), ("heavy_rain", "thunderstorm", "strong_wind", "storm"))

    def test_no_detected_signals_has_supported_empty_result(self) -> None:
        result = self.assess()
        self.assertIsInstance(result, CurrentDayRiskAssessment)
        self.assertEqual(result.signals, ())
        self.assertEqual(result.unsupported_categories, ("heat", "cold"))

    def test_custom_policy_thresholds_are_used(self) -> None:
        policy = RiskAssessmentPolicy(
            magnetic_kp_threshold=6.5,
            heavy_rain_daily_mm=40,
            heavy_rain_hourly_mm=20,
            strong_wind_gust_kmh=50,
            storm_gust_kmh=80,
        )
        result = self.assess(
            current_weather=weather(daily_precipitation=40, hours=(hourly(precipitation=20, gust=80),)),
            forecast=geomagnetic(kp(6.5)),
            policy=policy,
        )
        self.assertEqual(self.categories(result), ("magnetic_storm", "heavy_rain", "strong_wind", "storm"))

    def test_storm_reason_records_numeric_only_limitation(self) -> None:
        result = self.assess(current_weather=weather(hours=(hourly(gust=90),)))
        self.assertIn("Официальные regional warnings не подключены", result.signals[-1].reason)

    def test_formatter_has_stable_order_and_unsupported_note(self) -> None:
        result = self.assess(current_weather=weather(hours=(hourly(gust=90, weather_code=95),)))
        text = format_current_day_risk_assessment(result)
        self.assertEqual(text.splitlines()[0], "Дата: 12.08.2026")
        self.assertLess(text.index("- strong_wind"), text.index("- storm"))
        self.assertIn("Не оцениваются на этом этапе: жара, холод", text)
        self.assertNotIn("Сегодня рисков нет", text)


if __name__ == "__main__":
    unittest.main()
