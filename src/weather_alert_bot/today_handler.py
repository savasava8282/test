from __future__ import annotations

from datetime import datetime
import sys

from weather_alert_bot.climate_cache import SQLiteClimateNormalsCache
from weather_alert_bot.climate_normals import OpenMeteoHistoricalWeatherClient
from weather_alert_bot.daily_report import (
    CLIMATE_FALLBACK_DIAGNOSTIC,
    build_production_daily_report,
)
from weather_alert_bot.geomagnetic_forecast import (
    GeomagneticForecastError,
    NoaaSwpcGeomagneticClient,
)
from weather_alert_bot.daily_summary import DailySummaryError, build_daily_summary
from weather_alert_bot.risk_assessment import RiskAssessmentError, assess_current_day_risks
from weather_alert_bot.start_handler import _next_offset
from weather_alert_bot.storage import SQLiteSettingsStore, StorageError, UserSettings
from weather_alert_bot.telegram_api import TelegramApiError, TelegramClient, TelegramUpdate
from weather_alert_bot.weather_forecast import (
    OpenMeteoWeatherClient,
    WeatherForecastError,
)


TODAY_COMMANDS = {"/today", "/today@weather_storm_alert_bot"}
ONBOARDING_REQUIRED_TEXT = "Сначала завершите первоначальную настройку через /start."
SUMMARY_ERROR_TEXT = "Не удалось сформировать сводку. Попробуйте позже."
STORAGE_ERROR_TEXT = "Ошибка чтения сохранённых настроек города."
NO_SAVED_OWNER_TEXT = "Сохранённый владелец не найден."
CLIMATE_FALLBACK_DIAGNOSTIC = (
    "Климатическая норма недоступна; жара и холод временно не оценены."
)


def _send_safe_message(
    telegram_client: TelegramClient,
    chat_id: int,
    text: str,
) -> bool:
    try:
        telegram_client.send_message(chat_id=chat_id, text=text)
    except TelegramApiError:
        print("Ошибка отправки сообщения Telegram.", file=sys.stderr)
        return False
    return True


def _handle_today(
    telegram_client: TelegramClient,
    owner: UserSettings,
    weather_client: OpenMeteoWeatherClient,
    geomagnetic_client: NoaaSwpcGeomagneticClient,
    climate_cache: SQLiteClimateNormalsCache,
    historical_client: OpenMeteoHistoricalWeatherClient,
    formed_at: datetime,
) -> int:
    if not owner.onboarding_completed:
        _send_safe_message(
            telegram_client,
            owner.telegram_chat_id,
            ONBOARDING_REQUIRED_TEXT,
        )
        return 1

    try:
        text = build_production_daily_report(
            owner=owner,
            weather_client=weather_client,
            geomagnetic_client=geomagnetic_client,
            climate_cache=climate_cache,
            historical_client=historical_client,
            formed_at=formed_at,
            summary_builder=build_daily_summary,
            risk_assessor=assess_current_day_risks,
        )
    except (
        WeatherForecastError,
        GeomagneticForecastError,
        DailySummaryError,
        RiskAssessmentError,
    ):
        print("Не удалось сформировать сводку.", file=sys.stderr)
        _send_safe_message(
            telegram_client,
            owner.telegram_chat_id,
            SUMMARY_ERROR_TEXT,
        )
        return 1

    if not _send_safe_message(telegram_client, owner.telegram_chat_id, text):
        return 1
    print("Сводка /today отправлена.")
    return 0


def run_until_today(
    telegram_client: TelegramClient,
    storage: SQLiteSettingsStore,
    weather_client: OpenMeteoWeatherClient,
    geomagnetic_client: NoaaSwpcGeomagneticClient,
    climate_cache: SQLiteClimateNormalsCache,
    historical_client: OpenMeteoHistoricalWeatherClient,
    formed_at: datetime,
) -> int:
    """Wait for one new private owner /today, send one summary, and finish."""
    try:
        try:
            owner = storage.get_single_user_settings()
        except StorageError:
            print(STORAGE_ERROR_TEXT, file=sys.stderr)
            return 1

        if owner is None:
            print(NO_SAVED_OWNER_TEXT, file=sys.stderr)
            return 1

        offset: int | None = None
        seen_update_ids: set[int] = set()

        while True:
            old_updates = telegram_client.get_updates(
                offset=offset,
                timeout=0,
                limit=100,
            )
            offset = _next_offset(offset, old_updates)
            seen_update_ids.update(update.update_id for update in old_updates)
            if not old_updates:
                break

        print("Ожидание новой команды /today...")

        while True:
            updates = telegram_client.get_updates(offset=offset, timeout=30, limit=100)
            offset = _next_offset(offset, updates)

            for update in updates:
                if update.update_id in seen_update_ids:
                    continue
                seen_update_ids.add(update.update_id)

                message = update.message
                if message is None or message.chat_type != "private":
                    continue
                if message.chat_id != owner.telegram_chat_id:
                    continue
                if message.text not in TODAY_COMMANDS:
                    continue

                print("Команда /today получена.")
                return _handle_today(
                    telegram_client,
                    owner,
                    weather_client,
                    geomagnetic_client,
                    climate_cache,
                    historical_client,
                    formed_at,
                )
    except TelegramApiError:
        print("Ошибка обработки команды /today.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Ожидание команды /today остановлено.")
        return 130
