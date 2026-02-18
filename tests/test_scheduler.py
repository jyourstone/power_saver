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
        prices = [slot for h, p in enumerate([
            0.50, 0.10, 0.50, 0.50, 0.50,  # hour 1 cheap, isolated
            0.50, 0.50, 0.10, 0.50, 0.50,  # hour 7 cheap, isolated
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50,
        ]) for slot in make_nordpool_hour(h, p)]
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 9)]

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=2.0,  # 8 slots → activates hours 1(4) and 7(4) (cheapest)
            now=now,
            prev_activity_history=history,
            min_consecutive_hours=2,  # Each block must be >= 2 hours (8 quarter-slots)
        )

        # Find the active blocks
        blocks = _find_active_blocks(schedule)
        # All blocks should be at least 8 quarter-slots (2 hours)
        for start, length in blocks:
            assert length >= 8, f"Block at index {start} has length {length}, expected >= 8"

    def test_gap_filling_merges_blocks(self, now):
        """Two nearby blocks with a small gap should merge when gap is filled."""
        # Prices: cheap at hours 2-3 and 5-6, expensive at hour 4
        # but not ALWAYS_EXPENSIVE, so gap can be filled
        prices = [slot for h, p in enumerate([
            0.50, 0.50, 0.01, 0.01, 0.30,  # hours 2-3 cheap, hour 4 moderate
            0.01, 0.01, 0.50, 0.50, 0.50,  # hours 5-6 cheap
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50,
        ]) for slot in make_nordpool_hour(h, p)]
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 17)]

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=3.0,  # 12 slots → activates hours 2(4), 3(4), 5(4) (cheapest)
            now=now,
            prev_activity_history=history,
            min_consecutive_hours=3,  # Need blocks of at least 3 hours (12 quarter-slots)
        )

        blocks = _find_active_blocks(schedule)
        # The gap at hour 4 should be filled, creating one merged block
        for start, length in blocks:
            assert length >= 12, f"Block at index {start} has length {length}, expected >= 12"

    def test_always_expensive_blocks_extension(self, now):
        """Slots at or above always_expensive should never be activated for extension."""
        # Two isolated cheap hours with an expensive hour between them
        prices = [slot for h, p in enumerate([
            0.50, 0.01, 5.00, 0.01, 0.50,  # hour 2 = very expensive
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50,
        ]) for slot in make_nordpool_hour(h, p)]
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 9)]

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=0.5,  # 2 slots → hours 1 and 3
            now=now,
            always_expensive=4.00,
            prev_activity_history=history,
            min_consecutive_hours=3,  # Want 3 consecutive, but blocked by expensive
        )

        # The expensive slot (hour 2, price 5.00) must stay standby
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
        # min_hours=1 (4 slots), min_consecutive=5 → effective = 1 hour (4 quarter-slots)
        prices = [slot for h in range(24) for slot in make_nordpool_hour(h, 0.50 if h != 10 else 0.01)]
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
        # The block at hour 10 should be 4 quarter-slots (1 hour), not 80 (5 hours)
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

    def test_extends_in_cheapest_direction(self, now):
        """Extension should prefer the cheaper adjacent slot."""
        # h5=0.01 (cheapest), h20=0.01 (second cheap island far away)
        # h4=0.20 (cheap neighbor of h5), h6=0.80 (expensive neighbor of h5)
        prices = [slot for h, p in enumerate([
            0.50, 0.50, 0.50, 0.50, 0.20,  # hour 4 = 0.20
            0.01,                              # hour 5 = cheapest
            0.80, 0.50, 0.50, 0.50, 0.50,   # hour 6 = 0.80
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50, 0.01,   # hour 20 = also cheapest
            0.50, 0.50, 0.50,
        ]) for slot in make_nordpool_hour(h, p)]
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 9)]

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=2.0,  # 8 slots → h5(4) + h20(4)
            now=now,
            prev_activity_history=history,
            min_consecutive_hours=2,  # 8 quarter-slots per block
        )

        # h5 block (4 slots) extends toward h4 (0.20), not h6 (0.80)
        hour4_slots = [
            s for s in schedule
            if datetime.fromisoformat(s["time"]).astimezone(TZ).hour == 4
        ]
        hour6_slots = [
            s for s in schedule
            if datetime.fromisoformat(s["time"]).astimezone(TZ).hour == 6
        ]
        assert all(s["status"] == "active" for s in hour4_slots), "Should extend toward cheaper neighbor (hour 4)"
        assert all(s["status"] == "standby" for s in hour6_slots), "Expensive hour 6 should not be activated"


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
        """In inverted mode, consecutive extension should prefer more expensive adjacent slots."""
        # h5=0.99 (most expensive), h20=0.99 (second expensive island far away)
        # h4=0.80 (expensive neighbor of h5), h6=0.20 (cheap neighbor of h5)
        prices = [slot for h, p in enumerate([
            0.50, 0.50, 0.50, 0.50, 0.80,  # hour 4 = 0.80 (expensive neighbor)
            0.99,                              # hour 5 = most expensive
            0.20, 0.50, 0.50, 0.50, 0.50,   # hour 6 = 0.20 (cheap neighbor)
            0.50, 0.50, 0.50, 0.50, 0.50,
            0.50, 0.50, 0.50, 0.50, 0.99,   # hour 20 = also most expensive
            0.50, 0.50, 0.50,
        ]) for slot in make_nordpool_hour(h, p)]
        history = [(now - timedelta(minutes=i * 15)).isoformat() for i in range(1, 9)]

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=2.0,  # 8 slots → h5(4) + h20(4)
            now=now,
            prev_activity_history=history,
            min_consecutive_hours=2,  # 8 quarter-slots per block
            selection_mode="most_expensive",
        )

        # h5 block (4 slots) extends toward h4 (0.80), not h6 (0.20)
        hour4_slots = [
            s for s in schedule
            if datetime.fromisoformat(s["time"]).astimezone(TZ).hour == 4
        ]
        hour6_slots = [
            s for s in schedule
            if datetime.fromisoformat(s["time"]).astimezone(TZ).hour == 6
        ]
        assert all(s["status"] == "active" for s in hour4_slots), "Should extend toward more expensive neighbor"
        assert all(s["status"] == "standby" for s in hour6_slots), "Cheap hour 6 should not be activated"

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
