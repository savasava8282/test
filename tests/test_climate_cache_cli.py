from datetime import datetime, timezone
import io
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from weather_alert_bot.app import main
from weather_alert_bot.climate_cache import SQLiteClimateNormalsCache
from weather_alert_bot.climate_normals import calculate_climate_normals
from weather_alert_bot.storage import SQLiteSettingsStore
from tests.test_climate_cache import historical_records, normals
from tests.test_risk_assessment_cli import city, geomagnetic, weather


class ClimateCacheCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.settings_path = root / "settings.sqlite3"
        self.climate_path = root / "climate.sqlite3"
        SQLiteSettingsStore(self.settings_path).save_confirmed_city(42, city())
        self.now = datetime(2026, 8, 11, 21, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def run_cli(self, mode: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        environment = {
            "WEATHER_ALERT_BOT_DB_PATH": str(self.settings_path),
            "WEATHER_ALERT_BOT_CLIMATE_DB_PATH": str(self.climate_path),
        }
        with patch.dict(os.environ, environment, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main([mode])
        return result, stdout.getvalue(), stderr.getvalue()

    def test_refresh_without_token_reads_settings_only_and_writes_cache(self) -> None:
        with patch("weather_alert_bot.app.OpenMeteoHistoricalWeatherClient") as historical_type:
            historical_type.return_value.fetch.return_value = historical_records()
            with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
                with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as kp_type:
                    with patch("weather_alert_bot.app.TelegramClient") as telegram_type:
                        with patch("weather_alert_bot.app.datetime") as datetime_type:
                            datetime_type.now.return_value = self.now
                            before = self.settings_path.read_bytes()
                            result, stdout, stderr = self.run_cli("--refresh-climate-cache")

        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        self.assertIn("Кэш климатической нормы обновлён.", stdout)
        self.assertIn("Период: 1991–2020", stdout)
        self.assertIn("Модель: ERA5-Land", stdout)
        self.assertIn("Календарных дней: 366", stdout)
        historical_type.return_value.fetch.assert_called_once_with(
            55.75204, 37.61781, "Europe/Moscow"
        )
        weather_type.assert_not_called()
        kp_type.assert_not_called()
        telegram_type.assert_not_called()
        self.assertEqual(self.settings_path.read_bytes(), before)
        self.assertIsNotNone(SQLiteClimateNormalsCache(self.climate_path).get(55.75204, 37.61781, "Europe/Moscow"))

    def test_refresh_replaces_existing_snapshot_and_always_fetches_once(self) -> None:
        cache = SQLiteClimateNormalsCache(self.climate_path)
        cache.save(normals(), generated_at=self.now)
        with patch("weather_alert_bot.app.OpenMeteoHistoricalWeatherClient") as historical_type:
            historical_type.return_value.fetch.return_value = historical_records()
            with patch("weather_alert_bot.app.datetime") as datetime_type:
                datetime_type.now.return_value = self.now.replace(hour=22)
                result, _, stderr = self.run_cli("--refresh-climate-cache")
        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        historical_type.return_value.fetch.assert_called_once()
        loaded = cache.get(55.75204, 37.61781, "Europe/Moscow")
        assert loaded is not None
        self.assertEqual(loaded.generated_at, self.now.replace(hour=22))

    def test_preview_cache_hit_avoids_historical_and_keeps_weather_and_noaa(self) -> None:
        SQLiteClimateNormalsCache(self.climate_path).save(normals(55.75204, 37.61781, "Europe/Moscow"), generated_at=self.now)
        with patch("weather_alert_bot.app.OpenMeteoHistoricalWeatherClient") as historical_type:
            with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
                weather_type.return_value.fetch.return_value = weather()
                with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as kp_type:
                    kp_type.return_value.fetch.return_value = geomagnetic()
                    with patch("weather_alert_bot.app.datetime") as datetime_type:
                        datetime_type.now.return_value = self.now
                        result, stdout, stderr = self.run_cli("--preview-current-risks")
        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        historical_type.return_value.fetch.assert_not_called()
        weather_type.return_value.fetch.assert_called_once()
        kp_type.return_value.fetch.assert_called_once()
        self.assertNotIn("Не оцениваются на этом этапе", stdout)

    def test_preview_cache_miss_fetches_once_then_second_run_hits(self) -> None:
        with patch("weather_alert_bot.app.OpenMeteoHistoricalWeatherClient") as historical_type:
            historical_type.return_value.fetch.return_value = historical_records()
            with patch("weather_alert_bot.app.OpenMeteoWeatherClient") as weather_type:
                weather_type.return_value.fetch.return_value = weather()
                with patch("weather_alert_bot.app.NoaaSwpcGeomagneticClient") as kp_type:
                    kp_type.return_value.fetch.return_value = geomagnetic()
                    with patch("weather_alert_bot.app.datetime") as datetime_type:
                        datetime_type.now.return_value = self.now
                        first = self.run_cli("--preview-current-risks")
                        second = self.run_cli("--preview-current-risks")
        self.assertEqual(first[0], 0)
        self.assertEqual(second[0], 0)
        historical_type.return_value.fetch.assert_called_once()
        self.assertEqual(weather_type.return_value.fetch.call_count, 2)
        self.assertEqual(kp_type.return_value.fetch.call_count, 2)

    def test_refresh_and_cache_are_mutually_exclusive_with_existing_modes(self) -> None:
        for other in ("--preview-current-risks", "--preview-climate-normal", "--fetch-weather-forecast", "--fetch-kp-forecast", "--wait-for-today"):
            with self.subTest(other=other), self.assertRaises(SystemExit) as raised:
                main(["--refresh-climate-cache", other])
            self.assertEqual(raised.exception.code, 2)

    def test_refresh_historical_failure_leaves_no_set(self) -> None:
        with patch("weather_alert_bot.app.OpenMeteoHistoricalWeatherClient") as historical_type:
            from weather_alert_bot.climate_normals import ClimateNormalsError
            historical_type.return_value.fetch.side_effect = ClimateNormalsError("private")
            result, stdout, stderr = self.run_cli("--refresh-climate-cache")
        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Ошибка обновления климатической нормы.", stderr)
        self.assertIsNone(
            SQLiteClimateNormalsCache(self.climate_path, read_only=True).get(
                55.75204, 37.61781, "Europe/Moscow"
            )
        )


if __name__ == "__main__":
    unittest.main()
