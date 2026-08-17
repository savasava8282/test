import argparse
from datetime import datetime, timezone
from threading import Event
import signal
import sys
from collections.abc import Sequence

from weather_alert_bot.city_handler import run_until_city
from weather_alert_bot.climate_cache import (
    ClimateCacheError,
    SQLiteClimateNormalsCache,
    get_or_create_climate_normals,
    refresh_climate_normals,
)
from weather_alert_bot.climate_normals import (
    BASELINE_END,
    BASELINE_START,
    ClimateNormalsError,
    OpenMeteoHistoricalWeatherClient,
    calculate_climate_normals,
    format_climate_normal,
    get_climate_normal_for_date,
    local_calendar_date,
)
from weather_alert_bot.config import ConfigError, load_settings
from weather_alert_bot.confirmed_city_handler import run_until_confirmed_city
from weather_alert_bot.daily_days_handler import run_until_daily_days
from weather_alert_bot.daily_dispatch import (
    DailyDispatchError,
    evaluate_daily_dispatch_due,
    run_daily_dispatch_once,
)
from weather_alert_bot.daily_sending_handler import run_until_daily_sending
from weather_alert_bot.daily_time_handler import run_until_daily_time
from weather_alert_bot.daily_summary import (
    DailySummaryError,
    build_daily_summary,
    format_daily_summary,
)
from weather_alert_bot.geocoding import GeocodingError, OpenMeteoGeocodingClient
from weather_alert_bot.geocoded_city_handler import run_until_geocoded_city
from weather_alert_bot.geomagnetic_forecast import (
    GeomagneticForecastError,
    NoaaSwpcGeomagneticClient,
)
from weather_alert_bot.onboarding_complete_handler import run_until_onboarding_complete
from weather_alert_bot.risk_assessment import (
    RiskAssessmentError,
    assess_current_day_risks,
    format_current_day_risk_assessment,
)
from weather_alert_bot.runtime_state import RuntimeStateError, SQLiteRuntimeStateStore
from weather_alert_bot.scheduler import run_scheduler_loop
from weather_alert_bot.settings_summary_handler import run_until_settings_summary
from weather_alert_bot.storage import SQLiteSettingsStore, StorageError
from weather_alert_bot.start_handler import run_until_start
from weather_alert_bot.today_handler import run_until_today
from weather_alert_bot.telegram_api import TelegramApiError, TelegramClient
from weather_alert_bot.urgent_warnings_handler import run_until_urgent_warnings
from weather_alert_bot.warning_categories_handler import run_until_warning_categories
from weather_alert_bot.weather_forecast import (
    OpenMeteoWeatherClient,
    WeatherForecastError,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the minimal application entry point."""
    parser = argparse.ArgumentParser(description="Каркас погодного бота")
    telegram_group = parser.add_mutually_exclusive_group()
    telegram_group.add_argument(
        "--check-telegram",
        action="store_true",
        help="проверить токен и получить идентичность бота",
    )
    telegram_group.add_argument(
        "--wait-for-start",
        action="store_true",
        help="дождаться одной новой команды /start и ответить",
    )
    telegram_group.add_argument(
        "--wait-for-city",
        action="store_true",
        help="дождаться новой /start и одного названия города",
    )
    telegram_group.add_argument(
        "--wait-for-geocoded-city",
        action="store_true",
        help="дождаться города, проверить его через Open-Meteo и завершиться",
    )
    telegram_group.add_argument(
        "--wait-for-confirmed-city",
        action="store_true",
        help="дождаться города, показать первый результат и получить подтверждение",
    )
    telegram_group.add_argument(
        "--wait-for-daily-time",
        action="store_true",
        help="настроить время ежедневной отправки для сохранённого города",
    )
    telegram_group.add_argument(
        "--wait-for-daily-days",
        action="store_true",
        help="настроить дни ежедневной отправки для сохранённого города",
    )
    telegram_group.add_argument(
        "--wait-for-daily-sending",
        action="store_true",
        help="включить или выключить ежедневную рассылку для сохранённого города",
    )
    telegram_group.add_argument(
        "--wait-for-urgent-warnings",
        action="store_true",
        help="настроить срочные предупреждения для сохранённого города",
    )
    telegram_group.add_argument(
        "--wait-for-warning-categories",
        action="store_true",
        help="настроить категории предупреждений для сохранённого города",
    )
    telegram_group.add_argument(
        "--wait-for-settings-summary",
        action="store_true",
        help="показать итоговые настройки сохранённого города",
    )
    telegram_group.add_argument(
        "--wait-for-onboarding-complete",
        action="store_true",
        help="подтвердить итоговые настройки и завершить первоначальную настройку",
    )
    telegram_group.add_argument(
        "--fetch-weather-forecast",
        action="store_true",
        help="получить диагностический прогноз для единственного сохранённого города",
    )
    telegram_group.add_argument(
        "--fetch-kp-forecast",
        action="store_true",
        help="получить диагностический прогноз планетарного индекса Kp NOAA SWPC",
    )
    telegram_group.add_argument(
        "--preview-daily-summary",
        action="store_true",
        help="сформировать диагностическую ежедневную сводку без Telegram",
    )
    telegram_group.add_argument(
        "--preview-current-risks",
        action="store_true",
        help="сформировать диагностическую оценку рисков текущего дня без Telegram",
    )
    telegram_group.add_argument(
        "--preview-climate-normal",
        action="store_true",
        help="показать климатическую норму текущего календарного дня без Telegram",
    )
    telegram_group.add_argument(
        "--refresh-climate-cache",
        action="store_true",
        help="обновить сохранённую климатическую норму без Telegram",
    )
    telegram_group.add_argument(
        "--wait-for-today",
        action="store_true",
        help="дождаться одной новой команды /today владельца и отправить сводку",
    )
    telegram_group.add_argument(
        "--run-daily-dispatch-once",
        action="store_true",
        help="однократно проверить расписание и отправить ежедневную сводку при необходимости",
    )
    telegram_group.add_argument(
        "--run-scheduler",
        action="store_true",
        help="запустить постоянный foreground-планировщик ежедневной рассылки",
    )
    telegram_group.add_argument(
        "--geocode-city",
        metavar="CITY",
        help="однократно найти город через Open-Meteo",
    )
    args = parser.parse_args(argv)

    if args.check_telegram:
        return _check_telegram()
    if args.wait_for_start:
        return _wait_for_start()
    if args.wait_for_city:
        return _wait_for_city()
    if args.wait_for_geocoded_city:
        return _wait_for_geocoded_city()
    if args.wait_for_confirmed_city:
        return _wait_for_confirmed_city()
    if args.wait_for_daily_time:
        return _wait_for_daily_time()
    if args.wait_for_daily_days:
        return _wait_for_daily_days()
    if args.wait_for_daily_sending:
        return _wait_for_daily_sending()
    if args.wait_for_urgent_warnings:
        return _wait_for_urgent_warnings()
    if args.wait_for_warning_categories:
        return _wait_for_warning_categories()
    if args.wait_for_settings_summary:
        return _wait_for_settings_summary()
    if args.wait_for_onboarding_complete:
        return _wait_for_onboarding_complete()
    if args.fetch_weather_forecast:
        return _fetch_weather_forecast()
    if args.fetch_kp_forecast:
        return _fetch_kp_forecast()
    if args.preview_daily_summary:
        return _preview_daily_summary()
    if args.preview_current_risks:
        return _preview_current_risks()
    if args.preview_climate_normal:
        return _preview_climate_normal()
    if args.refresh_climate_cache:
        return _refresh_climate_cache()
    if args.wait_for_today:
        return _wait_for_today()
    if args.run_daily_dispatch_once:
        return _run_daily_dispatch_once()
    if args.run_scheduler:
        return _run_scheduler()
    if args.geocode_city is not None:
        return _geocode_city(args.geocode_city)

    load_settings(require_telegram_token=False)
    print("Каркас погодного бота готов.")
    return 0


def _wait_for_start() -> int:
    try:
        settings = load_settings(require_telegram_token=True)
        if settings.telegram_bot_token is None:
            raise TelegramApiError("Токен Telegram не задан.")

        client = TelegramClient(settings.telegram_bot_token)
        return run_until_start(client)
    except (ConfigError, TelegramApiError) as exc:
        print(f"Ошибка ожидания /start: {exc}", file=sys.stderr)
        return 1


def _wait_for_city() -> int:
    try:
        settings = load_settings(require_telegram_token=True)
        if settings.telegram_bot_token is None:
            raise TelegramApiError("Токен Telegram не задан.")

        client = TelegramClient(settings.telegram_bot_token)
        return run_until_city(client)
    except (ConfigError, TelegramApiError) as exc:
        print(f"Ошибка ожидания города: {exc}", file=sys.stderr)
        return 1


def _wait_for_geocoded_city() -> int:
    try:
        settings = load_settings(require_telegram_token=True)
        if settings.telegram_bot_token is None:
            raise TelegramApiError("Токен Telegram не задан.")

        telegram_client = TelegramClient(settings.telegram_bot_token)
        geocoding_client = OpenMeteoGeocodingClient()
        return run_until_geocoded_city(telegram_client, geocoding_client)
    except (ConfigError, TelegramApiError) as exc:
        print(f"Ошибка ожидания города с геокодированием: {exc}", file=sys.stderr)
        return 1


def _wait_for_confirmed_city() -> int:
    try:
        settings = load_settings(require_telegram_token=True)
        if settings.telegram_bot_token is None:
            raise TelegramApiError("Токен Telegram не задан.")

        telegram_client = TelegramClient(settings.telegram_bot_token)
        geocoding_client = OpenMeteoGeocodingClient()
        storage = SQLiteSettingsStore(settings.db_path)
        return run_until_confirmed_city(telegram_client, geocoding_client, storage)
    except ConfigError as exc:
        print(f"Ошибка ожидания подтверждённого города: {exc}", file=sys.stderr)
        return 1
    except StorageError:
        print("Ошибка ожидания подтверждённого города.", file=sys.stderr)
        return 1
    except TelegramApiError:
        print("Ошибка ожидания подтверждённого города.", file=sys.stderr)
        return 1


def _wait_for_daily_time() -> int:
    try:
        settings = load_settings(require_telegram_token=True)
        if settings.telegram_bot_token is None:
            raise TelegramApiError("Токен Telegram не задан.")

        telegram_client = TelegramClient(settings.telegram_bot_token)
        storage = SQLiteSettingsStore(settings.db_path)
        return run_until_daily_time(telegram_client, storage)
    except ConfigError:
        print("Ошибка настройки времени ежедневной отправки.", file=sys.stderr)
        return 1
    except StorageError:
        print("Ошибка настройки времени ежедневной отправки.", file=sys.stderr)
        return 1
    except TelegramApiError:
        print("Ошибка настройки времени ежедневной отправки.", file=sys.stderr)
        return 1


def _wait_for_daily_days() -> int:
    try:
        settings = load_settings(require_telegram_token=True)
        if settings.telegram_bot_token is None:
            raise TelegramApiError("Токен Telegram не задан.")

        telegram_client = TelegramClient(settings.telegram_bot_token)
        storage = SQLiteSettingsStore(settings.db_path)
        return run_until_daily_days(telegram_client, storage)
    except ConfigError:
        print("Ошибка настройки дней ежедневной отправки.", file=sys.stderr)
        return 1
    except StorageError:
        print("Ошибка настройки дней ежедневной отправки.", file=sys.stderr)
        return 1
    except TelegramApiError:
        print("Ошибка настройки дней ежедневной отправки.", file=sys.stderr)
        return 1


def _wait_for_daily_sending() -> int:
    try:
        settings = load_settings(require_telegram_token=True)
        if settings.telegram_bot_token is None:
            raise TelegramApiError("Токен Telegram не задан.")

        telegram_client = TelegramClient(settings.telegram_bot_token)
        storage = SQLiteSettingsStore(settings.db_path)
        return run_until_daily_sending(telegram_client, storage)
    except ConfigError:
        print("Ошибка настройки ежедневной рассылки.", file=sys.stderr)
        return 1
    except StorageError:
        print("Ошибка настройки ежедневной рассылки.", file=sys.stderr)
        return 1
    except TelegramApiError:
        print("Ошибка настройки ежедневной рассылки.", file=sys.stderr)
        return 1


def _wait_for_urgent_warnings() -> int:
    try:
        settings = load_settings(require_telegram_token=True)
        if settings.telegram_bot_token is None:
            raise TelegramApiError("Токен Telegram не задан.")

        telegram_client = TelegramClient(settings.telegram_bot_token)
        storage = SQLiteSettingsStore(settings.db_path)
        return run_until_urgent_warnings(telegram_client, storage)
    except ConfigError:
        print("Ошибка настройки срочных предупреждений.", file=sys.stderr)
        return 1
    except StorageError:
        print("Ошибка настройки срочных предупреждений.", file=sys.stderr)
        return 1
    except TelegramApiError:
        print("Ошибка настройки срочных предупреждений.", file=sys.stderr)
        return 1


def _wait_for_warning_categories() -> int:
    try:
        settings = load_settings(require_telegram_token=True)
        if settings.telegram_bot_token is None:
            raise TelegramApiError("Токен Telegram не задан.")

        telegram_client = TelegramClient(settings.telegram_bot_token)
        storage = SQLiteSettingsStore(settings.db_path)
        return run_until_warning_categories(telegram_client, storage)
    except ConfigError:
        print("Ошибка настройки категорий предупреждений.", file=sys.stderr)
        return 1
    except StorageError:
        print("Ошибка настройки категорий предупреждений.", file=sys.stderr)
        return 1
    except TelegramApiError:
        print("Ошибка настройки категорий предупреждений.", file=sys.stderr)
        return 1


def _wait_for_settings_summary() -> int:
    try:
        settings = load_settings(require_telegram_token=True)
        if settings.telegram_bot_token is None:
            raise TelegramApiError("Токен Telegram не задан.")

        telegram_client = TelegramClient(settings.telegram_bot_token)
        storage = SQLiteSettingsStore(settings.db_path)
        return run_until_settings_summary(telegram_client, storage)
    except ConfigError:
        print("Ошибка показа итоговых настроек.", file=sys.stderr)
        return 1
    except StorageError:
        print("Ошибка показа итоговых настроек.", file=sys.stderr)
        return 1
    except TelegramApiError:
        print("Ошибка показа итоговых настроек.", file=sys.stderr)
        return 1


def _wait_for_onboarding_complete() -> int:
    try:
        settings = load_settings(require_telegram_token=True)
        if settings.telegram_bot_token is None:
            raise TelegramApiError("Токен Telegram не задан.")

        telegram_client = TelegramClient(settings.telegram_bot_token)
        storage = SQLiteSettingsStore(settings.db_path)
        return run_until_onboarding_complete(telegram_client, storage)
    except ConfigError:
        print("Ошибка завершения первоначальной настройки.", file=sys.stderr)
        return 1
    except StorageError:
        print("Ошибка завершения первоначальной настройки.", file=sys.stderr)
        return 1
    except TelegramApiError:
        print("Ошибка завершения первоначальной настройки.", file=sys.stderr)
        return 1


def _fetch_weather_forecast() -> int:
    try:
        settings = load_settings(require_telegram_token=False)
        storage = SQLiteSettingsStore(settings.db_path, read_only=True)
        user_settings = storage.get_single_user_settings()
        if user_settings is None:
            print("Сохранённый город не найден.", file=sys.stderr)
            return 1

        forecast = OpenMeteoWeatherClient().fetch(
            user_settings.latitude,
            user_settings.longitude,
            user_settings.timezone,
        )
    except (ConfigError, StorageError):
        print("Ошибка чтения сохранённых настроек города.", file=sys.stderr)
        return 1
    except WeatherForecastError:
        print("Ошибка получения прогноза погоды.", file=sys.stderr)
        return 1

    first_day = forecast.daily[0]
    print(f"Город: {user_settings.city_name}")
    print(f"Часовой пояс: {user_settings.timezone}")
    print(f"Дней прогноза: {len(forecast.daily)}")
    print(f"Первая дата: {first_day.date.isoformat()}")
    print(
        "Первый день: "
        f"min={first_day.temperature_2m_min:g}, "
        f"max={first_day.temperature_2m_max:g}"
    )
    print(
        "Максимальная вероятность осадков: "
        f"{first_day.precipitation_probability_max:g}%"
    )
    print(f"Сумма осадков: {first_day.precipitation_sum:g}")
    print(f"Максимальный ветер: {first_day.wind_speed_10m_max:g}")
    print(f"Максимальные порывы: {first_day.wind_gusts_10m_max:g}")
    print(f"Почасовых значений: {len(forecast.hourly)}")
    return 0


def _fetch_kp_forecast() -> int:
    try:
        forecast = NoaaSwpcGeomagneticClient().fetch()
    except GeomagneticForecastError:
        print("Ошибка получения прогноза Kp NOAA SWPC.", file=sys.stderr)
        return 1

    intervals = forecast.intervals
    first = intervals[0]
    last = intervals[-1]
    status_counts: dict[str, int] = {}
    for interval in intervals:
        if interval.status is not None:
            status_counts[interval.status] = status_counts.get(interval.status, 0) + 1

    print("Источник: NOAA SWPC")
    print(f"Количество интервалов: {len(intervals)}")
    print(f"Первый timestamp: {first.timestamp.isoformat(sep=' ')}")
    print(f"Последний timestamp: {last.timestamp.isoformat(sep=' ')}")
    print(f"Первый Kp: {first.kp:g}")
    print(f"Максимальный Kp: {max(interval.kp for interval in intervals):g}")
    if status_counts:
        breakdown = ", ".join(
            f"{status}={status_counts[status]}"
            for status in sorted(status_counts)
        )
        print(f"Статусы: {breakdown}")
    return 0


def _preview_daily_summary() -> int:
    try:
        settings = load_settings(require_telegram_token=False)
        storage = SQLiteSettingsStore(settings.db_path, read_only=True)
        user_settings = storage.get_single_user_settings()
        if user_settings is None:
            print("Сохранённый город не найден.", file=sys.stderr)
            return 1

        weather = OpenMeteoWeatherClient().fetch(
            user_settings.latitude,
            user_settings.longitude,
            user_settings.timezone,
        )
        geomagnetic = NoaaSwpcGeomagneticClient().fetch()
        summary = build_daily_summary(
            user_settings,
            weather,
            geomagnetic,
            datetime.now(timezone.utc),
        )
        print(format_daily_summary(summary))
        return 0
    except (ConfigError, StorageError):
        print("Ошибка чтения сохранённых настроек города.", file=sys.stderr)
        return 1
    except WeatherForecastError:
        print("Ошибка получения прогноза погоды.", file=sys.stderr)
        return 1
    except GeomagneticForecastError:
        print("Ошибка получения прогноза Kp NOAA SWPC.", file=sys.stderr)
        return 1
    except DailySummaryError:
        print("Ошибка формирования ежедневной сводки.", file=sys.stderr)
        return 1


def _preview_current_risks() -> int:
    try:
        settings = load_settings(require_telegram_token=False)
        storage = SQLiteSettingsStore(settings.db_path, read_only=True)
        user_settings = storage.get_single_user_settings()
        if user_settings is None:
            print("Сохранённый город не найден.", file=sys.stderr)
            return 1

        current_time = datetime.now(timezone.utc)
        weather = OpenMeteoWeatherClient().fetch(
            user_settings.latitude,
            user_settings.longitude,
            user_settings.timezone,
        )
        geomagnetic = NoaaSwpcGeomagneticClient().fetch()
        climate_cache = SQLiteClimateNormalsCache(settings.climate_db_path)
        normals = get_or_create_climate_normals(
            climate_cache,
            OpenMeteoHistoricalWeatherClient(),
            user_settings.latitude,
            user_settings.longitude,
            user_settings.timezone,
            current_time,
            calculator=calculate_climate_normals,
        )
        target_date = local_calendar_date(current_time, user_settings.timezone)
        climate_normal = get_climate_normal_for_date(normals, target_date)
        assessment = assess_current_day_risks(
            weather,
            geomagnetic,
            user_settings.timezone,
            current_time,
            climate_normal=climate_normal,
        )
        print(format_current_day_risk_assessment(assessment))
        return 0
    except KeyboardInterrupt:
        return 130
    except (ConfigError, StorageError):
        print("Ошибка чтения сохранённых настроек города.", file=sys.stderr)
        return 1
    except WeatherForecastError:
        print("Ошибка получения прогноза погоды.", file=sys.stderr)
        return 1
    except GeomagneticForecastError:
        print("Ошибка получения прогноза Kp NOAA SWPC.", file=sys.stderr)
        return 1
    except (ClimateNormalsError, ClimateCacheError):
        print("Ошибка получения климатической нормы.", file=sys.stderr)
        return 1
    except RiskAssessmentError:
        print("Ошибка формирования оценки рисков текущего дня.", file=sys.stderr)
        return 1


def _preview_climate_normal() -> int:
    try:
        settings = load_settings(require_telegram_token=False)
        storage = SQLiteSettingsStore(settings.db_path, read_only=True)
        user_settings = storage.get_single_user_settings()
        if user_settings is None:
            print("Сохранённый город не найден.", file=sys.stderr)
            return 1

        current_time = datetime.now(timezone.utc)
        target_date = local_calendar_date(current_time, user_settings.timezone)
        historical_days = OpenMeteoHistoricalWeatherClient().fetch(
            user_settings.latitude,
            user_settings.longitude,
            user_settings.timezone,
        )
        normals = calculate_climate_normals(
            historical_days,
            user_settings.latitude,
            user_settings.longitude,
            user_settings.timezone,
        )
        print(format_climate_normal(normals, target_date))
        return 0
    except KeyboardInterrupt:
        return 130
    except (ConfigError, StorageError):
        print("Ошибка чтения сохранённых настроек города.", file=sys.stderr)
        return 1
    except ClimateNormalsError:
        print("Ошибка получения климатической нормы.", file=sys.stderr)
        return 1


def _refresh_climate_cache() -> int:
    try:
        settings = load_settings(require_telegram_token=False)
        storage = SQLiteSettingsStore(settings.db_path, read_only=True)
        user_settings = storage.get_single_user_settings()
        if user_settings is None:
            print("Сохранённый город не найден.", file=sys.stderr)
            return 1

        climate_cache = SQLiteClimateNormalsCache(settings.climate_db_path)
        refresh_climate_normals(
            climate_cache,
            OpenMeteoHistoricalWeatherClient(),
            user_settings.latitude,
            user_settings.longitude,
            user_settings.timezone,
            datetime.now(timezone.utc),
            calculator=calculate_climate_normals,
        )
        print("Кэш климатической нормы обновлён.")
        print(f"Период: {BASELINE_START.year}–{BASELINE_END.year}")
        print("Модель: ERA5-Land")
        print("Календарных дней: 366")
        return 0
    except KeyboardInterrupt:
        return 130
    except (ConfigError, StorageError):
        print("Ошибка чтения сохранённых настроек города.", file=sys.stderr)
        return 1
    except (ClimateNormalsError, ClimateCacheError):
        print("Ошибка обновления климатической нормы.", file=sys.stderr)
        return 1


def _wait_for_today() -> int:
    try:
        settings = load_settings(require_telegram_token=True)
        if settings.telegram_bot_token is None:
            raise TelegramApiError("Токен Telegram не задан.")

        telegram_client = TelegramClient(settings.telegram_bot_token)
        storage = SQLiteSettingsStore(settings.db_path, read_only=True)
        weather_client = OpenMeteoWeatherClient()
        geomagnetic_client = NoaaSwpcGeomagneticClient()
        climate_cache = SQLiteClimateNormalsCache(settings.climate_db_path)
        historical_client = OpenMeteoHistoricalWeatherClient()
        return run_until_today(
            telegram_client,
            storage,
            weather_client,
            geomagnetic_client,
            climate_cache,
            historical_client,
            datetime.now(timezone.utc),
        )
    except (ConfigError, StorageError, TelegramApiError, ClimateCacheError):
        print("Ошибка обработки команды /today.", file=sys.stderr)
        return 1


def _run_daily_dispatch_once() -> int:
    try:
        settings = load_settings(require_telegram_token=True)
        if settings.telegram_bot_token is None:
            raise TelegramApiError("Токен Telegram не задан.")

        storage = SQLiteSettingsStore(settings.db_path, read_only=True)
        owner = storage.get_single_user_settings()
        if owner is None:
            print("Сохранённый владелец не найден.", file=sys.stderr)
            return 1

        runtime_state = SQLiteRuntimeStateStore(settings.runtime_db_path)
        current_time = datetime.now(timezone.utc)
        state = runtime_state.get_daily_delivery_state(owner.telegram_chat_id)
        decision = evaluate_daily_dispatch_due(
            owner,
            current_time,
            None if state is None else state.last_successful_local_date,
        )
        if decision.status != "due":
            _print_daily_dispatch_status(decision.status)
            return 0

        result = run_daily_dispatch_once(
            owner=owner,
            runtime_state=runtime_state,
            weather_client=OpenMeteoWeatherClient(),
            geomagnetic_client=NoaaSwpcGeomagneticClient(),
            climate_cache=SQLiteClimateNormalsCache(settings.climate_db_path),
            historical_client=OpenMeteoHistoricalWeatherClient(),
            telegram_client=TelegramClient(settings.telegram_bot_token),
            current_time=current_time,
        )
    except KeyboardInterrupt:
        return 130
    except (
        ConfigError,
        StorageError,
        RuntimeStateError,
        DailyDispatchError,
        TelegramApiError,
        ClimateCacheError,
    ):
        print("Ошибка выполнения ежедневной рассылки.", file=sys.stderr)
        return 1

    _print_daily_dispatch_status(result.status)
    return 0


def _run_scheduler() -> int:
    try:
        settings = load_settings(require_telegram_token=True)
        if settings.telegram_bot_token is None:
            raise TelegramApiError("Токен Telegram не задан.")

        telegram_client = TelegramClient(settings.telegram_bot_token)
        settings_store = SQLiteSettingsStore(settings.db_path, read_only=True)
        runtime_state = SQLiteRuntimeStateStore(settings.runtime_db_path)
        weather_client = OpenMeteoWeatherClient()
        geomagnetic_client = NoaaSwpcGeomagneticClient()
        climate_cache = SQLiteClimateNormalsCache(settings.climate_db_path)
        historical_client = OpenMeteoHistoricalWeatherClient()
    except Exception:
        print("Ошибка запуска планировщика.", file=sys.stderr)
        return 1

    stop_event = Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    previous_handlers: dict[int, object] = {}
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, request_stop)

        print("Планировщик запущен.")
        try:
            run_scheduler_loop(
                settings_store=settings_store,
                runtime_state=runtime_state,
                weather_client=weather_client,
                geomagnetic_client=geomagnetic_client,
                climate_cache=climate_cache,
                historical_client=historical_client,
                telegram_client=telegram_client,
                stop_event=stop_event,
            )
        except KeyboardInterrupt:
            stop_event.set()
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)

    print("Планировщик остановлен.")
    return 0


def _print_daily_dispatch_status(status: str) -> None:
    if status == "not_due":
        print("Ежедневная сводка сейчас не запланирована.")
    elif status == "already_sent":
        print("Ежедневная сводка за текущий день уже отправлена.")
    else:
        print("Ежедневная сводка отправлена по расписанию.")


def _check_telegram() -> int:
    try:
        settings = load_settings(require_telegram_token=True)
        if settings.telegram_bot_token is None:
            raise TelegramApiError("Токен Telegram не задан.")

        identity = TelegramClient(settings.telegram_bot_token).get_me()
    except (ConfigError, TelegramApiError) as exc:
        print(f"Ошибка проверки Telegram: {exc}", file=sys.stderr)
        return 1

    print("Токен принят Telegram: да")
    print(f"ID бота: {identity.id}")
    print(f"Username: @{identity.username}")
    print(f"Имя: {identity.first_name}")
    return 0


def _geocode_city(city: str) -> int:
    try:
        locations = OpenMeteoGeocodingClient().search(city.strip())
    except GeocodingError as exc:
        print(f"Ошибка геокодирования: {exc}", file=sys.stderr)
        return 1

    if not locations:
        print("Подходящие города не найдены.")
        return 2

    print("Найденные варианты:")
    for index, location in enumerate(locations[:5], start=1):
        place_parts = [location.name]
        if location.admin1:
            place_parts.append(location.admin1)
        place_parts.append(location.country)
        print(
            f"{index}. {', '.join(place_parts)} — "
            f"{location.latitude:.6f}, {location.longitude:.6f} — {location.timezone}"
        )
    print("Источник геокодирования: Open-Meteo; данные о локациях: GeoNames.")
    return 0
