import argparse
import sys
from collections.abc import Sequence

from weather_alert_bot.city_handler import run_until_city
from weather_alert_bot.config import ConfigError, load_settings
from weather_alert_bot.start_handler import run_until_start
from weather_alert_bot.telegram_api import TelegramApiError, TelegramClient


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
    args = parser.parse_args(argv)

    if args.check_telegram:
        return _check_telegram()
    if args.wait_for_start:
        return _wait_for_start()
    if args.wait_for_city:
        return _wait_for_city()

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
