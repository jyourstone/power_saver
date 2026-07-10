"""Tests for the Power Saver coordinator — locked schedule behavior."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from helpers import TZ, make_nordpool_hour

# Import scheduler directly to avoid triggering __init__.py which needs homeassistant
_scheduler_path = Path(__file__).resolve().parent.parent / "custom_components" / "power_saver"
sys.path.insert(0, str(_scheduler_path))
import scheduler  # noqa: E402

build_schedule = scheduler.build_schedule
NORDPOOL_TYPE_HACS = "hacs"
NORDPOOL_TYPE_NATIVE = "native"
EXPECTED_CLOCK_REFRESH_DELAY_SECONDS = 10
EXPECTED_CLOCK_REFRESH_MINUTES = (0, 15, 30, 45)


def _make_coordinator_for_refresh_tracking(nordpool_type=NORDPOOL_TYPE_HACS):
    """Create a coordinator with enough state for refresh tracking tests."""
    from custom_components.power_saver.coordinator import PowerSaverCoordinator

    hass = MagicMock()
    hass.async_create_task = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_123"
    entry.data = {
        "nordpool_sensor": "sensor.nordpool",
        "nordpool_type": nordpool_type,
    }
    entry.options = {}

    with (
        patch("custom_components.power_saver.coordinator.DataUpdateCoordinator.__init__"),
        patch("custom_components.power_saver.coordinator.Store"),
    ):
        coordinator = PowerSaverCoordinator(hass, entry)

    coordinator.hass = hass
    coordinator.config_entry = entry
    coordinator.async_request_refresh = MagicMock()
    return coordinator


@pytest.fixture
def now() -> datetime:
    """Return a fixed 'now' for deterministic testing."""
    return datetime(2026, 2, 6, 14, 30, 0, tzinfo=TZ)


@pytest.fixture
def today_prices() -> list[dict]:
    """Return 96 quarter-hour slots of today's price data."""
    prices = [
        0.10, 0.08, 0.05, 0.03, 0.04, 0.06,  # 00-05: cheap night
        0.15, 0.35, 0.50, 0.45, 0.30, 0.25,  # 06-11: morning ramp
        0.20, 0.18, 0.15, 0.12, 0.14, 0.40,  # 12-17: midday + evening ramp
        0.55, 0.60, 0.50, 0.35, 0.20, 0.12,  # 18-23: evening peak + decline
    ]
    return [slot for h, p in enumerate(prices) for slot in make_nordpool_hour(h, p)]


@pytest.fixture
def tomorrow_prices() -> list[dict]:
    """Return 96 quarter-hour slots of tomorrow's price data."""
    prices = [
        0.08, 0.06, 0.04, 0.02, 0.03, 0.05,  # 00-05
        0.12, 0.30, 0.45, 0.40, 0.28, 0.22,  # 06-11
        0.18, 0.16, 0.13, 0.10, 0.12, 0.35,  # 12-17
        0.50, 0.55, 0.45, 0.30, 0.18, 0.10,  # 18-23
    ]
    return [slot for h, p in enumerate(prices) for slot in make_nordpool_hour(h, p, day_offset=1)]


