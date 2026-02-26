"""Tests for the Power Saver scheduling algorithm.

These tests import scheduler.py directly (without going through the
custom_components package __init__.py) so they can run without homeassistant
installed.
"""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta
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
_find_active_blocks = scheduler._find_active_blocks
_is_excluded = scheduler._is_excluded

from helpers import TZ, make_nordpool_hour, make_nordpool_slot


class TestBuildSchedule:
    """Tests for the build_schedule function."""

    def test_basic_cheapest_slots_activated(self, now, today_prices):
        """The cheapest N slots should be activated."""
        # Provide history to satisfy rolling window lookback
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 11)]
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,  # 10 slots
            now=now,
            prev_activity_history=history,
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
            now=now,
            always_cheap=0.10,
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
        # Provide history to satisfy rolling window lookback
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 25)]
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=6.0,  # 24 slots — would normally activate many
            now=now,
            always_expensive=0.30,
            prev_activity_history=history,
        )

        # No slot at or above 0.30 should be active
        expensive_active = [
            s for s in schedule
            if s["status"] == "active" and s["price"] >= 0.30
        ]
        assert len(expensive_active) == 0

    def test_always_expensive_disabled_when_none(self, now, today_prices):
        """When always_expensive is None, there should be no upper limit."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=6.0,  # 24 slots
            now=now,
            always_expensive=None,
        )

        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) == 24

    def test_tomorrow_data_included(self, now, today_prices, tomorrow_prices):
        """Schedule should include both today and tomorrow."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=tomorrow_prices,
            min_hours=2.5,
            now=now,
        )

        # Should have 192 slots total (96 today + 96 tomorrow)
        assert len(schedule) == 192

    def test_rolling_window_shares_quota(self, now, today_prices, tomorrow_prices):
        """In rolling window mode, quota is shared across both days."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=tomorrow_prices,
            min_hours=2.5,  # 10 slots total (shared)
            now=now,
            rolling_window_hours=24.0,
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
            now=now,
        )

        # Only tomorrow's slots
        assert len(schedule) == 96


class TestPriceSimilarityThreshold:
    """Tests for the price similarity threshold feature."""

    def test_threshold_activates_extra_slots(self, now):
        """Slots within the threshold percentage of the cheapest should be activated."""
        # Flat prices: all between 0.10 and 0.13 (4 quarter-hour slots per hour)
        prices = [slot for h in range(24) for slot in make_nordpool_hour(h, 0.10 + (h % 4) * 0.01)]
        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=2.5,  # 10 slots normally
            now=now,
            price_similarity_pct=20.0,  # 20% of 0.10 = threshold 0.12
        )

        active = [s for s in schedule if s["status"] == "active"]
        # Should activate more than the 10 minimum slots
        # Slots with price <= 0.12 should all be active (0.10, 0.11, 0.12)
        assert len(active) > 10
        # Slots at 0.13 should NOT be active (0.13 > 0.12)
        for s in schedule:
            if s["price"] == 0.13:
                assert s["status"] == "standby"

    def test_threshold_disabled_when_none(self, now, today_prices):
        """When threshold is None, only min_hours worth of cheapest slots activate."""
        # Provide history to satisfy rolling window lookback
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 11)]
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            price_similarity_pct=None,
            prev_activity_history=history,
        )

        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) == 10  # Exactly min_hours * 4

    def test_threshold_respects_always_expensive(self, now):
        """Threshold should not activate slots above always_expensive."""
        # All prices clustered around 0.50
        prices = [slot for h in range(24) for slot in make_nordpool_hour(h, 0.50 + h * 0.01)]
        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=1.0,  # 4 slots
            now=now,
            always_expensive=0.55,  # Hard cutoff
            price_similarity_pct=50.0,  # Would expand to 0.75 but capped by always_expensive
        )

        # No slot at or above 0.55 should be active
        for s in schedule:
            if s["price"] >= 0.55:
                assert s["status"] == "standby"

    def test_threshold_works_for_negative_prices(self, now):
        """When cheapest price is negative, threshold should apply using additive offset."""
        # 4 negative-price hours, then 20 expensive hours (4 quarter-slots each)
        prices = (
            [slot for h in range(4) for slot in make_nordpool_hour(h, -0.10 + h * 0.02)]
            + [slot for h in range(4, 24) for slot in make_nordpool_hour(h, 0.50)]
        )
        # min_price = -0.10, pct = 50% → offset = 0.05, threshold = -0.05
        # Hours <= -0.05: h0(-0.10), h1(-0.08), h2(-0.06) = 3 hours × 4 slots = 12 slots
        # always_cheap=-1.0 so it doesn't activate negative prices on its own
        schedule_with = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=0.25,  # 1 slot quota
            now=now,
            always_cheap=-1.0,
            price_similarity_pct=50.0,
        )
        schedule_without = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=0.25,
            now=now,
            always_cheap=-1.0,
        )

        active_with = [s for s in schedule_with if s["status"] == "active"]
        active_without = [s for s in schedule_without if s["status"] == "active"]

        # Without threshold: only 1 slot (min_hours quota)
        assert len(active_without) == 1
        # With threshold: 3 hours × 4 quarter-slots = 12 active slots
        assert len(active_with) == 12
        assert all(s["price"] <= -0.05 for s in active_with)

    def test_threshold_applies_to_tomorrow_independently(self, now):
        """Tomorrow should use its own cheapest price for threshold calculation."""
        today = [slot for h in range(24) for slot in make_nordpool_hour(h, 0.10)]
        tomorrow = [slot for h in range(24) for slot in make_nordpool_hour(h, 0.50 + h * 0.01, day_offset=1)]

        schedule = build_schedule(
            raw_today=today,
            raw_tomorrow=tomorrow,
            min_hours=0.25,  # 1 slot quota only
            now=now,
            price_similarity_pct=10.0,  # 10% of 0.50 = threshold at 0.55 for tomorrow
        )

        tomorrow_base = datetime(2026, 2, 7, tzinfo=TZ)
        tomorrow_active = [
            s for s in schedule
            if s["status"] == "active"
            and datetime.fromisoformat(s["time"]).astimezone(TZ).date() == tomorrow_base.date()
        ]

        # Tomorrow's threshold: 0.50 * 1.10 = 0.55
        # Hours 0-5 at prices 0.50-0.55 should be active = 6 hours × 4 slots = 24 slots
        # More than just the 1 min_hours slot
        assert len(tomorrow_active) == 24
        # All active tomorrow slots should be <= 0.55
        for s in tomorrow_active:
            assert s["price"] <= 0.55


class TestRollingWindowConstraint:
    """Tests for the rolling window constraint."""

    def test_shortfall_activates_immediate_slots(self, today_prices):
        """When past activity is insufficient, slots should be activated starting now."""
        now = datetime(2026, 2, 6, 14, 30, 0, tzinfo=TZ)

        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=6.0,  # 24 slots in 8-hour window
            now=now,
            rolling_window_hours=8.0,
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
            now=now,
            rolling_window_hours=8.0,
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
            now=now,
        )

        # now is 14:30, should find the 14:30 slot (quarter=2 of hour 14)
        current = find_current_slot(schedule, now)
        assert current is not None
        slot_time = datetime.fromisoformat(current["time"]).astimezone(TZ)
        assert slot_time.hour == 14
        assert slot_time.minute == 30

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


class TestFindActiveBlocks:
    """Tests for the _find_active_blocks helper."""

    def test_single_block(self):
        """Should find one contiguous block."""
        schedule = [
            {"status": "standby"},
            {"status": "active"},
            {"status": "active"},
            {"status": "active"},
            {"status": "standby"},
        ]
        blocks = _find_active_blocks(schedule)
        assert blocks == [(1, 3)]

    def test_multiple_blocks(self):
        """Should find multiple separate blocks."""
        schedule = [
            {"status": "active"},
            {"status": "active"},
            {"status": "standby"},
            {"status": "active"},
            {"status": "standby"},
            {"status": "active"},
            {"status": "active"},
        ]
        blocks = _find_active_blocks(schedule)
        assert blocks == [(0, 2), (3, 1), (5, 2)]

    def test_no_active(self):
        """Should return empty list when no active slots."""
        schedule = [{"status": "standby"}, {"status": "standby"}]
        assert _find_active_blocks(schedule) == []

    def test_all_active(self):
        """Should return one block spanning the entire schedule."""
        schedule = [{"status": "active"}, {"status": "active"}, {"status": "active"}]
        assert _find_active_blocks(schedule) == [(0, 3)]


class TestMinConsecutiveHours:
    """Tests for the minimum consecutive active hours feature."""

    def test_short_block_gets_extended(self, now):
        """A single short block should be extended to meet the minimum."""
        # now=14:30 — put cheap hours in the future (h16, h20)
        prices = [slot for h, p in enumerate([
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.10, 0.50, 0.50, 0.50,  # hour 16 cheap, isolated
            0.10, 0.50, 0.50, 0.50,         # hour 20 cheap, isolated
        ]) for slot in make_nordpool_hour(h, p)]
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 9)]

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=2.0,  # 8 slots → activates hours 16(4) and 20(4) (cheapest)
            now=now,
            prev_activity_history=history,
            min_consecutive_hours=2,  # Each block must be >= 2 hours (8 quarter-slots)
        )

        # Find future active blocks
        future_blocks = [
            (start, length) for start, length in _find_active_blocks(schedule)
            if start >= 0 and datetime.fromisoformat(schedule[start]["time"]).astimezone(TZ) >= now
        ]
        # All future blocks should be at least 8 quarter-slots (2 hours)
        for start, length in future_blocks:
            assert length >= 8, f"Block at index {start} has length {length}, expected >= 8"

    def test_gap_filling_merges_blocks(self, now):
        """Two nearby blocks with a small gap should merge when gap is filled."""
        # now=14:30 — put cheap hours in the future (h16-17, h19-20, gap at h18)
        prices = [slot for h, p in enumerate([
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.01, 0.01, 0.30, 0.01,  # h16-17 cheap, h18 moderate, h19 cheap
            0.01, 0.50, 0.50, 0.50,         # h20 cheap
        ]) for slot in make_nordpool_hour(h, p)]
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 17)]

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=3.0,  # 12 slots → activates h16(4), h17(4), h19(4) (cheapest)
            now=now,
            prev_activity_history=history,
            min_consecutive_hours=3,  # Need blocks of at least 3 hours (12 quarter-slots)
        )

        # Future blocks should be merged (gap at h18 filled)
        future_blocks = [
            (start, length) for start, length in _find_active_blocks(schedule)
            if datetime.fromisoformat(schedule[start]["time"]).astimezone(TZ) >= now
        ]
        for start, length in future_blocks:
            assert length >= 12, f"Block at index {start} has length {length}, expected >= 12"

    def test_always_expensive_blocks_extension(self, now):
        """Slots at or above always_expensive should never be activated for extension."""
        # now=14:30 — put cheap hours in the future with expensive barrier
        prices = [slot for h, p in enumerate([
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.01, 5.00, 0.01, 0.50,  # h16 cheap, h17 very expensive, h18 cheap
            0.50, 0.50, 0.50, 0.50,
        ]) for slot in make_nordpool_hour(h, p)]
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 9)]

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=0.5,  # 2 slots → h16 and h18
            now=now,
            always_expensive=4.00,
            prev_activity_history=history,
            min_consecutive_hours=3,  # Want 3 consecutive, but blocked by expensive
        )

        # The expensive slot (hour 17, price 5.00) must stay standby
        for s in schedule:
            if s["price"] >= 4.00:
                assert s["status"] == "standby", f"Expensive slot at {s['time']} should be standby"

    def test_disabled_when_none(self, now, today_prices):
        """When min_consecutive_hours is None, no changes should be made."""
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 11)]

        schedule_without = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            prev_activity_history=history,
            min_consecutive_hours=None,
        )
        schedule_default = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            prev_activity_history=history,
        )

        # Both should produce identical schedules
        assert len(schedule_without) == len(schedule_default)
        for a, b in zip(schedule_without, schedule_default):
            assert a["status"] == b["status"]
            assert a["time"] == b["time"]

    def test_capped_at_min_hours(self, now):
        """Effective minimum should be capped at min_hours."""
        # now=14:30 — put cheap hour in the future (h18)
        # min_hours=1 (4 slots), min_consecutive=5 → effective = 1 hour (4 quarter-slots)
        prices = [slot for h in range(24) for slot in make_nordpool_hour(h, 0.50 if h != 18 else 0.01)]
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 5)]

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=1.0,  # 4 slots
            now=now,
            prev_activity_history=history,
            min_consecutive_hours=5,  # Requesting 5, but capped to 1
        )

        # Active count should not exceed much beyond min_hours
        # The block at hour 18 should be 4 quarter-slots (1 hour), not 80 (5 hours)
        blocks = _find_active_blocks(schedule)
        for start, length in blocks:
            # Each block should be at most slightly more than 4 quarter-slots
            # (rolling window might add some, but not 80)
            assert length <= 16, f"Block at {start} too long ({length}), min_consecutive should be capped"

    def test_already_long_blocks_untouched(self, now, today_prices):
        """Blocks already meeting the minimum should not be modified."""
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 25)]

        schedule_without = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=6.0,  # 24 slots — forms large contiguous blocks
            now=now,
            prev_activity_history=history,
            min_consecutive_hours=None,
        )
        schedule_with = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=6.0,
            now=now,
            prev_activity_history=history,
            min_consecutive_hours=2,  # Blocks already > 2 hours (8 quarter-slots)
        )

        # Check that blocks in both schedules match
        blocks_without = _find_active_blocks(schedule_without)
        blocks_with = _find_active_blocks(schedule_with)

        # If all blocks were already >= 8 quarter-slots (2 hours), no changes expected
        all_long = all(length >= 8 for _, length in blocks_without)
        if all_long:
            assert blocks_without == blocks_with

    def test_consolidation_prefers_cheapest_window(self, now):
        """Consolidation should prefer the cheapest consecutive window."""
        # now=14:30 — two cheap islands in the future at h17 and h21
        # h16=0.20 (cheap neighbor of h17), h18=0.80 (expensive neighbor of h17)
        prices = [slot for h, p in enumerate([
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.20, 0.01, 0.80, 0.50,  # h16=0.20, h17=cheapest, h18=0.80
            0.50, 0.01, 0.50, 0.50,         # h21 = also cheapest
        ]) for slot in make_nordpool_hour(h, p)]
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 9)]

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=2.0,  # 8 slots → h17(4) + h21(4)
            now=now,
            prev_activity_history=history,
            min_consecutive_hours=2,  # 8 quarter-slots per block
        )

        # The cheapest 2-hour window should be selected by consolidation
        # h16-h17 (0.20 + 0.01 = cheapest window) should be preferred
        hour16_slots = [
            s for s in schedule
            if datetime.fromisoformat(s["time"]).astimezone(TZ).hour == 16
        ]
        hour18_slots = [
            s for s in schedule
            if datetime.fromisoformat(s["time"]).astimezone(TZ).hour == 18
        ]
        assert all(s["status"] == "active" for s in hour16_slots), "Cheap neighbor h16 should be in the consolidated window"
        assert all(s["status"] == "standby" for s in hour18_slots), "Expensive h18 should not be activated"

    def test_scattered_slots_consolidated_not_inflated(self, now):
        """Scattered cheap slots should be consolidated into one block, not each extended.

        Regression test: with min_hours=1 and min_consecutive_hours=1, the old code
        would extend each of the 4 scattered cheapest slots into its own 1-hour block,
        resulting in ~3-4 hours instead of the expected 1 hour.
        """
        # now=14:30 — 4 cheap slots scattered in the future at hours 15, 17, 20, 23
        hourly_prices = [0.50] * 24
        hourly_prices[15] = 0.01
        hourly_prices[17] = 0.02
        hourly_prices[20] = 0.03
        hourly_prices[23] = 0.04
        prices = [slot for h, p in enumerate(hourly_prices) for slot in make_nordpool_hour(h, p)]
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 5)]

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=1.0,  # 4 slots
            now=now,
            rolling_window_hours=24.0,
            prev_activity_history=history,
            min_consecutive_hours=1.0,  # Each block must be >= 1 hour (4 slots)
        )

        # Check future blocks only
        future_blocks = [
            (start, length) for start, length in _find_active_blocks(schedule)
            if datetime.fromisoformat(schedule[start]["time"]).astimezone(TZ) >= now
        ]

        # All future blocks must meet the minimum consecutive requirement
        for start, length in future_blocks:
            assert length >= 4, f"Block at index {start} has length {length}, expected >= 4"

        # Total future active time should not be inflated
        future_active = [
            s for s in schedule
            if s["status"] == "active"
            and datetime.fromisoformat(s["time"]).astimezone(TZ) >= now
        ]
        assert len(future_active) <= 8, (
            f"Expected at most 8 future active slots (2h) but got {len(future_active)} "
            f"({len(future_active)/4}h). "
            "Scattered slots should be consolidated, not each extended independently."
        )

    def test_consecutive_preserves_long_blocks(self, now):
        """Long blocks that already meet the minimum should not be disrupted."""
        # now=14:30 — one cheap 2-hour block (h16-17) plus one scattered cheap slot (h22)
        hourly_prices = [0.50] * 24
        hourly_prices[16] = 0.01
        hourly_prices[17] = 0.01
        hourly_prices[22] = 0.02
        prices = [slot for h, p in enumerate(hourly_prices) for slot in make_nordpool_hour(h, p)]
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 13)]

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=3.0,  # 12 slots → h16(4) + h17(4) + h22(4)
            now=now,
            rolling_window_hours=24.0,
            prev_activity_history=history,
            min_consecutive_hours=2.0,  # 8 quarter-slots per block
        )

        # Future blocks should all meet minimum
        future_blocks = [
            (start, length) for start, length in _find_active_blocks(schedule)
            if datetime.fromisoformat(schedule[start]["time"]).astimezone(TZ) >= now
        ]
        # The h16-h17 block (8 slots) already meets minimum, should be preserved
        # The h22 block (4 slots) is short and should be consolidated
        for start, length in future_blocks:
            assert length >= 8, f"Block at index {start} has length {length}, expected >= 8"


    def test_block_straddling_window_boundary_not_lost(self, now):
        """A short block at the rolling window boundary should not be deactivated and lost.

        Regression: if a short active block starts inside the future window but
        extends past future_end_idx, it would be deactivated for consolidation
        but _find_consecutive_candidates only searches within the window, so the
        freed slots could never be re-placed — silently losing active hours.
        """
        # now=14:30, rolling_window=6h → window ends at 20:30
        # Put cheap slots at h15 (inside window) and h20 (straddles boundary)
        hourly_prices = [0.50] * 24
        hourly_prices[15] = 0.01  # inside window
        hourly_prices[20] = 0.02  # straddles: starts at 20:00, block ends 20:45 > 20:30
        prices = [slot for h, p in enumerate(hourly_prices) for slot in make_nordpool_hour(h, p)]
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 9)]

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=2.0,  # 8 slots → h15(4) + h20(4)
            now=now,
            rolling_window_hours=6.0,  # window: 14:30–20:30
            prev_activity_history=history,
            min_consecutive_hours=2,  # 8 quarter-slots — both blocks are "short"
        )

        # Count total future active slots — should not lose any
        future_active = [
            s for s in schedule
            if s["status"] == "active"
            and datetime.fromisoformat(s["time"]).astimezone(TZ) >= now
        ]
        # We requested 2 hours (8 slots); should get at least that many
        assert len(future_active) >= 8, (
            f"Expected at least 8 future active slots (2h) but got {len(future_active)}. "
            "A block straddling the window boundary may have been lost during consolidation."
        )


    def test_in_progress_block_not_fragmented_on_recalculation(self):
        """An in-progress consecutive block must not be split by recalculation.

        Regression test for GitHub issue: user configures min_hours=1,
        min_consecutive_hours=1, exclude 17:00-11:00. At 10:00, the scheduler
        produces a clean consecutive block. When recalculated at 11:30
        (mid-block), the block should be preserved, not fragmented.

        The root cause: _enforce_min_consecutive only operates on future slots.
        As slots become past, the future portion of the block becomes "short" and
        gets freed/reallocated elsewhere, fragmenting the in-progress block.
        """
        # Prices from the actual user report: the 4 cheapest non-excluded
        # slots are scattered (11:00=1.44, 11:15=1.56, 12:00=1.56, 13:15=1.57),
        # NOT consecutive. The consecutive enforcement must consolidate them.
        prices = [
            # h0-h10: excluded range (17:00-11:00), prices don't matter much
            *[make_nordpool_slot(h, 1.0 + h * 0.02, quarter=q)
              for h in range(11) for q in range(4)],
            # h11: 1.44, 1.56, 1.60, 1.60 (11:00 is cheapest in range)
            make_nordpool_slot(11, 1.44, quarter=0),
            make_nordpool_slot(11, 1.56, quarter=1),
            make_nordpool_slot(11, 1.60, quarter=2),
            make_nordpool_slot(11, 1.60, quarter=3),
            # h12: 1.56, 1.60, 1.59, 1.58 (12:00 is 2nd cheapest)
            make_nordpool_slot(12, 1.56, quarter=0),
            make_nordpool_slot(12, 1.60, quarter=1),
            make_nordpool_slot(12, 1.59, quarter=2),
            make_nordpool_slot(12, 1.58, quarter=3),
            # h13: 1.59, 1.57, 1.58, 1.59 (13:15 is 3rd cheapest)
            make_nordpool_slot(13, 1.59, quarter=0),
            make_nordpool_slot(13, 1.57, quarter=1),
            make_nordpool_slot(13, 1.58, quarter=2),
            make_nordpool_slot(13, 1.59, quarter=3),
            # h14-h16: moderate prices
            *[make_nordpool_slot(h, 1.60 + (h - 14) * 0.02, quarter=q)
              for h in range(14, 17) for q in range(4)],
            # h17-h23: excluded range again
            *[make_nordpool_slot(h, 1.70 + (h - 17) * 0.02, quarter=q)
              for h in range(17, 24) for q in range(4)],
        ]

        # --- Phase 1: Initial schedule at 10:00 ---
        now_10 = datetime(2026, 2, 6, 10, 0, 0, tzinfo=TZ)

        # Simulate activity from previous day (user has been running the
        # integration for days). This satisfies the rolling window lookback
        # so it won't add extra slots to compensate for "missing" past activity.
        prev_history = [
            (now_10 - timedelta(hours=20, minutes=i * 15)).isoformat()
            for i in range(4)  # 4 slots = 1 hour of activity yesterday
        ]

        schedule_10 = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=1.0,
            now=now_10,
            rolling_window_hours=24.0,
            prev_activity_history=prev_history,
            min_consecutive_hours=1.0,
            exclude_from="17:00:00",
            exclude_until="11:00:00",
        )

        # Verify: at 10:00, we get a nice consecutive block starting at 11:00
        future_blocks_10 = [
            (start, length) for start, length in _find_active_blocks(schedule_10)
            if datetime.fromisoformat(schedule_10[start]["time"]).astimezone(TZ) >= now_10
        ]
        assert len(future_blocks_10) >= 1, "Should have at least one future active block"
        # The block should be at least 4 slots (1 hour)
        assert future_blocks_10[0][1] >= 4, (
            f"Initial block should be >= 4 slots but is {future_blocks_10[0][1]}"
        )

        # Build activity history as the coordinator would
        history_after_phase1 = build_activity_history(
            schedule_10, prev_history, now_10, 24.0
        )

        # --- Phase 2: Recalculate at 11:30 (mid-block) ---
        now_1130 = datetime(2026, 2, 6, 11, 30, 0, tzinfo=TZ)

        # Update history: slots 11:00 and 11:15 have passed and were active
        history_at_1130 = build_activity_history(
            schedule_10, history_after_phase1, now_1130, 24.0
        )

        schedule_1130 = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=1.0,
            now=now_1130,
            rolling_window_hours=24.0,
            prev_activity_history=history_at_1130,
            min_consecutive_hours=1.0,
            exclude_from="17:00:00",
            exclude_until="11:00:00",
        )

        # The critical check: at 11:30, the current slot should be ACTIVE
        # (the in-progress block should continue)
        current_slot = find_current_slot(schedule_1130, now_1130)
        assert current_slot is not None, "Should find current slot at 11:30"
        assert current_slot["status"] == "active", (
            f"Current slot at 11:30 should be active (in-progress block) "
            f"but is '{current_slot['status']}'. The consecutive block was fragmented."
        )

        # Also verify: the block containing 11:00-11:45 should still be consecutive
        # (11:00 and 11:15 are past-active, 11:30 and 11:45 should be future-active)
        slot_1145 = next(
            (s for s in schedule_1130
             if "11:45" in s["time"] and "2026-02-06" in s["time"]),
            None,
        )
        assert slot_1145 is not None, "Should find 11:45 slot"
        assert slot_1145["status"] == "active", (
            f"Slot at 11:45 should be active to maintain consecutive block "
            f"but is '{slot_1145['status']}'"
        )

        # --- Phase 3: Recalculate at 11:45 (last slot of block) ---
        # This is the critical regression scenario: at 11:45, the 11:30 slot is
        # now in the past and shows as "standby" in the base selection (because the
        # cheapest-4 slots are 11:00, 11:15, 12:00, 13:15). Without the history-aware
        # trailing detection and in-progress block protection, trailing_past_active=0
        # and the block is freed, turning the heater off at 11:45.
        now_1145 = datetime(2026, 2, 6, 11, 45, 0, tzinfo=TZ)

        history_at_1145 = build_activity_history(
            schedule_1130, history_at_1130, now_1145, 24.0
        )

        schedule_1145 = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=1.0,
            now=now_1145,
            rolling_window_hours=24.0,
            prev_activity_history=history_at_1145,
            min_consecutive_hours=1.0,
            exclude_from="17:00:00",
            exclude_until="11:00:00",
        )

        # The critical check: at 11:45, the current slot should be ACTIVE
        current_slot_1145 = find_current_slot(schedule_1145, now_1145)
        assert current_slot_1145 is not None, "Should find current slot at 11:45"
        assert current_slot_1145["status"] == "active", (
            f"Current slot at 11:45 should be active (final slot of in-progress block) "
            f"but is '{current_slot_1145['status']}'. "
            f"The consecutive block was fragmented at the last slot."
        )

    def test_in_progress_block_survives_midnight_day_rollover(self):
        """In-progress block must not be broken at midnight when the day rolls over.

        Regression test: at 00:00 the scheduler switches to the new day's raw_today
        data (which starts at 00:00). The schedule therefore has no past slots, so
        future_start_idx == 0 and the trailing loop exits immediately with
        trailing_past_active == 0. Without Fix C, no protection fires and the
        in-progress block (started at 23:30/23:45 the previous evening) is lost.

        Fix C extends the trailing detection to scan prev_activity_history for
        consecutive active slots immediately before the schedule start, bridging
        the day boundary.
        """
        # Build a Feb 7 price set where the 4 cheapest slots are in the
        # afternoon (13:00-13:45), NOT at midnight, so the base selection
        # never activates 00:00-00:45. The protection must supply those slots.
        today_feb7 = [
            # Midnight through morning: moderate prices — not cheapest
            *[make_nordpool_slot(h, 0.85 + h * 0.01, day_offset=1, quarter=q)
              for h in range(12) for q in range(4)],
            # 13:00-13:45: cheapest 4 slots
            make_nordpool_slot(13, 0.60, day_offset=1, quarter=0),
            make_nordpool_slot(13, 0.61, day_offset=1, quarter=1),
            make_nordpool_slot(13, 0.62, day_offset=1, quarter=2),
            make_nordpool_slot(13, 0.63, day_offset=1, quarter=3),
            # Rest of day: moderate/expensive
            *[make_nordpool_slot(h, 0.80 + h * 0.01, day_offset=1, quarter=q)
              for h in range(14, 24) for q in range(4)],
        ]

        # History: the heater was active at 23:30 and 23:45 on Feb 6.
        # This simulates an in-progress 1-hour block that started at 23:15
        # and should run through 00:15 on Feb 7.
        feb6_2330 = datetime(2026, 2, 6, 23, 30, 0, tzinfo=TZ).isoformat()
        feb6_2345 = datetime(2026, 2, 6, 23, 45, 0, tzinfo=TZ).isoformat()
        history_at_midnight = [feb6_2330, feb6_2345]

        now_midnight = datetime(2026, 2, 7, 0, 0, 0, tzinfo=TZ)

        schedule_midnight = build_schedule(
            raw_today=today_feb7,
            raw_tomorrow=[],
            min_hours=1.0,
            now=now_midnight,
            rolling_window_hours=24.0,
            prev_activity_history=history_at_midnight,
            min_consecutive_hours=1.0,
        )

        # The current slot (00:00 Feb 7) must remain active — it's part of the
        # in-progress block that started at 23:30 on Feb 6.
        current_slot = find_current_slot(schedule_midnight, now_midnight)
        assert current_slot is not None, "Should find current slot at midnight"
        assert current_slot["status"] == "active", (
            f"Slot at 00:00 should be active (continuing in-progress block from "
            f"previous day) but is '{current_slot['status']}'. "
            f"The midnight day-rollover broke the consecutive block."
        )

    def test_consolidation_when_freed_less_than_effective_slots(self):
        """Isolated short blocks must consolidate even when freed < effective_slots.

        Regression test for a budget-check bug in the consecutive enforcement
        consolidation loop:

        With min_hours=1h (4 slots) and min_consecutive_hours=1h (effective_slots=4),
        the base selection can pick 4 isolated 1-slot cheap blocks scattered across the
        day (e.g. 3:00, 7:00, 15:00, 20:00).  By mid-day (now=12:00):
          - 3:00 and 7:00 are in the past — trailing_past_active=0 (heater is not
            currently running so no in-progress protection applies)
          - 15:00 and 20:00 are two isolated future 1-slot blocks
          - Both get freed: freed=2

        The consolidation loop then looks for a 4-slot consecutive window.  Every
        candidate window is all-standby, so new_needed=4.  The old budget check
        ``if new_needed > freed: continue`` skips ALL candidates (4 > 2), leaving
        the 2 freed slots permanently deactivated — the heater ends up with
        0 future active slots and never runs for the rest of the day.

        The fix removes that budget check so the cheapest 4-slot window (13:00-13:45)
        is activated regardless of freed, and ``freed`` simply goes negative to stop
        further windows from being activated.

        Setup:
          - Prices: 4 isolated cheap slots at 3:00, 7:00, 15:00, 20:00 (quarter=0,
            price=0.55).  All other slots at 1.0+.
          - Cheap consecutive block at 13:00-13:45 (price=0.70) — cheaper than
            the scattered slots' surrounding hours but more expensive than 0.55, so
            the base selection picks the scattered slots, not this block.
          - History: heater ran 1:00-1:45 (4 slots) → past_active_count=6, which
            prevents the rolling window's "critical activation" path from firing and
            adding extra future slots that would mask the bug.
        """
        prices = [
            make_nordpool_slot(h, 1.0 + h * 0.01, quarter=q)
            for h in range(24) for q in range(4)
        ]
        # 4 isolated cheap scattered slots — these become the base-selected slots
        for h in [3, 7, 15, 20]:
            prices[h * 4] = make_nordpool_slot(h, 0.55, quarter=0)
        # Cheap consecutive block at 13:00-13:45 — the consolidation target
        for q in range(4):
            prices[13 * 4 + q] = make_nordpool_slot(13, 0.70, quarter=q)

        # History: heater ran 1:00-1:45 today, providing past_active_count=6
        # (2 from past base slots 3:00, 7:00 + 4 from history = 6 >= min_slots=4).
        # This keeps the rolling window in "sufficient" mode, so it does NOT
        # add extra future slots that would push freed up to effective_slots=4.
        history = [
            datetime(2026, 2, 6, 1,  0, tzinfo=TZ).isoformat(),
            datetime(2026, 2, 6, 1, 15, tzinfo=TZ).isoformat(),
            datetime(2026, 2, 6, 1, 30, tzinfo=TZ).isoformat(),
            datetime(2026, 2, 6, 1, 45, tzinfo=TZ).isoformat(),
        ]

        now = datetime(2026, 2, 6, 12, 0, 0, tzinfo=TZ)
        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=1.0,
            now=now,
            rolling_window_hours=24.0,
            prev_activity_history=history,
            min_consecutive_hours=1.0,
        )

        future_active = [
            s for s in schedule
            if s.get("status") == "active"
            and datetime.fromisoformat(s["time"]).astimezone(TZ) >= now
        ]
        assert len(future_active) >= 4, (
            f"Expected >=4 future active slots after consolidation but got "
            f"{len(future_active)}: {[s['time'] for s in future_active]}. "
            f"The 2 freed slots were not placed because new_needed (4) > freed (2)."
        )

        # The future active slots must form at least one 4-slot consecutive block
        active_times = sorted(
            datetime.fromisoformat(s["time"]).astimezone(TZ) for s in future_active
        )
        has_consecutive_block = any(
            active_times[i + 3] - active_times[i] == timedelta(minutes=45)
            for i in range(len(active_times) - 3)
        )
        assert has_consecutive_block, (
            f"Expected at least one consecutive 4-slot block in future active slots, "
            f"got: {[t.strftime('%H:%M') for t in active_times]}"
        )

        # Specifically: the cheapest future block (13:00-13:45) should be activated
        future_times = {t.strftime("%H:%M") for t in active_times}
        assert {"13:00", "13:15", "13:30", "13:45"}.issubset(future_times), (
            f"Expected 13:00-13:45 to be the consolidation target, "
            f"got: {sorted(future_times)}"
        )

        # Exactly 1 consecutive block should be activated — NOT 2.
        # When freed=2 and effective_slots=4, the budget bypass applies only to the
        # FIRST window. After that window is placed (slots_activated > 0), the budget
        # check kicks back in: new_needed=4 > freed=-2, so subsequent windows are
        # skipped. This prevents the over-activation regression where removing the
        # check entirely caused 2 windows (8 slots) to fire when freed < effective_slots.
        assert len(future_active) == 4, (
            f"Expected exactly 4 future active slots (1 consecutive block), "
            f"got {len(future_active)}: {[t.strftime('%H:%M') for t in active_times]}. "
            f"Over-activation: budget check not applied after first window."
        )

    def test_consolidation_does_not_over_activate_when_freed_geq_effective_slots(self):
        """When freed >= effective_slots the budget check must still cap at 1 window.

        Regression guard for the over-activation introduced when the budget check
        was removed entirely: with freed=6 and effective_slots=4, removing the check
        caused 2 consecutive windows (8 slots) to be activated instead of 1 (4 slots).

        The fix allows bypassing the check only for the first window (slots_activated==0).
        After the first window fires, new_needed=4 > freed=2 causes subsequent windows
        to be skipped.

        Setup mirrors the real-world log scenario:
          - Base: 4 cheap scattered slots (3 past, 1 future)
          - Rolling window activates 5 extra future slots → 6 future active total
          - Consecutive enforcement frees all 6 from 3 short blocks (freed=6)
          - Should consolidate into exactly 1 block of 4, not 2 blocks of 4
        """
        prices = [
            make_nordpool_slot(h, 1.0 + h * 0.01, quarter=q)
            for h in range(24) for q in range(4)
        ]
        # Base cheapest 4: scattered isolated slots (hours 1, 5, 9, 22 quarter=0)
        for h in [1, 5, 9, 22]:
            prices[h * 4] = make_nordpool_slot(h, 0.50, quarter=0)
        # Cheap consecutive target at 13:00-13:45
        for q in range(4):
            prices[13 * 4 + q] = make_nordpool_slot(13, 0.60, quarter=q)
        # Second cheap consecutive block at 16:00-16:45 (slightly more expensive)
        for q in range(4):
            prices[16 * 4 + q] = make_nordpool_slot(16, 0.65, quarter=q)

        # No history — rolling window critical activation will add extra future slots
        # to cover the constraint, creating freed=6 scattered short blocks.
        now = datetime(2026, 2, 6, 10, 0, 0, tzinfo=TZ)
        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=1.0,
            now=now,
            rolling_window_hours=24.0,
            prev_activity_history=[],
            min_consecutive_hours=1.0,
        )

        future_active = [
            s for s in schedule
            if s.get("status") == "active"
            and datetime.fromisoformat(s["time"]).astimezone(TZ) >= now
        ]
        active_times = sorted(
            datetime.fromisoformat(s["time"]).astimezone(TZ) for s in future_active
        )

        # Must have at least one consecutive 4-slot block
        has_consecutive_block = any(
            active_times[i + 3] - active_times[i] == timedelta(minutes=45)
            for i in range(len(active_times) - 3)
        )
        assert has_consecutive_block, (
            f"Expected a consecutive 4-slot block, "
            f"got: {[t.strftime('%H:%M') for t in active_times]}"
        )

        # Total active hours must stay close to min_hours (1h = 4 slots).
        # Allow some overshoot from rolling window activations, but NOT the
        # 2× overshoot (8 future slots = 2h) caused by the removed budget check.
        assert len(future_active) <= 8, (
            f"Over-activation: expected <=8 future active slots, "
            f"got {len(future_active)}: {[t.strftime('%H:%M') for t in active_times]}. "
            f"The budget check was not applied after the first window."
        )


class TestMostExpensiveMode:
    """Tests for the 'most_expensive' selection mode (inverted scheduling)."""

    def test_most_expensive_slots_activated(self, now, today_prices):
        """The most expensive N slots should be activated in inverted mode."""
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 11)]
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,  # 10 slots
            now=now,
            prev_activity_history=history,
            selection_mode="most_expensive",
        )

        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) == 10

        # All active prices should be >= all standby prices
        active_prices = sorted(s["price"] for s in active)
        standby_prices = sorted(
            s["price"] for s in schedule if s["status"] == "standby"
        )
        assert active_prices[0] >= standby_prices[-1]

    def test_inverted_always_expensive_acts_as_always_activate(self, now, today_prices):
        """In inverted mode, always_expensive means 'always activate above this price'."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=0.25,  # Only 1 slot quota
            now=now,
            always_expensive=0.50,
            selection_mode="most_expensive",
        )

        active = [s for s in schedule if s["status"] == "active"]
        # All slots with price >= 0.50 should be active
        expensive_slots = [s for s in schedule if s["price"] >= 0.50]
        for slot in expensive_slots:
            assert slot["status"] == "active"
        # Should have more than 1 because always_expensive forces activation
        assert len(active) > 1

    def test_inverted_always_cheap_acts_as_never_activate(self, now, today_prices):
        """In inverted mode, always_cheap means 'never activate below this price'."""
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 25)]
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=6.0,  # Would normally activate many
            now=now,
            always_cheap=0.15,
            prev_activity_history=history,
            selection_mode="most_expensive",
        )

        # No slot at or below 0.15 should be active
        cheap_active = [
            s for s in schedule
            if s["status"] == "active" and s["price"] <= 0.15
        ]
        assert len(cheap_active) == 0

    def test_inverted_similarity_threshold(self, now):
        """Price similarity threshold should expand from most expensive price downward."""
        # Prices clustered: 0.50, 0.49, 0.48, 0.47, repeating (4 quarter-slots per hour)
        prices = [slot for h in range(24) for slot in make_nordpool_hour(h, 0.50 - (h % 4) * 0.01)]
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 19)]
        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=2.5,  # 10 slots
            now=now,
            prev_activity_history=history,
            price_similarity_pct=4.0,  # 4% of 0.50 = 0.02, threshold at 0.48
            selection_mode="most_expensive",
        )

        active = [s for s in schedule if s["status"] == "active"]
        # Hours with price >= 0.48: 0.50, 0.49, 0.48 = 18 hours × 4 slots = 72
        assert len(active) == 72
        # 0.47 slots should be standby (below threshold)
        for s in schedule:
            if s["price"] == 0.47:
                assert s["status"] == "standby"
        # All active slots should have price >= 0.48
        for s in active:
            assert s["price"] >= 0.48

    def test_inverted_consecutive_extends_with_most_expensive(self, now):
        """In inverted mode, consecutive consolidation should prefer more expensive windows."""
        # now=14:30 — put expensive islands in the future
        # h17=0.99 (most expensive), h21=0.99 (second expensive island)
        # h16=0.80 (expensive neighbor of h17), h18=0.20 (cheap neighbor of h17)
        prices = [slot for h, p in enumerate([
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.80, 0.99, 0.20, 0.50,  # h16=0.80, h17=most expensive, h18=0.20
            0.50, 0.99, 0.50, 0.50,         # h21 = also most expensive
        ]) for slot in make_nordpool_hour(h, p)]
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 9)]

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=2.0,  # 8 slots → h17(4) + h21(4)
            now=now,
            prev_activity_history=history,
            min_consecutive_hours=2,  # 8 quarter-slots per block
            selection_mode="most_expensive",
        )

        # Consolidation should prefer the most expensive window (h16-h17)
        hour16_slots = [
            s for s in schedule
            if datetime.fromisoformat(s["time"]).astimezone(TZ).hour == 16
        ]
        hour18_slots = [
            s for s in schedule
            if datetime.fromisoformat(s["time"]).astimezone(TZ).hour == 18
        ]
        assert all(s["status"] == "active" for s in hour16_slots), "Should consolidate toward more expensive neighbor"
        assert all(s["status"] == "standby" for s in hour18_slots), "Cheap hour 18 should not be activated"

    def test_default_mode_is_cheapest(self, now, today_prices):
        """Without explicit selection_mode, behavior should match 'cheapest'."""
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 11)]
        schedule_default = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            prev_activity_history=history,
        )
        schedule_explicit = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            prev_activity_history=history,
            selection_mode="cheapest",
        )

        for a, b in zip(schedule_default, schedule_explicit, strict=True):
            assert a["status"] == b["status"]
            assert a["time"] == b["time"]


