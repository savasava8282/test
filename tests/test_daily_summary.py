from datetime import date, datetime, timedelta, timezone
import unittest
from zoneinfo import ZoneInfo

from weather_alert_bot.daily_summary import (
    DAILY_RISK_CATEGORY_MAPPING,
    DailySummary,
    DailySummaryError,
    build_daily_summary,
    format_daily_risk_section,
    format_daily_summary,
)
from weather_alert_bot.geomagnetic_forecast import (
    GeomagneticForecast,
    GeomagneticForecastInterval,
)
from weather_alert_bot.storage import UserSettings
from weather_alert_bot.risk_assessment import (
    CurrentDayRiskAssessment,
    RiskSignal,
)
from weather_alert_bot.weather_forecast import (
    DailyForecast,
    HourlyForecast,
    WeatherForecast,
)


SUMMARY_DATE = date(2026, 8, 11)
FORMED_AT = datetime(2026, 8, 10, 21, 0, tzinfo=timezone.utc)


def settings(timezone_name: str = "Europe/Moscow") -> UserSettings:
    return UserSettings(
        telegram_chat_id=42,
        city_name="Москва",
        latitude=55.75204,
        longitude=37.61781,
        timezone=timezone_name,
    )


def weather(
    *,
    weather_code: int = 61,
    day: date = SUMMARY_DATE,
    precipitation_probability_max: float = 78,
    precipitation_sum: float = 1.1,
    hourly: tuple[HourlyForecast, ...] | None = None,
) -> WeatherForecast:
    if hourly is None:
        hourly = tuple(
            HourlyForecast(
                time=datetime(day.year, day.month, day.day, hour),
                temperature_2m={9: 18.0, 14: 22.0, 15: 24.0}.get(hour, 20.0),
                precipitation_probability={9: 20.0, 14: 78.0, 15: 78.0}.get(hour, 0.0),
                precipitation=0.5 if hour == 14 else 0.0,
                weather_code=weather_code,
                wind_speed_10m=10.0,
                wind_gusts_10m=20.0,
            )
            for hour in (9, 14, 15)
        )
    return WeatherForecast(
        latitude=55.75204,
        longitude=37.61781,
        timezone="Europe/Moscow",
        generation_time_ms=None,
        daily=(
            DailyForecast(
                date=day,
                weather_code=weather_code,
                temperature_2m_max=25.1,
                temperature_2m_min=-2.0,
                precipitation_probability_max=precipitation_probability_max,
                precipitation_sum=precipitation_sum,
                wind_speed_10m_max=14.7,
                wind_gusts_10m_max=43.9,
            ),
        ),
        hourly=hourly,
    )


def geomagnetic(predicted: tuple[float, ...] = (5.67,)) -> GeomagneticForecast:
    intervals = [
        GeomagneticForecastInterval(
            timestamp=datetime(2026, 8, 11, 0),
            kp=2.0,
            status="observed",
        )
    ]
    intervals.extend(
        GeomagneticForecastInterval(
            timestamp=datetime(2026, 8, 11) + timedelta(hours=3 * index),
            kp=value,
            status="predicted",
        )
        for index, value in enumerate(predicted, start=1)
    )
    return GeomagneticForecast(intervals=tuple(intervals))