class TestRefreshTracking:
    """Tests for event-driven and clock-aligned coordinator refresh tracking."""

    def test_data_update_coordinator_polling_is_disabled(self):
        """Coordinator should not use drift-prone fixed interval polling."""
        from custom_components.power_saver.coordinator import PowerSaverCoordinator

        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_123"
        entry.data = {
            "nordpool_sensor": "sensor.nordpool",
            "nordpool_type": NORDPOOL_TYPE_HACS,
        }

        with (
            patch(
                "custom_components.power_saver.coordinator.DataUpdateCoordinator.__init__"
            ) as mock_init,
            patch("custom_components.power_saver.coordinator.Store"),
        ):
            PowerSaverCoordinator(hass, entry)

        assert mock_init.call_args.kwargs["update_interval"] is None

    def test_setup_refresh_tracking_registers_hacs_listeners_once(self):
        """HACS setups should register Nord Pool and fallback listeners once."""
        coordinator = _make_coordinator_for_refresh_tracking()
        unsub_nordpool = MagicMock()
        unsub_clock = MagicMock()

        with (
            patch(
                "custom_components.power_saver.coordinator.async_track_state_change_event",
                return_value=unsub_nordpool,
            ) as mock_track_state,
            patch(
                "custom_components.power_saver.coordinator.async_track_time_change",
                return_value=unsub_clock,
            ) as mock_track_time,
            patch.object(coordinator, "_subscribe_native_coordinator") as mock_native,
        ):
            coordinator.async_setup_refresh_tracking()
            coordinator.async_setup_refresh_tracking()

        mock_track_state.assert_called_once_with(
            coordinator.hass,
            ["sensor.nordpool"],
            coordinator._on_nordpool_update,
        )
        mock_track_time.assert_called_once_with(
            coordinator.hass,
            coordinator._schedule_clock_refresh,
            minute=EXPECTED_CLOCK_REFRESH_MINUTES,
            second=0,
        )
        mock_native.assert_not_called()
        assert coordinator._unsub_nordpool is unsub_nordpool
        assert coordinator._unsub_clock_refresh is unsub_clock

    def test_setup_refresh_tracking_subscribes_native_coordinator(self):
        """Native setups should also subscribe to the native Nord Pool coordinator."""
        coordinator = _make_coordinator_for_refresh_tracking(NORDPOOL_TYPE_NATIVE)

        with (
            patch(
                "custom_components.power_saver.coordinator.async_track_state_change_event",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.power_saver.coordinator.async_track_time_change",
                return_value=MagicMock(),
            ),
            patch.object(coordinator, "_subscribe_native_coordinator") as mock_native,
        ):
            coordinator.async_setup_refresh_tracking()

        mock_native.assert_called_once()

    def test_clock_boundary_schedules_delayed_refresh(self):
        """Quarter-hour fallback should wait briefly before refreshing."""
        coordinator = _make_coordinator_for_refresh_tracking()
        unsub_delay = MagicMock()

        with patch(
            "custom_components.power_saver.coordinator.async_call_later",
            return_value=unsub_delay,
        ) as mock_call_later:
            coordinator._schedule_clock_refresh(datetime(2026, 2, 6, 14, 0))

        mock_call_later.assert_called_once_with(
            coordinator.hass,
            EXPECTED_CLOCK_REFRESH_DELAY_SECONDS,
            coordinator._on_clock_refresh_delay_elapsed,
        )
        assert coordinator._unsub_delayed_clock_refresh is unsub_delay

    def test_clock_boundary_replaces_pending_delayed_refresh(self):
        """A new boundary callback should cancel any pending delayed refresh."""
        coordinator = _make_coordinator_for_refresh_tracking()
        pending_unsub = MagicMock()
        new_unsub = MagicMock()
        coordinator._unsub_delayed_clock_refresh = pending_unsub

        with patch(
            "custom_components.power_saver.coordinator.async_call_later",
            return_value=new_unsub,
        ):
            coordinator._schedule_clock_refresh(datetime(2026, 2, 6, 14, 0))

        pending_unsub.assert_called_once()
        assert coordinator._unsub_delayed_clock_refresh is new_unsub

    def test_clock_boundary_skips_fallback_after_recent_nordpool_update(self):
        """Fallback should not be scheduled when Nord Pool already refreshed."""
        coordinator = _make_coordinator_for_refresh_tracking()
        now = datetime(2026, 2, 6, 13, 0, 5, tzinfo=timezone.utc)
        coordinator._last_nordpool_refresh_request = now - timedelta(seconds=3)

        with (
            patch(
                "custom_components.power_saver.coordinator.dt_util.utcnow",
                return_value=now,
            ),
            patch(
                "custom_components.power_saver.coordinator.async_call_later",
            ) as mock_call_later,
        ):
            coordinator._schedule_clock_refresh(datetime(2026, 2, 6, 14, 0))

        mock_call_later.assert_not_called()
        assert coordinator._unsub_delayed_clock_refresh is None

    def test_nordpool_update_cancels_pending_fallback(self):
        """Nord Pool updates should cancel the delayed fallback refresh."""
        coordinator = _make_coordinator_for_refresh_tracking()
        pending_unsub = MagicMock()
        coordinator._unsub_delayed_clock_refresh = pending_unsub
        now = datetime(2026, 2, 6, 13, 0, 0, tzinfo=timezone.utc)

        with patch(
            "custom_components.power_saver.coordinator.dt_util.utcnow",
            return_value=now,
        ):
            coordinator._on_nordpool_update(MagicMock())

        pending_unsub.assert_called_once()
        assert coordinator._unsub_delayed_clock_refresh is None
        assert coordinator._last_nordpool_refresh_request == now
        coordinator.async_request_refresh.assert_called_once()
        coordinator.hass.async_create_task.assert_called_once()

    def test_native_update_cancels_pending_fallback(self):
        """Native coordinator updates should cancel the delayed fallback refresh."""
        coordinator = _make_coordinator_for_refresh_tracking(NORDPOOL_TYPE_NATIVE)
        pending_unsub = MagicMock()
        coordinator._unsub_delayed_clock_refresh = pending_unsub
        now = datetime(2026, 2, 6, 13, 0, 0, tzinfo=timezone.utc)

        with patch(
            "custom_components.power_saver.coordinator.dt_util.utcnow",
            return_value=now,
        ):
            coordinator._on_native_coordinator_update()

        pending_unsub.assert_called_once()
        assert coordinator._unsub_delayed_clock_refresh is None
        assert coordinator._last_nordpool_refresh_request == now
        coordinator.async_request_refresh.assert_called_once()
        coordinator.hass.async_create_task.assert_called_once()

    def test_delayed_clock_refresh_requests_refresh(self):
        """Delayed fallback callback should request a coordinator refresh."""
        coordinator = _make_coordinator_for_refresh_tracking()
        coordinator._unsub_delayed_clock_refresh = MagicMock()

        coordinator._on_clock_refresh_delay_elapsed(datetime(2026, 2, 6, 14, 0))

        assert coordinator._unsub_delayed_clock_refresh is None
        coordinator.async_request_refresh.assert_called_once()
        coordinator.hass.async_create_task.assert_called_once()

    async def test_shutdown_cancels_refresh_tracking_callbacks(self):
        """Shutdown should clean up all refresh listeners and pending callbacks."""
        coordinator = _make_coordinator_for_refresh_tracking()
        coordinator._store = MagicMock()
        coordinator._store.async_save = AsyncMock()
        coordinator._last_on_time = None
        coordinator._hours_override = None
        coordinator._exclude_from_override = None
        coordinator._exclude_until_override = None
        coordinator._refresh_tracking_setup = True
        coordinator._unsub_nordpool = MagicMock()
        coordinator._unsub_native_coordinator = MagicMock()
        coordinator._unsub_clock_refresh = MagicMock()
        coordinator._unsub_delayed_clock_refresh = MagicMock()

        with patch(
            "custom_components.power_saver.coordinator.DataUpdateCoordinator.async_shutdown",
            new=AsyncMock(),
        ) as mock_super_shutdown:
            await coordinator.async_shutdown()

        assert coordinator._refresh_tracking_setup is False
        assert coordinator._unsub_nordpool is None
        assert coordinator._unsub_native_coordinator is None
        assert coordinator._unsub_clock_refresh is None
        assert coordinator._unsub_delayed_clock_refresh is None
        mock_super_shutdown.assert_awaited_once()