class TestIsExcluded:
    """Tests for the _is_excluded helper function."""

    def test_none_params_returns_false(self):
        """Feature is disabled when either param is None."""
        dt = datetime(2026, 2, 6, 3, 0, 0, tzinfo=TZ)
        assert _is_excluded(dt, None, None) is False
        assert _is_excluded(dt, "00:00:00", None) is False
        assert _is_excluded(dt, None, "06:00:00") is False

    def test_normal_range_inside(self):
        """Slot within a normal (non-crossing) range is excluded."""
        dt = datetime(2026, 2, 6, 3, 0, 0, tzinfo=TZ)
        assert _is_excluded(dt, "00:00:00", "06:00:00") is True

    def test_normal_range_outside(self):
        """Slot outside a normal range is not excluded."""
        dt = datetime(2026, 2, 6, 10, 0, 0, tzinfo=TZ)
        assert _is_excluded(dt, "00:00:00", "06:00:00") is False

    def test_normal_range_boundary_start_inclusive(self):
        """Slot at the start boundary is excluded (inclusive)."""
        dt = datetime(2026, 2, 6, 0, 0, 0, tzinfo=TZ)
        assert _is_excluded(dt, "00:00:00", "06:00:00") is True

    def test_normal_range_boundary_end_exclusive(self):
        """Slot at the end boundary is not excluded (exclusive)."""
        dt = datetime(2026, 2, 6, 6, 0, 0, tzinfo=TZ)
        assert _is_excluded(dt, "00:00:00", "06:00:00") is False

    def test_cross_midnight_inside_before(self):
        """Slot before midnight in a cross-midnight range is excluded."""
        dt = datetime(2026, 2, 6, 23, 0, 0, tzinfo=TZ)
        assert _is_excluded(dt, "22:00:00", "06:00:00") is True

    def test_cross_midnight_inside_after(self):
        """Slot after midnight in a cross-midnight range is excluded."""
        dt = datetime(2026, 2, 6, 3, 0, 0, tzinfo=TZ)
        assert _is_excluded(dt, "22:00:00", "06:00:00") is True

    def test_cross_midnight_outside(self):
        """Slot outside a cross-midnight range is not excluded."""
        dt = datetime(2026, 2, 6, 12, 0, 0, tzinfo=TZ)
        assert _is_excluded(dt, "22:00:00", "06:00:00") is False

    def test_equal_start_end_excludes_nothing(self):
        """Zero-length range excludes nothing."""
        dt = datetime(2026, 2, 6, 3, 0, 0, tzinfo=TZ)
        assert _is_excluded(dt, "06:00:00", "06:00:00") is False

    def test_hhmm_format(self):
        """Accepts HH:MM format without seconds."""
        dt = datetime(2026, 2, 6, 3, 0, 0, tzinfo=TZ)
        assert _is_excluded(dt, "00:00", "06:00") is True


