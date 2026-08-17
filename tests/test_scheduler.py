from datetime import date, datetime, timezone
from pathlib import Path
import tempfile
import unittest
from threading import Event
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from weather_alert_bot.daily_dispatch import DailyDispatchResult
from weather_alert_bot.runtime_state import SQLiteRuntimeStateStore
from weather_alert_bot.scheduler import (
    SCHEDULER_ERROR_DIAGNOSTIC,
    SCHEDULED_REPORT_SENT_DIAGNOSTIC,
    SchedulerTickError,
    SchedulerTickResult,
    next_utc_minute_boundary,
    run_scheduler_loop,
    run_scheduler_tick,
    seconds_until_next_utc_minute,
)
from weather_alert_bot.storage import UserSettings


UTC = ZoneInfo("UTC")


def owner(**changes: object) -> UserSettings:
    values: dict[str, object] = {
        "telegram_chat_id": 42,
        "city_name": "Москва",
        "latitude": 55.75204,
        "longitude": 37.61781,
        "timezone": "Europe/Moscow",
        "daily_send_time": "10:00",
        "daily_send_days": "1,2,3,4,5,6,7",
        "daily_sending_enabled": True,
        "onboarding_completed": True,
    }
    values.update(changes)
    return UserSettings(**values)  # type: ignore[arg-type]