class DailySummaryBuildTest(unittest.TestCase):
    def test_uses_saved_timezone_to_select_local_date_and_exact_09_15_values(self) -> None:
        result = build_daily_summary(settings(), weather(), geomagnetic(), FORMED_AT)

        self.assertEqual(result.date, SUMMARY_DATE)
        self.assertEqual(result.morning_temperature, 18.0)
        self.assertEqual(result.daytime_temperature, 24.0)
        self.assertEqual(result.formed_at.tzinfo, ZoneInfo("Europe/Moscow"))

    def test_missing_daily_date_is_rejected(self) -> None:
        with self.assertRaises(DailySummaryError):
            build_daily_summary(
                settings(),
                weather(day=date(2026, 8, 12)),
                geomagnetic(),
                FORMED_AT,
            )

    def test_missing_09_or_15_is_rejected(self) -> None:
        for missing_hour in (9, 15):
            hourly = tuple(
                item
                for item in weather().hourly
                if item.time.hour != missing_hour
            )
            with self.subTest(missing_hour=missing_hour):
                with self.assertRaises(DailySummaryError):
                    build_daily_summary(
                        settings(),
                        weather(hourly=hourly),
                        geomagnetic(),
                        FORMED_AT,
                    )

    def test_all_documented_wmo_code_groups_are_supported(self) -> None:
        codes = (
            0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65,
            66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99,
        )
        for code in codes:
            with self.subTest(code=code):
                result = build_daily_summary(
                    settings(), weather(weather_code=code), geomagnetic(), FORMED_AT
                )
                self.assertTrue(result.weather_description)

    def test_unknown_wmo_code_is_rejected(self) -> None:
        with self.assertRaises(DailySummaryError):
            build_daily_summary(settings(), weather(weather_code=999), geomagnetic(), FORMED_AT)

    def test_no_precipitation_has_no_time(self) -> None:
        hourly = tuple(
            HourlyForecast(
                time=datetime(
                    SUMMARY_DATE.year,
                    SUMMARY_DATE.month,
                    SUMMARY_DATE.day,
                    hour,
                ),
                temperature_2m=20.0,
                precipitation_probability=0.0,
                precipitation=0.0,
                weather_code=0,
                wind_speed_10m=1.0,
                wind_gusts_10m=2.0,
            )
            for hour in (9, 15)
        )
        result = build_daily_summary(
            settings(),
            weather(precipitation_probability_max=0, precipitation_sum=0, hourly=hourly),
            geomagnetic(),
            FORMED_AT,
        )
        self.assertIsNone(result.precipitation_time)

    def test_equal_precipitation_probability_uses_earliest_hour(self) -> None:
        result = build_daily_summary(settings(), weather(), geomagnetic(), FORMED_AT)

        self.assertEqual(result.precipitation_time.hour, 14)

    def test_zero_probabilities_fallback_to_first_positive_precipitation(self) -> None:
        hourly = tuple(
            HourlyForecast(
                time=datetime(
                    SUMMARY_DATE.year,
                    SUMMARY_DATE.month,
                    SUMMARY_DATE.day,
                    hour,
                ),
                temperature_2m=20.0,
                precipitation_probability=0.0,
                precipitation=0.4 if hour == 13 else 0.0,
                weather_code=61,
                wind_speed_10m=1.0,
                wind_gusts_10m=2.0,
            )
            for hour in (9, 13, 15)
        )
        result = build_daily_summary(
            settings(),
            weather(precipitation_probability_max=0, precipitation_sum=1, hourly=hourly),
            geomagnetic(),
            FORMED_AT,
        )
        self.assertEqual(result.precipitation_time.hour, 13)

    def test_kp_uses_only_first_eight_predicted_intervals(self) -> None:
        result = build_daily_summary(
            settings(),
            weather(),
            geomagnetic(tuple(float(value) for value in range(1, 10))),
            FORMED_AT,
        )

        self.assertEqual(result.kp_max_24h, 8.0)

    def test_missing_predicted_kp_is_rejected(self) -> None:
        observed_only = GeomagneticForecast(
            intervals=(
                GeomagneticForecastInterval(
                    timestamp=datetime(2026, 8, 11),
                    kp=4.0,
                    status="observed",
                ),
            )
        )
        with self.assertRaises(DailySummaryError):
            build_daily_summary(settings(), weather(), observed_only, FORMED_AT)

    def test_naive_formed_at_is_rejected(self) -> None:
        with self.assertRaises(DailySummaryError):
            build_daily_summary(
                settings(), weather(), geomagnetic(), datetime(2026, 8, 10, 21)
            )


