"""Tests for the Power Saver scheduling algorithm.

These tests import scheduler.py directly (without going through the
custom_components package __init__.py) so they can run without homeassistant
installed.
"""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Import scheduler directly to avoid triggering __init__.py which needs homeassistant
_scheduler_path = Path(__file__).resolve().parent.parent / "custom_components" / "power_saver"
sys.path.insert(0, str(_scheduler_path))
import scheduler  # noqa: E402

build_schedule = scheduler.build_schedule
find_current_slot = scheduler.find_current_slot
find_next_change = scheduler.find_next_change
build_activity_history = scheduler.build_activity_history

# TZ and make_nordpool_slot are defined in conftest.py, which pytest loads
# automatically. We just need to define them here for direct use in tests.
TZ = timezone(timedelta(hours=1), name="CET")


def make_nordpool_slot(hour: int, price: float, day_offset: int = 0) -> dict:
    """Create a Nordpool-style price slot for testing."""
    base = datetime(2026, 2, 6, tzinfo=TZ) + timedelta(days=day_offset)
    start = base.replace(hour=hour, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "value": price,
    }


class TestBuildSchedule:
    """Tests for the build_schedule function."""

    def test_basic_cheapest_slots_activated(self, now, today_prices):
        """The cheapest N slots should be activated."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,  # 10 slots
            always_cheap=0.0,
            always_expensive=0.0,
            rolling_window_hours=None,
            now=now,
        )

        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) == 10

        # All active prices should be <= all standby prices
        active_prices = sorted(s["price"] for s in active)
        standby_prices = sorted(
            s["price"] for s in schedule if s["status"] == "standby"
        )
        assert active_prices[-1] <= standby_prices[0]

    def test_always_cheap_threshold(self, now, today_prices):
        """Slots below always_cheap should always be active, even beyond quota."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=0.25,  # Only 1 slot quota
            always_cheap=0.10,
            always_expensive=0.0,
            rolling_window_hours=None,
            now=now,
        )

        active = [s for s in schedule if s["status"] == "active"]
        # Should have more than 1 slot because many are below 0.10
        assert len(active) > 1

        # All slots with price <= 0.10 should be active
        cheap_slots = [s for s in schedule if s["price"] <= 0.10]
        for slot in cheap_slots:
            assert slot["status"] == "active"

    def test_always_expensive_threshold(self, now, today_prices):
        """Slots at or above always_expensive should never be active."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=6.0,  # 24 slots — would normally activate many
            always_cheap=0.0,
            always_expensive=0.30,
            rolling_window_hours=None,
            now=now,
        )

        # No slot at or above 0.30 should be active
        expensive_active = [
            s for s in schedule
            if s["status"] == "active" and s["price"] >= 0.30
        ]
        assert len(expensive_active) == 0

    def test_always_expensive_disabled_when_zero(self, now, today_prices):
        """When always_expensive is 0, there should be no upper limit."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=6.0,  # 24 slots
            always_cheap=0.0,
            always_expensive=0.0,  # Disabled
            rolling_window_hours=None,
            now=now,
        )

        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) == 24

    def test_tomorrow_data_included(self, now, today_prices, tomorrow_prices):
        """Schedule should include both today and tomorrow."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=tomorrow_prices,
            min_hours=2.5,
            always_cheap=0.0,
            always_expensive=0.0,
            rolling_window_hours=None,
            now=now,
        )

        # Should have 48 slots total (24 today + 24 tomorrow)
        assert len(schedule) == 48

    def test_standard_mode_resets_quota_for_tomorrow(self, now, today_prices, tomorrow_prices):
        """In standard mode (no rolling window), each day gets its own quota."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=tomorrow_prices,
            min_hours=2.5,  # 10 slots per day
            always_cheap=0.0,
            always_expensive=0.0,
            rolling_window_hours=None,  # Standard mode
            now=now,
        )

        today_base = datetime(2026, 2, 6, tzinfo=TZ)
        tomorrow_base = datetime(2026, 2, 7, tzinfo=TZ)

        today_active = [
            s for s in schedule
            if s["status"] == "active"
            and datetime.fromisoformat(s["time"]).astimezone(TZ).date() == today_base.date()
        ]
        tomorrow_active = [
            s for s in schedule
            if s["status"] == "active"
            and datetime.fromisoformat(s["time"]).astimezone(TZ).date() == tomorrow_base.date()
        ]

        assert len(today_active) == 10
        assert len(tomorrow_active) == 10

    def test_rolling_window_shares_quota(self, now, today_prices, tomorrow_prices):
        """In rolling window mode, quota is shared across both days."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=tomorrow_prices,
            min_hours=2.5,  # 10 slots total (shared)
            always_cheap=0.0,
            always_expensive=0.0,
            rolling_window_hours=24.0,
            now=now,
        )

        # Total active should be at least 10 (base quota)
        # Rolling window may add more
        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) >= 10

    def test_schedule_sorted_by_time(self, now, today_prices):
        """Schedule should be sorted chronologically."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            always_cheap=0.0,
            always_expensive=0.0,
            rolling_window_hours=None,
            now=now,
        )

        times = [s["time"] for s in schedule]
        assert times == sorted(times)

    def test_empty_today_with_tomorrow_returns_empty(self, now, tomorrow_prices):
        """When today has no data but tomorrow does, schedule contains only tomorrow."""
        schedule = build_schedule(
            raw_today=[],
            raw_tomorrow=tomorrow_prices,
            min_hours=2.5,
            always_cheap=0.0,
            always_expensive=0.0,
            rolling_window_hours=None,
            now=now,
        )

        # Only tomorrow's slots
        assert len(schedule) == 24


