import argparse
import sys
from collections.abc import Sequence

from weather_alert_bot.city_handler import run_until_city
from weather_alert_bot.config import ConfigError, load_settings
from weather_alert_bot.confirmed_city_handler import run_until_confirmed_city
from weather_alert_bot.daily_days_handler import run_until_daily_days
from weather_alert_bot.daily_sending_handler import run_until_daily_sending
from weather_alert_bot.daily_time_handler import run_until_daily_time
from weather_alert_bot.geocoding import GeocodingError, OpenMeteoGeocodingClient
from weather_alert_bot.geocoded_city_handler import run_until_geocoded_city
from weather_alert_bot.storage import SQLiteSettingsStore, StorageError
from weather_alert_bot.start_handler import run_until_start
from weather_alert_bot.settings_summary_handler import run_until_settings_summary
from weather_alert_bot.telegram_api import TelegramApiError, TelegramClient
from weather_alert_bot.urgent_warnings_handler import run_until_urgent_warnings
from weather_alert_bot.warning_categories_handler import run_until_warning_categories


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