class TestExcludedHours:
    """Tests for the excluded hours feature in build_schedule."""

    def test_basic_exclusion(self, now, today_prices):
        """Slots in excluded range get 'excluded' status."""
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 11)]
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            prev_activity_history=history,
            exclude_from="00:00:00",
            exclude_until="06:00:00",
        )

        # Hours 0-5 should be excluded
        for s in schedule:
            slot_hour = datetime.fromisoformat(s["time"]).astimezone(TZ).hour
            if slot_hour < 6:
                assert s["status"] == "excluded", f"Hour {slot_hour} should be excluded"

    def test_excluded_slots_dont_consume_quota(self, now, today_prices):
        """Excluded slots don't reduce the activation quota."""
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 11)]
        # Without exclusion
        schedule_no_excl = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            prev_activity_history=history,
        )
        # With exclusion of hours 0-5 (which happen to be the cheapest)
        schedule_with_excl = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            prev_activity_history=history,
            exclude_from="00:00:00",
            exclude_until="06:00:00",
        )

        active_no_excl = [s for s in schedule_no_excl if s["status"] == "active"]
        active_with_excl = [s for s in schedule_with_excl if s["status"] == "active"]
        excluded = [s for s in schedule_with_excl if s["status"] == "excluded"]

        # Baseline without exclusion should have active slots
        assert len(active_no_excl) >= 10  # 2.5 hours * 4 slots
        # Should still have active slots (from non-excluded hours)
        assert len(active_with_excl) > 0
        assert len(excluded) == 24  # Hours 0-5 × 4 quarter-slots
        # Total non-excluded active slots should still meet min_hours quota
        assert len(active_with_excl) >= 10  # 2.5 hours * 4 slots

    def test_exclusion_overrides_always_cheap(self, now, today_prices):
        """Excluded slots stay excluded even if price is below always_cheap."""
        # Hours 0-5 have the cheapest prices (0.03-0.10)
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            always_cheap=0.10,
            exclude_from="00:00:00",
            exclude_until="06:00:00",
        )

        for s in schedule:
            slot_hour = datetime.fromisoformat(s["time"]).astimezone(TZ).hour
            if slot_hour < 6:
                assert s["status"] == "excluded", (
                    f"Hour {slot_hour} at price {s['price']} should be excluded "
                    f"even though price <= always_cheap"
                )

    def test_cross_midnight_exclusion(self, now, today_prices, tomorrow_prices):
        """Cross-midnight range (e.g., 22:00-06:00) works across both days."""
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 11)]
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=tomorrow_prices,
            min_hours=2.5,
            now=now,
            prev_activity_history=history,
            exclude_from="22:00:00",
            exclude_until="06:00:00",
        )

        for s in schedule:
            slot_hour = datetime.fromisoformat(s["time"]).astimezone(TZ).hour
            if slot_hour >= 22 or slot_hour < 6:
                assert s["status"] == "excluded", f"Hour {slot_hour} should be excluded"

    def test_disabled_when_both_none(self, now, today_prices):
        """Feature has no effect when both params are None."""
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 11)]
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            prev_activity_history=history,
            exclude_from=None,
            exclude_until=None,
        )

        excluded = [s for s in schedule if s["status"] == "excluded"]
        assert len(excluded) == 0

    def test_rolling_window_does_not_activate_excluded(self, now, today_prices):
        """Rolling window constraint does not activate excluded slots."""
        # Use a small rolling window that would normally need more activations
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=4,
            now=now,
            rolling_window_hours=8,
            exclude_from="00:00:00",
            exclude_until="06:00:00",
        )

        for s in schedule:
            slot_hour = datetime.fromisoformat(s["time"]).astimezone(TZ).hour
            if slot_hour < 6:
                assert s["status"] == "excluded", (
                    f"Hour {slot_hour} should remain excluded despite rolling window"
                )

    def test_consecutive_hours_does_not_bridge_excluded(self, now, today_prices):
        """Min consecutive hours does not extend through excluded slots."""
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 11)]
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            prev_activity_history=history,
            min_consecutive_hours=2.0,
            exclude_from="00:00:00",
            exclude_until="06:00:00",
        )

        for s in schedule:
            slot_hour = datetime.fromisoformat(s["time"]).astimezone(TZ).hour
            if slot_hour < 6:
                assert s["status"] == "excluded", (
                    f"Hour {slot_hour} should remain excluded despite consecutive constraint"
                )

    def test_all_hours_excluded(self, now, today_prices):
        """When all hours are excluded, everything is excluded and nothing activates."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            exclude_from="00:00:00",
            exclude_until="00:00:01",
        )
        # This is nearly a 24h exclusion (00:00:00 to 00:00:01 next day)
        # Actually exclude_from < exclude_until, so only the first second is excluded
        # Let's test with a cross-midnight range that covers everything
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            exclude_from="00:00:00",
            exclude_until="23:59:59",
        )

        excluded = [s for s in schedule if s["status"] == "excluded"]
        active = [s for s in schedule if s["status"] == "active"]
        assert len(excluded) == 96  # All 24 hours × 4 quarter-slots
        assert len(active) == 0

    def test_inverted_mode_with_exclusion(self, now, today_prices):
        """Excluded hours work the same in most_expensive mode."""
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 11)]
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            prev_activity_history=history,
            selection_mode="most_expensive",
            exclude_from="18:00:00",
            exclude_until="22:00:00",
        )

        for s in schedule:
            slot_hour = datetime.fromisoformat(s["time"]).astimezone(TZ).hour
            if 18 <= slot_hour < 22:
                assert s["status"] == "excluded", (
                    f"Hour {slot_hour} should be excluded in inverted mode"
                )

        # Non-excluded slots should still have some active ones
        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) > 0