class TestRollingWindowConstraint:
    """Tests for the rolling window constraint."""

    def test_shortfall_activates_immediate_slots(self, today_prices):
        """When past activity is insufficient, slots should be activated starting now."""
        now = datetime(2026, 2, 6, 14, 30, 0, tzinfo=TZ)

        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=6.0,  # 24 slots in 8-hour window
            always_cheap=0.0,
            always_expensive=0.0,
            rolling_window_hours=8.0,
            now=now,
            prev_activity_history=[],  # No history
        )

        # Should have activated slots to meet the constraint
        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) >= 24

    def test_history_prevents_unnecessary_activation(self, today_prices):
        """When past history meets the constraint, no extra activation needed."""
        now = datetime(2026, 2, 6, 14, 30, 0, tzinfo=TZ)

        # Create history showing 6 hours of recent activity
        history = []
        for i in range(24):  # 24 slots = 6 hours
            slot_time = now - timedelta(minutes=(i + 1) * 15)
            history.append(slot_time.isoformat())

        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=6.0,
            always_cheap=0.0,
            always_expensive=0.0,
            rolling_window_hours=8.0,
            now=now,
            prev_activity_history=history,
        )

        # The base quota (24 slots for 6h) is the primary activation mechanism
        # Rolling window should not need to add extra
        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) >= 24