class SchedulerBoundaryTest(unittest.TestCase):
    def test_next_boundary_and_delay_cover_exact_fractional_and_rollover_cases(self) -> None:
        cases = (
            (datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC), 60.0),
            (datetime(2026, 8, 14, 12, 0, 0, 500000, tzinfo=UTC), 59.5),
            (datetime(2026, 8, 14, 12, 0, 59, 999000, tzinfo=UTC), 0.001),
            (datetime(2026, 8, 14, 12, 59, 59, 500000, tzinfo=UTC), 0.5),
            (datetime(2026, 8, 14, 23, 59, 59, 999000, tzinfo=UTC), 0.001),
        )
        for current_time, expected_delay in cases:
            with self.subTest(current_time=current_time):
                boundary = next_utc_minute_boundary(current_time)
                self.assertEqual(boundary.second, 0)
                self.assertEqual(boundary.microsecond, 0)
                self.assertEqual(seconds_until_next_utc_minute(current_time), expected_delay)

        self.assertEqual(
            next_utc_minute_boundary(
                datetime(2026, 8, 14, 23, 59, 59, 999000, tzinfo=UTC)
            ),
            datetime(2026, 8, 15, 0, 0, tzinfo=UTC),
        )

    def test_naive_and_non_utc_times_are_rejected(self) -> None:
        for current_time in (
            datetime(2026, 8, 14, 12, 0),
            datetime(2026, 8, 14, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        ):
            with self.subTest(current_time=current_time):
                with self.assertRaises(SchedulerTickError):
                    next_utc_minute_boundary(current_time)


class SchedulerTickTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.runtime = SQLiteRuntimeStateStore(Path(self.directory.name) / "runtime.sqlite3")
        self.settings_store = Mock()
        self.weather = Mock()
        self.geomagnetic = Mock()
        self.climate = Mock()
        self.historical = Mock()
        self.telegram = Mock()
        self.current_time = datetime(2026, 8, 14, 7, tzinfo=UTC)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_one_tick_reads_settings_and_calls_existing_dispatch_once(self) -> None:
        first_owner = owner()
        self.settings_store.get_single_user_settings.return_value = first_owner
        dispatch_result = DailyDispatchResult("not_due", date(2026, 8, 14))
        with patch(
            "weather_alert_bot.scheduler.run_daily_dispatch_once",
            return_value=dispatch_result,
        ) as dispatch:
            result = run_scheduler_tick(
                settings_store=self.settings_store,
                runtime_state=self.runtime,
                weather_client=self.weather,
                geomagnetic_client=self.geomagnetic,
                climate_cache=self.climate,
                historical_client=self.historical,
                telegram_client=self.telegram,
                current_time=self.current_time,
            )

        self.assertEqual(result.status, "not_due")
        self.settings_store.get_single_user_settings.assert_called_once_with()
        dispatch.assert_called_once_with(
            owner=first_owner,
            runtime_state=self.runtime,
            weather_client=self.weather,
            geomagnetic_client=self.geomagnetic,
            climate_cache=self.climate,
            historical_client=self.historical,
            telegram_client=self.telegram,
            current_time=self.current_time,
        )

    def test_settings_are_reread_and_changes_reach_the_next_tick(self) -> None:
        first_owner = owner(daily_send_time="10:00")
        second_owner = owner(daily_send_time="11:00")
        self.settings_store.get_single_user_settings.side_effect = [first_owner, second_owner]
        dispatch_result = DailyDispatchResult("not_due", date(2026, 8, 14))
        with patch(
            "weather_alert_bot.scheduler.run_daily_dispatch_once",
            return_value=dispatch_result,
        ) as dispatch:
            run_scheduler_tick(
                settings_store=self.settings_store,
                runtime_state=self.runtime,
                weather_client=self.weather,
                geomagnetic_client=self.geomagnetic,
                climate_cache=self.climate,
                historical_client=self.historical,
                telegram_client=self.telegram,
                current_time=self.current_time,
            )
            run_scheduler_tick(
                settings_store=self.settings_store,
                runtime_state=self.runtime,
                weather_client=self.weather,
                geomagnetic_client=self.geomagnetic,
                climate_cache=self.climate,
                historical_client=self.historical,
                telegram_client=self.telegram,
                current_time=self.current_time,
            )

        self.assertEqual([call.kwargs["owner"] for call in dispatch.call_args_list], [first_owner, second_owner])

    def test_missing_or_broken_settings_are_safe_tick_failures(self) -> None:
        for stored in (None, RuntimeError("private SQLite details")):
            with self.subTest(stored=stored):
                self.settings_store.get_single_user_settings.reset_mock()
                if isinstance(stored, Exception):
                    self.settings_store.get_single_user_settings.side_effect = stored
                else:
                    self.settings_store.get_single_user_settings.return_value = stored
                result = run_scheduler_tick(
                    settings_store=self.settings_store,
                    runtime_state=self.runtime,
                    weather_client=self.weather,
                    geomagnetic_client=self.geomagnetic,
                    climate_cache=self.climate,
                    historical_client=self.historical,
                    telegram_client=self.telegram,
                    current_time=self.current_time,
                )
                self.assertEqual(result.status, "failed")

    def test_not_due_does_not_call_network_dependencies(self) -> None:
        self.settings_store.get_single_user_settings.return_value = owner(
            daily_send_time="11:00"
        )
        result = run_scheduler_tick(
            settings_store=self.settings_store,
            runtime_state=self.runtime,
            weather_client=self.weather,
            geomagnetic_client=self.geomagnetic,
            climate_cache=self.climate,
            historical_client=self.historical,
            telegram_client=self.telegram,
            current_time=self.current_time,
        )
        self.assertEqual(result.status, "not_due")
        self.weather.fetch.assert_not_called()
        self.geomagnetic.fetch.assert_not_called()
        self.historical.fetch.assert_not_called()
        self.telegram.send_message.assert_not_called()


class SchedulerLoopTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dependencies = {
            "settings_store": Mock(),
            "runtime_state": Mock(),
            "weather_client": Mock(),
            "geomagnetic_client": Mock(),
            "climate_cache": Mock(),
            "historical_client": Mock(),
            "telegram_client": Mock(),
        }

    def test_initial_tick_is_immediate_and_wait_uses_completion_boundary(self) -> None:
        stop_event = Event()
        clock = iter(
            (
                datetime(2026, 8, 14, 12, 15, 0, 100000, tzinfo=UTC),
                datetime(2026, 8, 14, 12, 15, 4, 500000, tzinfo=UTC),
            )
        )
        waits: list[float] = []

        def waiter(event: Event, delay: float) -> bool:
            waits.append(delay)
            event.set()
            return True

        with patch(
            "weather_alert_bot.scheduler.run_scheduler_tick",
            return_value=SchedulerTickResult("not_due"),
        ) as tick:
            run_scheduler_loop(
                **self.dependencies,
                stop_event=stop_event,
                now=lambda: next(clock),
                waiter=waiter,
            )

        tick.assert_called_once()
        self.assertEqual(
            tick.call_args.kwargs["current_time"],
            datetime(2026, 8, 14, 12, 15, 0, 100000, tzinfo=timezone.utc),
        )
        self.assertEqual(waits, [55.5])

    def test_long_tick_skips_missed_minutes_without_catch_up(self) -> None:
        stop_event = Event()
        clock = iter(
            (
                datetime(2026, 8, 14, 12, 15, 0, tzinfo=UTC),
                datetime(2026, 8, 14, 12, 15, 4, tzinfo=UTC),
                datetime(2026, 8, 14, 12, 16, 0, tzinfo=UTC),
                datetime(2026, 8, 14, 12, 17, 8, tzinfo=UTC),
            )
        )
        waits: list[float] = []

        def waiter(event: Event, delay: float) -> bool:
            waits.append(delay)
            if len(waits) == 2:
                event.set()
            return event.is_set()

        with patch(
            "weather_alert_bot.scheduler.run_scheduler_tick",
            return_value=SchedulerTickResult("not_due"),
        ) as tick:
            run_scheduler_loop(
                **self.dependencies,
                stop_event=stop_event,
                now=lambda: next(clock),
                waiter=waiter,
            )

        self.assertEqual(tick.call_count, 2)
        self.assertEqual(waits, [56.0, 52.0])

    def test_stop_during_wait_and_keyboard_interrupt_do_not_start_another_tick(self) -> None:
        for raises_keyboard_interrupt in (False, True):
            with self.subTest(raises_keyboard_interrupt=raises_keyboard_interrupt):
                stop_event = Event()
                now = Mock(
                    side_effect=[
                        datetime(2026, 8, 14, 12, 15, tzinfo=UTC),
                        datetime(2026, 8, 14, 12, 15, 1, tzinfo=UTC),
                    ]
                )

                def waiter(event: Event, _delay: float) -> bool:
                    event.set()
                    if raises_keyboard_interrupt:
                        raise KeyboardInterrupt
                    return True

                with patch(
                    "weather_alert_bot.scheduler.run_scheduler_tick",
                    return_value=SchedulerTickResult("not_due"),
                ) as tick:
                    run_scheduler_loop(
                        **self.dependencies,
                        stop_event=stop_event,
                        now=now,
                        waiter=waiter,
                    )
                tick.assert_called_once()
                self.assertTrue(stop_event.is_set())

    def test_only_actual_send_is_emitted_and_failures_are_safe(self) -> None:
        stop_event = Event()
        now = Mock(
            side_effect=[
                datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
                datetime(2026, 8, 14, 12, 0, 1, tzinfo=UTC),
            ]
        )
        output: list[str] = []
        errors: list[str] = []

        with patch(
            "weather_alert_bot.scheduler.run_scheduler_tick",
            return_value=SchedulerTickResult("failed"),
        ):
            def waiter(event: Event, _delay: float) -> bool:
                event.set()
                return True

            run_scheduler_loop(
                **self.dependencies,
                stop_event=stop_event,
                now=now,
                waiter=waiter,
                emit=output.append,
                error_emit=errors.append,
            )

        self.assertEqual(output, [])
        self.assertEqual(errors, [SCHEDULER_ERROR_DIAGNOSTIC])
        self.assertNotIn("private", " ".join(errors))
        self.assertNotIn("token", " ".join(errors).lower())

    def test_failed_tick_continues_at_next_boundary_without_immediate_retry(self) -> None:
        stop_event = Event()
        clock = iter(
            (
                datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
                datetime(2026, 8, 14, 12, 0, 2, tzinfo=UTC),
                datetime(2026, 8, 14, 12, 1, tzinfo=UTC),
                datetime(2026, 8, 14, 12, 1, 2, tzinfo=UTC),
            )
        )
        waits: list[float] = []
        errors: list[str] = []

        def waiter(event: Event, delay: float) -> bool:
            waits.append(delay)
            if len(waits) == 2:
                event.set()
            return event.is_set()

        with patch(
            "weather_alert_bot.scheduler.run_scheduler_tick",
            side_effect=(
                SchedulerTickResult("failed"),
                SchedulerTickResult("not_due"),
            ),
        ) as tick:
            run_scheduler_loop(
                **self.dependencies,
                stop_event=stop_event,
                now=lambda: next(clock),
                waiter=waiter,
                error_emit=errors.append,
            )

        self.assertEqual(tick.call_count, 2)
        self.assertEqual(waits, [58.0, 58.0])
        self.assertEqual(errors, [SCHEDULER_ERROR_DIAGNOSTIC])

    def test_success_diagnostic_is_emitted_only_for_sent_result(self) -> None:
        stop_event = Event()
        clock = iter(
            (
                datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
                datetime(2026, 8, 14, 12, 0, 1, tzinfo=UTC),
                datetime(2026, 8, 14, 12, 1, tzinfo=UTC),
                datetime(2026, 8, 14, 12, 1, 1, tzinfo=UTC),
            )
        )
        output: list[str] = []
        with patch(
            "weather_alert_bot.scheduler.run_scheduler_tick",
            side_effect=(
                SchedulerTickResult("sent"),
                SchedulerTickResult("already_sent"),
            ),
        ) as tick:
            def waiter(event: Event, _delay: float) -> bool:
                if tick.call_count == 2:
                    event.set()
                return event.is_set()

            run_scheduler_loop(
                **self.dependencies,
                stop_event=stop_event,
                now=lambda: next(clock),
                waiter=waiter,
                emit=output.append,
            )
        self.assertEqual(tick.call_count, 2)
        self.assertEqual(output, [SCHEDULED_REPORT_SENT_DIAGNOSTIC])
if __name__ == "__main__":
    unittest.main()