class DailySummaryFormattingTest(unittest.TestCase):
    def test_format_is_stable_and_formats_signs_and_fractional_values(self) -> None:
        summary = DailySummary(
            city_name="Москва",
            date=SUMMARY_DATE,
            weather_description="дождь",
            temperature_min=-2.0,
            temperature_max=25.1,
            morning_temperature=0.0,
            daytime_temperature=24.0,
            precipitation_probability_max=78.0,
            precipitation_time=datetime(2026, 8, 11, 14).time(),
            precipitation_sum=1.1,
            wind_speed_max=14.7,
            wind_gusts_max=43.9,
            kp_max_24h=5.67,
            formed_at=datetime(2026, 8, 11, 7, tzinfo=ZoneInfo("Europe/Moscow")),
        )

        self.assertEqual(
            format_daily_summary(summary),
            "\n".join(
                (
                    "📍 Москва",
                    "📅 11 августа 2026",
                    "",
                    "Погода: дождь",
                    "Температура: -2…+25.1 °C",
                    "Утром: 0 °C",
                    "Днём: +24 °C",
                    "",
                    "Осадки: до 78%, наиболее вероятно около 14:00",
                    "За сутки: 1.1 мм",
                    "",
                    "Ветер: до 14.7 км/ч",
                    "Порывы: до 43.9 км/ч",
                    "",
                    "Магнитная активность: Kp до 5.67 в ближайшие 24 ч",
                    "",
                    "Сводка сформирована: 11.08.2026 07:00",
                )
            ),
        )

    def test_risk_section_no_signals_has_stable_user_facing_text(self) -> None:
        assessment = CurrentDayRiskAssessment(SUMMARY_DATE, ())
        self.assertEqual(
            format_daily_risk_section(assessment, settings()),
            "Риски сегодня: значимых по включённым категориям не выявлено.",
        )

    def test_risk_section_uses_all_display_names_in_detector_order(self) -> None:
        categories = tuple(category for category, _, _ in DAILY_RISK_CATEGORY_MAPPING)
        assessment = CurrentDayRiskAssessment(
            SUMMARY_DATE,
            tuple(RiskSignal(category, "technical reason") for category in categories),
        )
        result = format_daily_risk_section(assessment, settings())
        expected = ["Риски сегодня:"]
        expected.extend(f"• {display_name}" for _, _, display_name in DAILY_RISK_CATEGORY_MAPPING)
        self.assertEqual(result, "\n".join(expected))

    def test_risk_section_filters_each_category_using_explicit_mapping(self) -> None:
        for category, setting_field, display_name in DAILY_RISK_CATEGORY_MAPPING:
            with self.subTest(category=category):
                disabled = settings()
                disabled = UserSettings(
                    **{
                        field: getattr(disabled, field)
                        for field in disabled.__dataclass_fields__
                        if field != setting_field
                    },
                    **{setting_field: False},
                )
                assessment = CurrentDayRiskAssessment(
                    SUMMARY_DATE,
                    (RiskSignal(category, "technical reason"),),
                )
                result = format_daily_risk_section(assessment, disabled)
                self.assertEqual(
                    result,
                    "Риски сегодня: значимых по включённым категориям не выявлено.",
                )
                self.assertNotIn(display_name, result)

    def test_ice_uses_warning_icing_setting_and_disabled_signal_does_not_remove_weather(self) -> None:
        disabled = UserSettings(
            **{
                field: getattr(settings(), field)
                for field in settings().__dataclass_fields__
                if field != "warning_icing_enabled"
            },
            warning_icing_enabled=False,
        )
        risk_section = format_daily_risk_section(
            CurrentDayRiskAssessment(SUMMARY_DATE, (RiskSignal("ice", "technical reason"),)),
            disabled,
        )
        summary = build_daily_summary(disabled, weather(), geomagnetic(), FORMED_AT)
        message = format_daily_summary(summary, risk_section=risk_section)
        self.assertIn("Погода: дождь", message)
        self.assertNotIn("гололёд", message)

    def test_climate_unavailable_note_is_filtered_by_enabled_heat_and_cold(self) -> None:
        assessment = CurrentDayRiskAssessment(SUMMARY_DATE, (), ("heat", "cold"))
        self.assertEqual(
            format_daily_risk_section(assessment, settings()),
            "Риски сегодня: значимых по включённым категориям не выявлено.\n"
            "Временно не оценены: сильная жара, сильный холод.",
        )

        heat_only = UserSettings(
            **{
                field: getattr(settings(), field)
                for field in settings().__dataclass_fields__
                if field != "warning_cold_enabled"
            },
            warning_cold_enabled=False,
        )
        self.assertEqual(
            format_daily_risk_section(assessment, heat_only),
            "Риски сегодня: значимых по включённым категориям не выявлено.\n"
            "Временно не оценены: сильная жара.",
        )

    def test_urgent_and_daily_sending_preferences_do_not_filter_manual_risks(self) -> None:
        manual_only = UserSettings(
            **{
                field: getattr(settings(), field)
                for field in settings().__dataclass_fields__
                if field not in {"urgent_warnings_enabled", "daily_sending_enabled"}
            },
            urgent_warnings_enabled=False,
            daily_sending_enabled=False,
        )
        result = format_daily_risk_section(
            CurrentDayRiskAssessment(
                SUMMARY_DATE,
                (RiskSignal("strong_wind", "technical reason"),),
            ),
            manual_only,
        )
        self.assertEqual(result, "Риски сегодня:\n• сильный ветер")

    def test_risk_section_is_deterministic(self) -> None:
        assessment = CurrentDayRiskAssessment(
            SUMMARY_DATE,
            (
                RiskSignal("storm", "technical reason"),
                RiskSignal("magnetic_storm", "technical reason"),
                RiskSignal("heat", "technical reason"),
            ),
        )
        first = format_daily_risk_section(assessment, settings())
        second = format_daily_risk_section(assessment, settings())
        self.assertEqual(first, second)