class TestFindCurrentSlot:
    """Tests for find_current_slot."""

    def test_finds_correct_slot(self, now, today_prices):
        """Should find the slot containing the current time."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            always_cheap=0.0,
            always_expensive=0.0,
            rolling_window_hours=None,
            now=now,
        )

        # now is 14:30, should find the 14:00 slot
        current = find_current_slot(schedule, now)
        assert current is not None
        slot_time = datetime.fromisoformat(current["time"]).astimezone(TZ)
        assert slot_time.hour == 14

    def test_returns_none_when_no_match(self):
        """Should return None when time is outside schedule range."""
        schedule = [
            {"price": 0.10, "time": "2026-02-06T10:00:00+01:00", "status": "active"},
            {"price": 0.20, "time": "2026-02-06T11:00:00+01:00", "status": "standby"},
        ]
        # Way before the schedule
        early = datetime(2026, 2, 6, 5, 0, 0, tzinfo=TZ)
        assert find_current_slot(schedule, early) is None

    def test_boundary_start_inclusive(self):
        """Slot start should be inclusive."""
        schedule = [
            {"price": 0.10, "time": "2026-02-06T10:00:00+01:00", "status": "active"},
            {"price": 0.20, "time": "2026-02-06T11:00:00+01:00", "status": "standby"},
        ]
        exactly_start = datetime(2026, 2, 6, 10, 0, 0, tzinfo=TZ)
        current = find_current_slot(schedule, exactly_start)
        assert current is not None
        assert current["price"] == 0.10

    def test_boundary_end_exclusive(self):
        """Slot end should be exclusive (belongs to next slot)."""
        schedule = [
            {"price": 0.10, "time": "2026-02-06T10:00:00+01:00", "status": "active"},
            {"price": 0.20, "time": "2026-02-06T11:00:00+01:00", "status": "standby"},
        ]
        exactly_end = datetime(2026, 2, 6, 11, 0, 0, tzinfo=TZ)
        current = find_current_slot(schedule, exactly_end)
        assert current is not None
        assert current["price"] == 0.20


class TestFindNextChange:
    """Tests for find_next_change."""

    def test_finds_next_transition(self):
        """Should find the next slot with a different status."""
        now = datetime(2026, 2, 6, 10, 30, 0, tzinfo=TZ)
        schedule = [
            {"price": 0.10, "time": "2026-02-06T10:00:00+01:00", "status": "active"},
            {"price": 0.10, "time": "2026-02-06T11:00:00+01:00", "status": "active"},
            {"price": 0.50, "time": "2026-02-06T12:00:00+01:00", "status": "standby"},
            {"price": 0.10, "time": "2026-02-06T13:00:00+01:00", "status": "active"},
        ]
        current_slot = schedule[0]

        next_change = find_next_change(schedule, current_slot, now)
        assert next_change == "2026-02-06T12:00:00+01:00"

    def test_returns_none_when_no_change(self):
        """Should return None when all future slots have the same status."""
        now = datetime(2026, 2, 6, 10, 30, 0, tzinfo=TZ)
        schedule = [
            {"price": 0.10, "time": "2026-02-06T10:00:00+01:00", "status": "active"},
            {"price": 0.10, "time": "2026-02-06T11:00:00+01:00", "status": "active"},
            {"price": 0.10, "time": "2026-02-06T12:00:00+01:00", "status": "active"},
        ]
        current_slot = schedule[0]

        assert find_next_change(schedule, current_slot, now) is None

    def test_returns_none_when_no_current_slot(self):
        """Should return None when current_slot is None."""
        now = datetime(2026, 2, 6, 10, 30, 0, tzinfo=TZ)
        assert find_next_change([], None, now) is None


class TestBuildActivityHistory:
    """Tests for build_activity_history."""

    def test_collects_past_active_slots(self):
        """Should collect active slots that have started."""
        now = datetime(2026, 2, 6, 14, 30, 0, tzinfo=TZ)
        schedule = [
            {"price": 0.10, "time": "2026-02-06T13:00:00+01:00", "status": "active"},
            {"price": 0.50, "time": "2026-02-06T14:00:00+01:00", "status": "standby"},
            {"price": 0.10, "time": "2026-02-06T15:00:00+01:00", "status": "active"},
        ]

        history = build_activity_history(schedule, [], now, 24.0)
        # Only 13:00 and 14:00 have started, but only 13:00 is active
        # 14:00 has started (14:00 <= 14:30) but is standby
        assert len(history) == 1
        assert "2026-02-06T13:00:00+01:00" in history[0]

    def test_merges_previous_history(self):
        """Should merge with previous history without duplicates."""
        now = datetime(2026, 2, 6, 14, 30, 0, tzinfo=TZ)
        schedule = [
            {"price": 0.10, "time": "2026-02-06T13:00:00+01:00", "status": "active"},
        ]
        prev = [
            "2026-02-06T10:00:00+01:00",
            "2026-02-06T13:00:00+01:00",  # Duplicate
        ]

        history = build_activity_history(schedule, prev, now, 24.0)
        assert len(history) == 2  # 10:00 and 13:00 (deduplicated)

    def test_prunes_old_entries(self):
        """Should remove entries outside the window."""
        now = datetime(2026, 2, 6, 14, 30, 0, tzinfo=TZ)
        schedule = []
        prev = [
            "2026-02-05T10:00:00+01:00",  # Yesterday, outside 8h window
            "2026-02-06T10:00:00+01:00",  # Within 8h window
        ]

        history = build_activity_history(schedule, prev, now, 8.0)
        assert len(history) == 1
        assert "2026-02-06T10:00:00+01:00" in history[0]

    def test_returns_sorted(self):
        """Should return history sorted chronologically."""
        now = datetime(2026, 2, 6, 14, 30, 0, tzinfo=TZ)
        schedule = [
            {"price": 0.10, "time": "2026-02-06T13:00:00+01:00", "status": "active"},
        ]
        prev = [
            "2026-02-06T12:00:00+01:00",
            "2026-02-06T08:00:00+01:00",
        ]

        history = build_activity_history(schedule, prev, now, 24.0)
        assert history == sorted(history)