class TestLockedSchedule:
    """Tests for the locked schedule behavior.

    These test the scheduling logic at the scheduler level to verify
    that a schedule computed once remains stable and correct.
    """

    def test_schedule_is_deterministic(self, now, today_prices):
        """The same inputs always produce the same schedule."""
        schedule1 = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=1.0,
            now=now,
            min_consecutive_hours=1.0,
        )
        schedule2 = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=1.0,
            now=now,
            min_consecutive_hours=1.0,
        )
        assert schedule1 == schedule2

    def test_one_hour_cheapest_produces_exactly_four_active_slots(self, now, today_prices):
        """With min_hours=1 and min_consecutive=1, exactly 4 slots should be active."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=1.0,
            now=now,
            min_consecutive_hours=1.0,
        )
        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) == 4, (
            f"Expected exactly 4 active slots (1 hour) but got {len(active)}"
        )

    def test_schedule_does_not_drift_with_advancing_now(self, today_prices):
        """Rebuilding the schedule at different times should not create extra slots.

        This is the core regression test for the schedule drift bug.
        """
        now_1030 = datetime(2026, 2, 6, 10, 30, 0, tzinfo=TZ)
        schedule_1030 = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=1.0,
            now=now_1030,
            min_consecutive_hours=1.0,
        )

        now_1045 = datetime(2026, 2, 6, 10, 45, 0, tzinfo=TZ)
        schedule_1045 = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=1.0,
            now=now_1045,
            min_consecutive_hours=1.0,
        )

        now_1230 = datetime(2026, 2, 6, 12, 30, 0, tzinfo=TZ)
        schedule_1230 = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=1.0,
            now=now_1230,
            min_consecutive_hours=1.0,
        )

        # All schedules should have exactly 4 active slots
        for label, schedule in [
            ("10:30", schedule_1030),
            ("10:45", schedule_1045),
            ("12:30", schedule_1230),
        ]:
            active = [s for s in schedule if s["status"] == "active"]
            assert len(active) == 4, (
                f"Schedule at {label} has {len(active)} active slots, expected 4"
            )

    def test_locked_schedule_covers_full_day(self, now, today_prices, tomorrow_prices):
        """Schedule with tomorrow data should cover both days."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=tomorrow_prices,
            min_hours=1.0,
            now=now,
        )
        assert len(schedule) == 192  # 96 today + 96 tomorrow

    def test_minimum_runtime_no_drift(self, today_prices):
        """Minimum runtime schedule should also be stable across rebuilds."""
        now_1030 = datetime(2026, 2, 6, 10, 30, 0, tzinfo=TZ)
        last_on = now_1030 - timedelta(hours=6)

        schedule_1030 = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.0,
            now=now_1030,
            strategy="minimum_runtime",
            max_hours_off=8.0,
            last_on_time=last_on,
            min_consecutive_hours=1.0,
        )

        now_1045 = datetime(2026, 2, 6, 10, 45, 0, tzinfo=TZ)
        schedule_1045 = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.0,
            now=now_1045,
            strategy="minimum_runtime",
            max_hours_off=8.0,
            last_on_time=last_on,
            min_consecutive_hours=1.0,
        )

        active_1030 = sum(1 for s in schedule_1030 if s["status"] == "active")
        active_1045 = sum(1 for s in schedule_1045 if s["status"] == "active")

        # Active counts should be equal or very close (not inflating)
        assert abs(active_1030 - active_1045) <= 1, (
            f"Schedule drift: {active_1030} active at 10:30 vs {active_1045} at 10:45"
        )

    def test_consecutive_blocks_are_correct_length(self, now, today_prices):
        """Active blocks should be exactly min_consecutive_hours long."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.0,
            now=now,
            min_consecutive_hours=1.0,
        )
        blocks = scheduler._find_active_blocks(schedule)
        for start, length in blocks:
            assert length >= 4, (
                f"Block at {schedule[start]['time']} has length {length}, "
                f"expected >= 4 (1 hour)"
            )


class TestScheduleExtension:
    """Tests for schedule behavior when tomorrow prices are added."""

    def test_tomorrow_prices_extend_schedule(self, now, today_prices, tomorrow_prices):
        """Adding tomorrow prices should produce a longer schedule."""
        schedule_today = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=1.0,
            now=now,
        )
        schedule_both = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=tomorrow_prices,
            min_hours=1.0,
            now=now,
        )
        assert len(schedule_both) > len(schedule_today)

    def test_schedule_with_only_today_is_valid(self, now, today_prices):
        """Schedule with only today data should still produce valid output."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=1.0,
            now=now,
        )
        assert len(schedule) == 96
        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) >= 4  # At least 1 hour of active slots

    def test_empty_tomorrow_does_not_break_schedule(self, now, today_prices):
        """Empty tomorrow list should work the same as no tomorrow data."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.0,
            now=now,
        )
        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) == 8  # 2.0 hours = 8 slots


class TestShouldRecomputeSchedule:
    """Tests for _should_recompute_schedule on the coordinator.

    Uses a minimal mock of the coordinator to test the recompute decision
    logic directly, covering all four trigger conditions.
    """

    @pytest.fixture
    def mock_coordinator(self):
        """Create a minimal mock that has the coordinator's recompute logic."""
        from custom_components.power_saver.coordinator import PowerSaverCoordinator

        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_123"
        entry.data = {
            "nordpool_sensor": "sensor.nordpool",
            "nordpool_type": "hacs",
        }
        entry.options = {
            "strategy": "lowest_price",
            "hours_per_period": 2.5,
        }

        with patch(
            "custom_components.power_saver.coordinator.Store"
        ):
            coord = PowerSaverCoordinator(hass, entry)
        return coord

    @pytest.fixture
    def sample_schedule(self, now, today_prices):
        """Build a sample schedule for use in recompute tests."""
        return build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=1.0,
            now=now,
        )

    def test_returns_true_when_no_locked_schedule(self, mock_coordinator, now):
        """No locked schedule (first run) should trigger recompute."""
        assert mock_coordinator._locked_schedule is None
        assert mock_coordinator._should_recompute_schedule([], now) is True

    def test_returns_true_when_tomorrow_prices_appear(
        self, mock_coordinator, now, sample_schedule, tomorrow_prices
    ):
        """New tomorrow prices should trigger recompute."""
        mock_coordinator._locked_schedule = sample_schedule
        mock_coordinator._schedule_has_tomorrow = False
        mock_coordinator._options_fingerprint = (
            mock_coordinator._compute_options_fingerprint()
        )

        assert mock_coordinator._should_recompute_schedule(
            tomorrow_prices, now
        ) is True

    def test_returns_true_when_schedule_expired(
        self, mock_coordinator, sample_schedule
    ):
        """All slots in the past should trigger recompute."""
        mock_coordinator._locked_schedule = sample_schedule
        mock_coordinator._schedule_has_tomorrow = False
        mock_coordinator._options_fingerprint = (
            mock_coordinator._compute_options_fingerprint()
        )

        # Advance time past the last slot
        last_slot = datetime.fromisoformat(sample_schedule[-1]["time"])
        future = last_slot + timedelta(hours=1)

        assert mock_coordinator._should_recompute_schedule([], future) is True

    def test_returns_true_when_options_changed(
        self, mock_coordinator, now, sample_schedule
    ):
        """Changed options (fingerprint mismatch) should trigger recompute."""
        mock_coordinator._locked_schedule = sample_schedule
        mock_coordinator._schedule_has_tomorrow = False
        mock_coordinator._options_fingerprint = (
            mock_coordinator._compute_options_fingerprint()
        )

        # Change an option that affects the schedule
        mock_coordinator.config_entry.options = {
            "strategy": "lowest_price",
            "hours_per_period": 5.0,  # Changed from 2.5
        }

        assert mock_coordinator._should_recompute_schedule([], now) is True

    def test_returns_false_when_nothing_changed(
        self, mock_coordinator, now, sample_schedule
    ):
        """No trigger conditions → reuse existing schedule."""
        mock_coordinator._locked_schedule = sample_schedule
        mock_coordinator._schedule_has_tomorrow = False
        mock_coordinator._options_fingerprint = (
            mock_coordinator._compute_options_fingerprint()
        )

        assert mock_coordinator._should_recompute_schedule([], now) is False

    def test_returns_false_when_tomorrow_already_included(
        self, mock_coordinator, now, today_prices, tomorrow_prices
    ):
        """Tomorrow prices present and already incorporated → no recompute."""
        # Build schedule that actually includes tomorrow's data
        schedule_with_tomorrow = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=tomorrow_prices,
            min_hours=1.0,
            now=now,
        )
        mock_coordinator._locked_schedule = schedule_with_tomorrow
        mock_coordinator._schedule_has_tomorrow = True
        mock_coordinator._options_fingerprint = (
            mock_coordinator._compute_options_fingerprint()
        )

        assert mock_coordinator._should_recompute_schedule(
            tomorrow_prices, now
        ) is False

    def test_controlled_entities_change_does_not_trigger_recompute(
        self, mock_coordinator, now, sample_schedule
    ):
        """Changing controlled_entities should NOT trigger recompute."""
        mock_coordinator._locked_schedule = sample_schedule
        mock_coordinator._schedule_has_tomorrow = False
        mock_coordinator._options_fingerprint = (
            mock_coordinator._compute_options_fingerprint()
        )

        # Change only controlled_entities (not a schedule-affecting option)
        opts = dict(mock_coordinator.config_entry.options)
        opts["controlled_entities"] = ["switch.heater"]
        mock_coordinator.config_entry.options = opts

        assert mock_coordinator._should_recompute_schedule([], now) is False

    def test_returns_true_when_locked_schedule_is_empty_list(
        self, mock_coordinator, now
    ):
        """Empty locked schedule should trigger recompute."""
        mock_coordinator._locked_schedule = []
        assert mock_coordinator._should_recompute_schedule([], now) is True

    def test_returns_true_when_last_slot_missing_time_key(
        self, mock_coordinator, now
    ):
        """Malformed slot (missing 'time' key) should trigger recompute."""
        mock_coordinator._locked_schedule = [{"price": 0.10, "status": "standby"}]
        mock_coordinator._options_fingerprint = (
            mock_coordinator._compute_options_fingerprint()
        )
        mock_coordinator._schedule_has_tomorrow = False

        assert mock_coordinator._should_recompute_schedule([], now) is True

    def test_returns_true_when_tomorrow_extends_beyond_schedule(
        self, mock_coordinator, now, today_prices, tomorrow_prices
    ):
        """After midnight, new tomorrow (day+2) prices should trigger recompute.

        Scenario: schedule was computed yesterday with today+tomorrow data.
        Now it's the next day and raw_tomorrow contains the day after tomorrow.
        The schedule's last slot is older than the newest tomorrow slot.
        """
        # Build schedule covering Feb 6 + Feb 7 (day_offset=0 and 1)
        schedule_with_tomorrow = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=tomorrow_prices,
            min_hours=1.0,
            now=now,
        )
        mock_coordinator._locked_schedule = schedule_with_tomorrow
        mock_coordinator._schedule_has_tomorrow = True
        mock_coordinator._options_fingerprint = (
            mock_coordinator._compute_options_fingerprint()
        )

        # Simulate being on Feb 7 with raw_tomorrow = Feb 8 (day_offset=2)
        day_after_tomorrow = [
            slot for h, p in enumerate([0.05] * 24)
            for slot in make_nordpool_hour(h, p, day_offset=2)
        ]
        now_next_day = now + timedelta(days=1)

        assert mock_coordinator._should_recompute_schedule(
            day_after_tomorrow, now_next_day
        ) is True

    def test_returns_true_when_last_slot_has_bad_time(
        self, mock_coordinator, now
    ):
        """Malformed slot (bad ISO string) should trigger recompute."""
        mock_coordinator._locked_schedule = [
            {"price": 0.10, "status": "standby", "time": "not-a-date"}
        ]
        mock_coordinator._options_fingerprint = (
            mock_coordinator._compute_options_fingerprint()
        )
        mock_coordinator._schedule_has_tomorrow = False

        assert mock_coordinator._should_recompute_schedule([], now) is True
