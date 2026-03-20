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
build_lowest_price_schedule = scheduler.build_lowest_price_schedule
build_minimum_runtime_schedule = scheduler.build_minimum_runtime_schedule
_partition_into_periods = scheduler._partition_into_periods
_build_base_schedule = scheduler._build_base_schedule
_activate_cheapest_in_group = scheduler._activate_cheapest_in_group
_find_active_blocks = scheduler._find_active_blocks
_is_excluded = scheduler._is_excluded

from helpers import TZ, make_nordpool_hour, make_nordpool_slot


class TestBuildSchedule:
    """Tests for the build_schedule function."""

    def test_basic_cheapest_slots_activated(self, now, today_prices):
        """The cheapest N slots should be activated."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,  # 10 slots
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
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=6.0,  # 24 slots — would normally activate many
            now=now,
            always_expensive=0.30,
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
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            price_similarity_pct=None,
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

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=2.0,  # 8 slots → activates hours 16(4) and 20(4) (cheapest)
            now=now,
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

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=3.0,  # 12 slots → activates h16(4), h17(4), h19(4) (cheapest)
            now=now,
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

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=0.5,  # 2 slots → h16 and h18
            now=now,
            always_expensive=4.00,
            min_consecutive_hours=3,  # Want 3 consecutive, but blocked by expensive
        )

        # The expensive slot (hour 17, price 5.00) must stay standby
        for s in schedule:
            if s["price"] >= 4.00:
                assert s["status"] == "standby", f"Expensive slot at {s['time']} should be standby"

    def test_disabled_when_none(self, now, today_prices):
        """When min_consecutive_hours is None, no changes should be made."""
        schedule_without = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            min_consecutive_hours=None,
        )
        schedule_default = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
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

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=1.0,  # 4 slots
            now=now,
            min_consecutive_hours=5,  # Requesting 5, but capped to 1
        )

        # Active count should not exceed much beyond min_hours
        # The block at hour 18 should be 4 quarter-slots (1 hour), not 80 (5 hours)
        blocks = _find_active_blocks(schedule)
        for start, length in blocks:
            # Each block should be at most slightly more than 4 quarter-slots
            assert length <= 16, f"Block at {start} too long ({length}), min_consecutive should be capped"

    def test_already_long_blocks_untouched(self, now, today_prices):
        """Blocks already meeting the minimum should not be modified."""
        schedule_without = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=6.0,  # 24 slots — forms large contiguous blocks
            now=now,
            min_consecutive_hours=None,
        )
        schedule_with = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=6.0,
            now=now,
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

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=2.0,  # 8 slots → h17(4) + h21(4)
            now=now,
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

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=1.0,  # 4 slots
            now=now,
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

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=3.0,  # 12 slots → h16(4) + h17(4) + h22(4)
            now=now,
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

    def test_consolidation_when_freed_less_than_effective_slots(self):
        """Isolated short blocks must consolidate even when freed < effective_slots.

        Regression test for a budget-check bug in the consecutive enforcement
        consolidation loop.
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

        now = datetime(2026, 2, 6, 12, 0, 0, tzinfo=TZ)
        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=1.0,
            now=now,
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
            f"The freed slots were not placed because new_needed > freed."
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


class TestMostExpensiveMode:
    """Tests for the 'most_expensive' selection mode (inverted scheduling)."""

    def test_most_expensive_slots_activated(self, now, today_prices):
        """The most expensive N slots should be activated in inverted mode."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,  # 10 slots
            now=now,
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
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=6.0,  # Would normally activate many
            now=now,
            always_cheap=0.15,
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
        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=2.5,  # 10 slots
            now=now,
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

        schedule = build_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=2.0,  # 8 slots → h17(4) + h21(4)
            now=now,
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
        schedule_default = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
        )
        schedule_explicit = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
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
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
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
        # Without exclusion
        schedule_no_excl = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
        )
        # With exclusion of hours 0-5 (which happen to be the cheapest)
        schedule_with_excl = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
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
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=tomorrow_prices,
            min_hours=2.5,
            now=now,
            exclude_from="22:00:00",
            exclude_until="06:00:00",
        )

        for s in schedule:
            slot_hour = datetime.fromisoformat(s["time"]).astimezone(TZ).hour
            if slot_hour >= 22 or slot_hour < 6:
                assert s["status"] == "excluded", f"Hour {slot_hour} should be excluded"

    def test_disabled_when_both_none(self, now, today_prices):
        """Feature has no effect when both params are None."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            exclude_from=None,
            exclude_until=None,
        )

        excluded = [s for s in schedule if s["status"] == "excluded"]
        assert len(excluded) == 0

    def test_consecutive_hours_does_not_bridge_excluded(self, now, today_prices):
        """Min consecutive hours does not extend through excluded slots."""
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
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
        schedule = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
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


# ---------------------------------------------------------------------------
# New test classes for v3.0.0 refactoring
# ---------------------------------------------------------------------------


class TestPartitionIntoPeriods:
    """Tests for the _partition_into_periods function."""

    def test_full_day_period(self, now, today_prices):
        """When period_from == period_to (00:00 -> 00:00), every slot belongs to one period per day."""
        schedule = _build_base_schedule(today_prices, now, None, None)
        periods = _partition_into_periods(schedule, "00:00", "00:00", now)

        # Full day: period_from == period_to means cross_midnight with to_time <= from_time
        # which means ALL slots match (slot_tod >= 00:00 always true)
        # All 96 slots should be in a single day's period
        assert len(periods) == 1
        assert len(periods[0]) == 96

    def test_full_day_two_days(self, now, today_prices, tomorrow_prices):
        """Full-day period with two days produces two groups."""
        all_raw = today_prices + tomorrow_prices
        schedule = _build_base_schedule(all_raw, now, None, None)
        periods = _partition_into_periods(schedule, "00:00", "00:00", now)

        assert len(periods) == 2
        assert len(periods[0]) == 96  # today
        assert len(periods[1]) == 96  # tomorrow

    def test_custom_daytime_period(self, now, today_prices):
        """A daytime period (06:00 to 18:00) includes only those hours."""
        schedule = _build_base_schedule(today_prices, now, None, None)
        periods = _partition_into_periods(schedule, "06:00", "18:00", now)

        assert len(periods) == 1
        # 12 hours * 4 = 48 slots
        assert len(periods[0]) == 48
        # Verify all slots are within 06:00-18:00
        for idx in periods[0]:
            slot_time = datetime.fromisoformat(schedule[idx]["time"]).astimezone(TZ)
            assert 6 <= slot_time.hour < 18

    def test_cross_midnight_period(self, now, today_prices):
        """A cross-midnight period (22:00 to 06:00) spans midnight correctly."""
        schedule = _build_base_schedule(today_prices, now, None, None)
        periods = _partition_into_periods(schedule, "22:00", "06:00", now)

        assert len(periods) >= 1
        # Today has hours 22-23 (after from_time) + hours 0-5 (before to_time)
        # 22:00 and 23:00 belong to the period starting on today's date
        # 00:00-05:45 belong to the period starting on yesterday's date (feb 5)
        total_slots = sum(len(p) for p in periods)
        # 8 hours * 4 = 32 slots total across midnight
        assert total_slots == 32

    def test_cross_midnight_two_days(self, now, today_prices, tomorrow_prices):
        """Cross-midnight period with two days' data creates proper groups."""
        all_raw = today_prices + tomorrow_prices
        schedule = _build_base_schedule(all_raw, now, None, None)
        periods = _partition_into_periods(schedule, "22:00", "06:00", now)

        # Feb 5 period (today 00:00-05:45), Feb 6 period (today 22-23 + tomorrow 00-05),
        # Feb 7 period (tomorrow 22-23)
        # Should have 2-3 periods depending on which dates are represented
        assert len(periods) >= 2
        # Each period should have at most 32 slots (8h * 4)
        for period in periods:
            assert len(period) <= 32

    def test_slots_outside_period_excluded(self, now, today_prices):
        """Slots outside the period boundaries are not included in any group."""
        schedule = _build_base_schedule(today_prices, now, None, None)
        periods = _partition_into_periods(schedule, "10:00", "14:00", now)

        # Only 4 hours * 4 = 16 slots should be included
        total_included = sum(len(p) for p in periods)
        assert total_included == 16
        # Total schedule is 96 — 80 slots are outside any period
        all_included = set()
        for p in periods:
            all_included.update(p)
        assert len(all_included) == 16
        # 80 slots are excluded from periods
        assert 96 - len(all_included) == 80


class TestLowestPriceStrategy:
    """Tests for the Lowest Price scheduling strategy."""

    def test_full_day_default(self, now, today_prices):
        """Default full-day period activates cheapest slots across the whole day."""
        schedule = build_lowest_price_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
        )

        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) == 10  # 2.5h * 4

        # Active slots should be the cheapest
        active_prices = sorted(s["price"] for s in active)
        standby_prices = sorted(s["price"] for s in schedule if s["status"] == "standby")
        assert active_prices[-1] <= standby_prices[0]

    def test_via_build_schedule_dispatcher(self, now, today_prices):
        """build_schedule with strategy='lowest_price' dispatches correctly."""
        schedule_direct = build_lowest_price_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
        )
        schedule_dispatched = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            strategy="lowest_price",
        )

        assert len(schedule_direct) == len(schedule_dispatched)
        for a, b in zip(schedule_direct, schedule_dispatched, strict=True):
            assert a["status"] == b["status"]
            assert a["time"] == b["time"]
            assert a["price"] == b["price"]

    def test_custom_period(self, now, today_prices):
        """Custom period 06:00-18:00 activates cheapest slots only within that window."""
        schedule = build_lowest_price_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.0,  # 8 slots per period
            now=now,
            period_from="06:00",
            period_to="18:00",
        )

        active = [s for s in schedule if s["status"] == "active"]
        # All active slots must be within 06:00-18:00
        for s in active:
            slot_hour = datetime.fromisoformat(s["time"]).astimezone(TZ).hour
            assert 6 <= slot_hour < 18, f"Active slot at hour {slot_hour} is outside period"

        # Should have exactly 8 active slots (2h quota for the one period)
        assert len(active) == 8

    def test_cross_midnight_period(self, now, today_prices):
        """Cross-midnight period 22:00-06:00 activates cheapest in that window."""
        schedule = build_lowest_price_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=1.0,  # 4 slots per period
            now=now,
            period_from="22:00",
            period_to="06:00",
        )

        active = [s for s in schedule if s["status"] == "active"]
        # Active slots should be in 22-23 or 0-5 range
        for s in active:
            slot_hour = datetime.fromisoformat(s["time"]).astimezone(TZ).hour
            assert slot_hour >= 22 or slot_hour < 6, (
                f"Active slot at hour {slot_hour} is outside cross-midnight period"
            )

    def test_per_period_quota(self, now, today_prices, tomorrow_prices):
        """Each period gets its own independent activation quota."""
        schedule = build_lowest_price_schedule(
            raw_today=today_prices,
            raw_tomorrow=tomorrow_prices,
            min_hours=1.0,  # 4 slots per period
            now=now,
        )

        # Full-day mode: each day is a separate period
        today_active = [
            s for s in schedule
            if s["status"] == "active"
            and datetime.fromisoformat(s["time"]).astimezone(TZ).date()
            == datetime(2026, 2, 6, tzinfo=TZ).date()
        ]
        tomorrow_active = [
            s for s in schedule
            if s["status"] == "active"
            and datetime.fromisoformat(s["time"]).astimezone(TZ).date()
            == datetime(2026, 2, 7, tzinfo=TZ).date()
        ]

        # Each day should have at least 4 active slots (1h quota)
        assert len(today_active) >= 4
        assert len(tomorrow_active) >= 4

    def test_with_tomorrow_data(self, now, today_prices, tomorrow_prices):
        """Tomorrow data is included and gets its own quota."""
        schedule = build_lowest_price_schedule(
            raw_today=today_prices,
            raw_tomorrow=tomorrow_prices,
            min_hours=2.0,
            now=now,
        )

        assert len(schedule) == 192  # 96 + 96

    def test_consecutive_does_not_migrate_slots_across_days(
        self, now, today_prices, tomorrow_prices
    ):
        """Each day keeps its own active slots after consecutive enforcement.

        Regression test: _enforce_min_consecutive was applied globally across
        today+tomorrow, causing all active slots to land on the cheaper day.
        """
        schedule = build_lowest_price_schedule(
            raw_today=today_prices,
            raw_tomorrow=tomorrow_prices,
            min_hours=1.0,
            now=now,
            min_consecutive_hours=1.0,
        )

        today_slots = [s for s in schedule if datetime.fromisoformat(s["time"]).astimezone(TZ).date() == now.date()]
        tomorrow_slots = [s for s in schedule if datetime.fromisoformat(s["time"]).astimezone(TZ).date() != now.date()]

        today_active = sum(1 for s in today_slots if s["status"] == "active")
        tomorrow_active = sum(1 for s in tomorrow_slots if s["status"] == "active")

        assert today_active >= 4, f"Today should have at least 1 active hour, got {today_active} slots"
        assert tomorrow_active >= 4, f"Tomorrow should have at least 1 active hour, got {tomorrow_active} slots"

    def test_exclusion_interaction(self, now, today_prices):
        """Excluded slots in custom periods stay excluded."""
        schedule = build_lowest_price_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.0,
            now=now,
            period_from="06:00",
            period_to="18:00",
            exclude_from="10:00:00",
            exclude_until="12:00:00",
        )

        for s in schedule:
            slot_hour = datetime.fromisoformat(s["time"]).astimezone(TZ).hour
            if 10 <= slot_hour < 12:
                assert s["status"] == "excluded", f"Hour {slot_hour} should be excluded"

    def test_consecutive_within_period(self, now, today_prices):
        """Consecutive enforcement works within period bounds."""
        schedule = build_lowest_price_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.0,
            now=now,
            min_consecutive_hours=2.0,  # 8 quarter-slots per block
        )

        # All future active blocks should be at least 8 quarter-slots
        future_blocks = [
            (start, length) for start, length in _find_active_blocks(schedule)
            if datetime.fromisoformat(schedule[start]["time"]).astimezone(TZ) >= now
        ]
        for start, length in future_blocks:
            assert length >= 8, f"Block at index {start} has length {length}, expected >= 8"

    def test_inverted_mode(self, now, today_prices):
        """Inverted mode (most_expensive) selects the most expensive slots."""
        schedule = build_lowest_price_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            selection_mode="most_expensive",
        )

        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) == 10

        # Active prices should be >= standby prices
        active_prices = sorted(s["price"] for s in active)
        standby_prices = sorted(s["price"] for s in schedule if s["status"] == "standby")
        assert active_prices[0] >= standby_prices[-1]

    def test_always_cheap(self, now, today_prices):
        """always_cheap forces activation of cheap slots beyond quota."""
        schedule = build_lowest_price_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=0.25,
            now=now,
            always_cheap=0.10,
        )

        cheap = [s for s in schedule if s["price"] <= 0.10]
        for s in cheap:
            assert s["status"] == "active"

    def test_always_expensive(self, now, today_prices):
        """always_expensive prevents activation of expensive slots."""
        schedule = build_lowest_price_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=6.0,
            now=now,
            always_expensive=0.30,
        )

        for s in schedule:
            if s["price"] >= 0.30:
                assert s["status"] != "active", f"Slot at price {s['price']} should not be active"

    def test_price_similarity(self, now):
        """Price similarity expands activation to similarly priced slots."""
        prices = [slot for h in range(24) for slot in make_nordpool_hour(h, 0.10 + (h % 4) * 0.01)]
        schedule = build_lowest_price_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours=2.5,
            now=now,
            price_similarity_pct=20.0,
        )

        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) > 10  # More than base quota

    def test_empty_data(self, now):
        """Empty input produces empty schedule."""
        schedule = build_lowest_price_schedule(
            raw_today=[],
            raw_tomorrow=[],
            min_hours=2.0,
            now=now,
        )
        assert len(schedule) == 0

    def test_custom_period_with_tomorrow(self, now, today_prices, tomorrow_prices):
        """Custom period across two days gives each period day its own quota."""
        schedule = build_lowest_price_schedule(
            raw_today=today_prices,
            raw_tomorrow=tomorrow_prices,
            min_hours=1.0,  # 4 slots per period
            now=now,
            period_from="08:00",
            period_to="20:00",
        )

        # Each day's 08:00-20:00 period should have active slots
        today_active = [
            s for s in schedule
            if s["status"] == "active"
            and datetime.fromisoformat(s["time"]).astimezone(TZ).date()
            == datetime(2026, 2, 6, tzinfo=TZ).date()
        ]
        tomorrow_active = [
            s for s in schedule
            if s["status"] == "active"
            and datetime.fromisoformat(s["time"]).astimezone(TZ).date()
            == datetime(2026, 2, 7, tzinfo=TZ).date()
        ]

        assert len(today_active) >= 4
        assert len(tomorrow_active) >= 4


class TestMinimumRuntimeStrategy:
    """Tests for the Minimum Runtime scheduling strategy."""

    def test_basic_deadline_scheduling(self, now, today_prices):
        """Basic deadline scheduling: places a block before the deadline."""
        last_on = now - timedelta(hours=4)
        schedule = build_minimum_runtime_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours_on=1.0,  # 4 slots
            now=now,
            max_hours_off=6.0,
            last_on_time=last_on,
        )

        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) >= 4

        # The first active block must start before the first deadline
        # (last_on + 6h = now + 2h). Subsequent blocks may be placed later.
        deadline = last_on + timedelta(hours=6)
        first_block_start = datetime.fromisoformat(active[0]["time"]).astimezone(TZ)
        assert first_block_start < deadline, (
            f"First active block at {first_block_start} starts at or after deadline {deadline}"
        )

    def test_via_build_schedule_dispatcher(self, now, today_prices):
        """build_schedule with strategy='minimum_runtime' dispatches correctly."""
        last_on = now - timedelta(hours=4)
        schedule_direct = build_minimum_runtime_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours_on=1.0,
            now=now,
            max_hours_off=6.0,
            last_on_time=last_on,
        )
        schedule_dispatched = build_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours=1.0,
            now=now,
            strategy="minimum_runtime",
            max_hours_off=6.0,
            last_on_time=last_on,
        )

        assert len(schedule_direct) == len(schedule_dispatched)
        for a, b in zip(schedule_direct, schedule_dispatched, strict=True):
            assert a["status"] == b["status"]
            assert a["time"] == b["time"]

    def test_no_last_on_time_first_run(self, now, today_prices):
        """Without last_on_time (first run), find cheapest block within max_hours_off window."""
        schedule = build_minimum_runtime_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours_on=1.0,
            now=now,
            max_hours_off=8.0,
            last_on_time=None,
        )

        # Should have an active block within the deadline window (now + 8h)
        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) >= 4

        # Verify at least one active slot exists within the first deadline window
        deadline = now + timedelta(hours=8)
        slots_before_deadline = [
            s for s in active
            if datetime.fromisoformat(s["time"]).astimezone(TZ) < deadline
        ]
        assert len(slots_before_deadline) >= 4, (
            f"Expected at least 4 active slots before deadline ({deadline}), "
            f"got {len(slots_before_deadline)}"
        )

    def test_mid_slot_now_includes_current_slot(self, today_prices):
        """When now falls mid-slot, the current ongoing slot should be schedulable."""
        # now at 14:37 — mid-way through the 14:30 slot
        mid_slot_now = datetime(2026, 2, 6, 14, 37, 0, tzinfo=TZ)
        last_on = mid_slot_now - timedelta(hours=6)

        schedule = build_minimum_runtime_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours_on=1.0,
            now=mid_slot_now,
            max_hours_off=6.0,
            last_on_time=last_on,
        )

        # The current slot (14:30) should be a candidate — verify it can be active
        current_slot = None
        for s in schedule:
            slot_time = datetime.fromisoformat(s["time"]).astimezone(TZ)
            if slot_time <= mid_slot_now < slot_time + timedelta(minutes=15):
                current_slot = s
                break
        assert current_slot is not None, "Current slot not found in schedule"
        # The 14:30 slot should be schedulable (not forced to standby)
        # Whether it's active depends on prices, but it must be considered.
        # With the deadline at 14:37 (last_on + 6h = 08:37, which is past),
        # the scheduler should activate immediately including the current slot.
        active_slots = [s for s in schedule if s["status"] == "active"]
        assert len(active_slots) >= 4  # 1 hour = 4 slots
        # At least one active slot should be at or before the current slot time
        earliest_active = min(
            datetime.fromisoformat(s["time"]).astimezone(TZ) for s in active_slots
        )
        assert earliest_active <= mid_slot_now, (
            f"Earliest active slot {earliest_active} is after now ({mid_slot_now}) — "
            "current slot was not included in scheduling"
        )

    def test_optimal_block_selection(self, now):
        """Should select the cheapest consecutive block before the deadline."""
        # Create prices with a clear cheap block at h16-16:45 and expensive elsewhere
        hourly_prices = [0.80] * 24
        hourly_prices[16] = 0.10  # Cheap block
        hourly_prices[15] = 0.90  # Expensive neighbor
        prices = [slot for h, p in enumerate(hourly_prices) for slot in make_nordpool_hour(h, p)]

        last_on = now - timedelta(hours=2)  # Deadline: now + 4h = 18:30
        schedule = build_minimum_runtime_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours_on=1.0,
            now=now,
            max_hours_off=6.0,
            last_on_time=last_on,
        )

        # Hour 16 should be the selected block (cheapest available before deadline)
        hour16_active = [
            s for s in schedule
            if s["status"] == "active"
            and datetime.fromisoformat(s["time"]).astimezone(TZ).hour == 16
        ]
        assert len(hour16_active) == 4, "Cheapest block at h16 should be selected"

    def test_imminent_deadline(self, now, today_prices):
        """When deadline is imminent, emergency activation occurs."""
        # Last on was almost max_hours_off ago, deadline is very soon
        last_on = now - timedelta(hours=5, minutes=45)  # deadline in 15 min
        schedule = build_minimum_runtime_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours_on=1.0,
            now=now,
            max_hours_off=6.0,
            last_on_time=last_on,
        )

        # Should have activated some slots even if not ideal
        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) >= 4

    def test_respects_always_expensive(self, now):
        """always_expensive prevents activation of expensive slots."""
        hourly_prices = [0.50] * 24
        hourly_prices[15] = 0.10
        hourly_prices[16] = 5.00  # Very expensive
        hourly_prices[17] = 0.10
        prices = [slot for h, p in enumerate(hourly_prices) for slot in make_nordpool_hour(h, p)]

        last_on = now - timedelta(hours=2)
        schedule = build_minimum_runtime_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours_on=1.0,
            now=now,
            max_hours_off=8.0,
            last_on_time=last_on,
            always_expensive=4.00,
        )

        # Expensive slots should not be activated (max_hours_off=8 and
        # last_on only 2 h ago, so no emergency pressure exists).
        for s in schedule:
            if s["price"] >= 4.00:
                assert s["status"] != "active", (
                    f"Expensive slot unexpectedly activated: {s}"
                )

    def test_exclusion_zones(self, now, today_prices):
        """Excluded time ranges are respected."""
        last_on = now - timedelta(hours=4)
        schedule = build_minimum_runtime_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours_on=1.0,
            now=now,
            max_hours_off=8.0,
            last_on_time=last_on,
            exclude_from="18:00:00",
            exclude_until="22:00:00",
        )

        for s in schedule:
            slot_hour = datetime.fromisoformat(s["time"]).astimezone(TZ).hour
            if 18 <= slot_hour < 22:
                assert s["status"] == "excluded", (
                    f"Hour {slot_hour} should be excluded"
                )

    def test_with_tomorrow_data(self, now, today_prices, tomorrow_prices):
        """Schedule extends across both days of data."""
        last_on = now - timedelta(hours=2)
        schedule = build_minimum_runtime_schedule(
            raw_today=today_prices,
            raw_tomorrow=tomorrow_prices,
            min_hours_on=1.0,
            now=now,
            max_hours_off=6.0,
            last_on_time=last_on,
        )

        assert len(schedule) == 192  # Both days included

    def test_insufficient_data_for_deadline(self, now):
        """When data doesn't extend to the deadline, emergency activation fires."""
        # Only 2 hours of data, but deadline is far away
        prices = [slot for h in range(15, 17) for slot in make_nordpool_hour(h, 0.50)]
        last_on = now - timedelta(hours=20)  # Deadline is way past
        schedule = build_minimum_runtime_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours_on=1.0,
            now=now,
            max_hours_off=24.0,
            last_on_time=last_on,
        )

        # Should still produce a schedule and activate what's available
        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) >= 4

    def test_multiple_blocks_in_horizon(self, now, today_prices, tomorrow_prices):
        """With enough data, multiple on-blocks are scheduled iteratively."""
        last_on = now - timedelta(hours=2)
        schedule = build_minimum_runtime_schedule(
            raw_today=today_prices,
            raw_tomorrow=tomorrow_prices,
            min_hours_on=1.0,  # 1h on-blocks
            now=now,
            max_hours_off=4.0,  # Must run every 4 hours
            last_on_time=last_on,
        )

        # With ~33.5 hours of data remaining after now, and 4h off + 1h on cycle,
        # should schedule multiple blocks
        active_blocks = _find_active_blocks(schedule)
        # Count future blocks only
        future_blocks = [
            (start, length) for start, length in active_blocks
            if datetime.fromisoformat(schedule[start]["time"]).astimezone(TZ) >= now
        ]
        assert len(future_blocks) >= 2, (
            f"Expected multiple future blocks with 4h max_off, got {len(future_blocks)}"
        )

    def test_always_cheap_bonus_activations(self, now):
        """always_cheap activates bonus cheap slots beyond the scheduled blocks."""
        hourly_prices = [0.50] * 24
        hourly_prices[15] = 0.01  # Very cheap
        hourly_prices[20] = 0.01  # Very cheap
        hourly_prices[16] = 0.30  # Moderate (will be in the scheduled block area)
        prices = [slot for h, p in enumerate(hourly_prices) for slot in make_nordpool_hour(h, p)]

        last_on = now - timedelta(hours=2)
        schedule = build_minimum_runtime_schedule(
            raw_today=prices,
            raw_tomorrow=[],
            min_hours_on=1.0,
            now=now,
            max_hours_off=8.0,
            last_on_time=last_on,
            always_cheap=0.05,
        )

        # All slots with price <= 0.05 should be active (bonus activations)
        cheap_slots = [s for s in schedule if s["price"] <= 0.05 and s["status"] != "excluded"]
        for s in cheap_slots:
            assert s["status"] == "active", (
                f"Cheap slot at {s['time']} (price={s['price']}) should be active via always_cheap"
            )

    def test_inverted_mode(self, now, today_prices):
        """Inverted mode selects the most expensive consecutive block."""
        last_on = now - timedelta(hours=4)
        schedule = build_minimum_runtime_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours_on=1.0,
            now=now,
            max_hours_off=6.0,
            last_on_time=last_on,
            selection_mode="most_expensive",
        )

        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) >= 4

    def test_empty_data(self, now):
        """Empty input produces empty schedule."""
        schedule = build_minimum_runtime_schedule(
            raw_today=[],
            raw_tomorrow=[],
            min_hours_on=1.0,
            now=now,
        )
        assert len(schedule) == 0

    def test_zero_min_hours_on(self, now, today_prices):
        """Zero min_hours_on results in no active blocks."""
        schedule = build_minimum_runtime_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours_on=0,
            now=now,
            max_hours_off=6.0,
            last_on_time=now - timedelta(hours=4),
        )

        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) == 0

    def test_consecutive_block_integrity(self, now, today_prices):
        """The on-block should be a contiguous set of slots."""
        last_on = now - timedelta(hours=4)
        schedule = build_minimum_runtime_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours_on=2.0,  # 8 consecutive slots
            now=now,
            max_hours_off=8.0,
            last_on_time=last_on,
        )

        blocks = _find_active_blocks(schedule)
        future_blocks = [
            (start, length) for start, length in blocks
            if datetime.fromisoformat(schedule[start]["time"]).astimezone(TZ) >= now
        ]

        # Each scheduled block should be at least min_hours_on * 4 slots
        for start, length in future_blocks:
            assert length >= 8, (
                f"Block at index {start} has length {length}, expected >= 8 for 2h min_hours_on"
            )

    def test_mid_day_recompute_skips_past_slots(self, now, today_prices):
        """When schedule is recomputed mid-day, past slots must not be activated.

        Cheapest prices are at 03:00 (0.03) and 04:00 (0.04), both well in the
        past when now=14:30. The scheduler must only pick future slots.
        """
        last_on = now - timedelta(hours=2)
        schedule = build_minimum_runtime_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours_on=1.0,  # 4 slots needed
            now=now,
            max_hours_off=6.0,
            last_on_time=last_on,
        )

        for s in schedule:
            slot_time = datetime.fromisoformat(s["time"]).astimezone(now.tzinfo)
            slot_end = slot_time + timedelta(minutes=15)
            if slot_end <= now and s["status"] == "active":
                pytest.fail(
                    f"Past slot at {s['time']} (price={s['price']}) was activated"
                )

    def test_mid_day_recompute_activates_enough_future_slots(self, now, today_prices):
        """Mid-day recompute must still activate the required number of future slots."""
        last_on = now - timedelta(hours=2)
        schedule = build_minimum_runtime_schedule(
            raw_today=today_prices,
            raw_tomorrow=[],
            min_hours_on=1.0,  # 4 slots needed
            now=now,
            max_hours_off=6.0,
            last_on_time=last_on,
        )

        future_active = [
            s for s in schedule
            if s["status"] == "active"
            and datetime.fromisoformat(s["time"]).astimezone(now.tzinfo)
            + timedelta(minutes=15) > now
        ]
        assert len(future_active) >= 4, (
            f"Expected at least 4 future active slots, got {len(future_active)}"
        )


class TestMinimumRuntimeDeadlineWindowing:
    """Tests for the deadline-based windowing in Minimum Runtime strategy.

    The main loop partitions the schedule horizon into sequential windows
    anchored by deadlines (last_on + max_hours_off) and picks the cheapest
    slots in each window.  These tests verify correctness of this approach.
    """

    def _make_prices(self, base_date, hourly_prices):
        """Build price slots for one day from hourly prices."""
        slots = []
        for h, p in enumerate(hourly_prices):
            for q in range(4):
                start = base_date.replace(hour=h, minute=q * 15)
                end = start + timedelta(minutes=15)
                slots.append({
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "value": p,
                })
        return slots

    def test_cheap_prices_far_away_selected(self):
        """When cheap prices are far from now but within the deadline window,
        the main loop selects them instead of expensive near-term slots.
        """
        now = datetime(2026, 3, 17, 21, 5, 0, tzinfo=TZ)
        base_today = datetime(2026, 3, 17, tzinfo=TZ)
        base_tomorrow = datetime(2026, 3, 18, tzinfo=TZ)

        # Expensive tonight (0.80), cheap tomorrow 10:00-14:00 (0.05)
        today_hourly = [0.50] * 14 + [0.80] * 10
        tomorrow_hourly = [0.60] * 10 + [0.05] * 4 + [0.60] * 10

        prices_today = self._make_prices(base_today, today_hourly)
        prices_tomorrow = self._make_prices(base_tomorrow, tomorrow_hourly)

        last_on = datetime(2026, 3, 17, 13, 15, 0, tzinfo=TZ)
        schedule = build_minimum_runtime_schedule(
            raw_today=prices_today,
            raw_tomorrow=prices_tomorrow,
            min_hours_on=4.0,
            now=now,
            max_hours_off=24.0,
            last_on_time=last_on,
        )

        # The cheap slots tomorrow (0.05) should be selected
        cheap_active = [
            s for s in schedule
            if s["status"] == "active" and s["price"] == 0.05
        ]
        assert len(cheap_active) == 16, (
            f"Expected 16 cheap (0.05) active slots, got {len(cheap_active)}"
        )

    def test_deadline_forces_activation_before_cheap_period(self):
        """When the deadline is before the cheap period, slots before
        the deadline are selected even if more expensive.
        """
        now = datetime(2026, 3, 17, 14, 30, 0, tzinfo=TZ)
        base_today = datetime(2026, 3, 17, tzinfo=TZ)
        base_tomorrow = datetime(2026, 3, 18, tzinfo=TZ)

        # Moderate today, very cheap tomorrow evening (far beyond deadline)
        today_hourly = [0.50] * 24
        tomorrow_hourly = [0.50] * 20 + [0.01] * 4

        prices_today = self._make_prices(base_today, today_hourly)
        prices_tomorrow = self._make_prices(base_tomorrow, tomorrow_hourly)

        # last_on = 12:30, deadline = 12:30 + 6h = 18:30, window ends at 18:30 + 1h = 19:30
        last_on = now - timedelta(hours=2)
        schedule = build_minimum_runtime_schedule(
            raw_today=prices_today,
            raw_tomorrow=prices_tomorrow,
            min_hours_on=1.0,
            now=now,
            max_hours_off=6.0,
            last_on_time=last_on,
        )

        # Must have slots activated before the first deadline window ends
        first_window_end = last_on + timedelta(hours=6.0 + 1.0)  # deadline + min_hours_on
        active_before = [
            s for s in schedule
            if s["status"] == "active"
            and datetime.fromisoformat(s["time"]).astimezone(TZ) < first_window_end
        ]
        assert len(active_before) >= 4, (
            f"Expected at least 4 active slots before first deadline window, "
            f"got {len(active_before)}"
        )

    def test_no_unnecessary_activations(self, now, today_prices, tomorrow_prices):
        """The main loop should not over-activate beyond what's needed."""
        last_on = now - timedelta(hours=2)
        schedule = build_minimum_runtime_schedule(
            raw_today=today_prices,
            raw_tomorrow=tomorrow_prices,
            min_hours_on=1.0,
            now=now,
            max_hours_off=4.0,
            last_on_time=last_on,
        )

        active = sum(1 for s in schedule if s["status"] == "active")
        # With 4h off + 1h on = 5h window, the main loop places ~1h per 5h
        # → ~6-7 windows in 33.5h of data → ~24-28 active slots.
        assert active <= 50, (
            f"Too many active slots ({active}); main loop may be over-activating"
        )

    def test_min_consecutive_with_deadline(self):
        """min_consecutive_hours works correctly with deadline windowing."""
        now = datetime(2026, 3, 17, 21, 0, 0, tzinfo=TZ)
        base_today = datetime(2026, 3, 17, tzinfo=TZ)
        base_tomorrow = datetime(2026, 3, 18, tzinfo=TZ)

        today_hourly = [0.50] * 24
        tomorrow_hourly = [0.60] * 10 + [0.05] * 4 + [0.60] * 10

        prices_today = self._make_prices(base_today, today_hourly)
        prices_tomorrow = self._make_prices(base_tomorrow, tomorrow_hourly)

        last_on = datetime(2026, 3, 17, 13, 15, 0, tzinfo=TZ)
        schedule = build_minimum_runtime_schedule(
            raw_today=prices_today,
            raw_tomorrow=prices_tomorrow,
            min_hours_on=4.0,
            now=now,
            max_hours_off=24.0,
            last_on_time=last_on,
            min_consecutive_hours=0.5,
        )

        # After consecutive enforcement, no active block should be < 2 slots
        blocks = _find_active_blocks(schedule)
        future_blocks = [
            (start, length) for start, length in blocks
            if datetime.fromisoformat(schedule[start]["time"]).astimezone(TZ) >= now
        ]
        for start, length in future_blocks:
            assert length >= 2, (
                f"Block at index {start} has length {length}, "
                "expected >= 2 for 0.5h min_consecutive"
            )

    def test_respects_always_expensive(self):
        """always_expensive prevents activation even with deadline pressure."""
        now = datetime(2026, 3, 17, 21, 0, 0, tzinfo=TZ)
        base_today = datetime(2026, 3, 17, tzinfo=TZ)
        base_tomorrow = datetime(2026, 3, 18, tzinfo=TZ)

        today_hourly = [5.0] * 24
        # 10:00-14:00 cheap (window 1), 17:00-21:00 cheap (window 2)
        tomorrow_hourly = (
            [5.0] * 10 + [1.0] * 4 + [5.0] * 3 + [1.0] * 4 + [5.0] * 3
        )

        prices_today = self._make_prices(base_today, today_hourly)
        prices_tomorrow = self._make_prices(base_tomorrow, tomorrow_hourly)

        last_on = datetime(2026, 3, 17, 13, 0, 0, tzinfo=TZ)
        schedule = build_minimum_runtime_schedule(
            raw_today=prices_today,
            raw_tomorrow=prices_tomorrow,
            min_hours_on=4.0,
            now=now,
            max_hours_off=24.0,
            last_on_time=last_on,
            always_expensive=4.0,
        )

        # No slot with price >= 4.0 should be active (except emergency)
        for s in schedule:
            t = datetime.fromisoformat(s["time"]).astimezone(TZ)
            if t < now:
                continue
            if s["status"] == "active":
                assert s["price"] < 4.0, (
                    f"Slot at {s['time']} (price={s['price']}) is above "
                    "always_expensive and should not have been activated"
                )

    def test_first_run_no_last_on_time(self):
        """On first run (no last_on_time), activates within the first window."""
        now = datetime(2026, 3, 17, 14, 30, 0, tzinfo=TZ)
        base_today = datetime(2026, 3, 17, tzinfo=TZ)
        base_tomorrow = datetime(2026, 3, 18, tzinfo=TZ)

        today_hourly = [0.05] * 4 + [0.50] * 20
        tomorrow_hourly = [0.40] * 24

        prices_today = self._make_prices(base_today, today_hourly)
        prices_tomorrow = self._make_prices(base_tomorrow, tomorrow_hourly)

        schedule = build_minimum_runtime_schedule(
            raw_today=prices_today,
            raw_tomorrow=prices_tomorrow,
            min_hours_on=4.0,
            now=now,
            max_hours_off=24.0,
            last_on_time=None,
        )

        active = [s for s in schedule if s["status"] == "active"]
        assert len(active) >= 16, (
            f"Expected at least 16 active slots, got {len(active)}"
        )

    def test_gap_bounded_by_max_hours_off(self):
        """The gap from last_on_time to the first activation must be
        within max_hours_off — the main loop places slots before the
        deadline, not 13+ hours later.
        """
        now = datetime(2026, 3, 17, 21, 0, 0, tzinfo=TZ)
        base_today = datetime(2026, 3, 17, tzinfo=TZ)
        base_tomorrow = datetime(2026, 3, 18, tzinfo=TZ)

        today_hourly = [0.80] * 24
        tomorrow_hourly = [0.60] * 12 + [0.05] * 4 + [0.60] * 8

        prices_today = self._make_prices(base_today, today_hourly)
        prices_tomorrow = self._make_prices(base_tomorrow, tomorrow_hourly)

        last_on = datetime(2026, 3, 17, 13, 0, 0, tzinfo=TZ)
        schedule = build_minimum_runtime_schedule(
            raw_today=prices_today,
            raw_tomorrow=prices_tomorrow,
            min_hours_on=4.0,
            now=now,
            max_hours_off=24.0,
            last_on_time=last_on,
        )

        # Find first future active slot
        future_active = [
            s for s in schedule
            if s["status"] == "active"
            and datetime.fromisoformat(s["time"]).astimezone(TZ) >= now
        ]
        assert future_active, "No future active slots"

        first_active_time = datetime.fromisoformat(
            future_active[0]["time"]
        ).astimezone(TZ)
        gap_from_last_on = (first_active_time - last_on).total_seconds() / 3600

        # The main loop's window extends from search_from to
        # deadline + min_hours_on. The first activation must start within
        # that window, so well under max_hours_off + min_hours_on from last_on.
        assert gap_from_last_on <= 24.0 + 4.0, (
            f"Gap from last_on to first active is {gap_from_last_on:.1f}h, "
            "expected within the first deadline window (24+4=28h)"
        )

    def test_small_rolling_window_fills_horizon(self):
        """With a small rolling window, multiple blocks fill the horizon."""
        now = datetime(2026, 3, 17, 14, 30, 0, tzinfo=TZ)
        base_today = datetime(2026, 3, 17, tzinfo=TZ)
        base_tomorrow = datetime(2026, 3, 18, tzinfo=TZ)

        # Uniform prices so selection doesn't matter
        today_hourly = [0.50] * 24
        tomorrow_hourly = [0.50] * 24

        prices_today = self._make_prices(base_today, today_hourly)
        prices_tomorrow = self._make_prices(base_tomorrow, tomorrow_hourly)

        last_on = now - timedelta(hours=2)
        schedule = build_minimum_runtime_schedule(
            raw_today=prices_today,
            raw_tomorrow=prices_tomorrow,
            min_hours_on=1.0,   # 4 slots
            now=now,
            max_hours_off=4.0,  # 5h rolling window
            last_on_time=last_on,
        )

        # With 4h off + 1h on = 5h cycle over ~33.5h of data,
        # should have multiple blocks distributed across the schedule.
        blocks = _find_active_blocks(schedule)
        future_blocks = [
            (start, length) for start, length in blocks
            if datetime.fromisoformat(schedule[start]["time"]).astimezone(TZ) >= now
        ]
        assert len(future_blocks) >= 4, (
            f"Expected at least 4 future blocks with 4h max_off, "
            f"got {len(future_blocks)}"
        )

    def test_recently_on_device_picks_cheapest_in_window(self):
        """When the device was just on, the scheduler picks cheapest slots
        within the deadline window, not expensive near-term ones.
        """
        now = datetime(2026, 3, 20, 15, 18, 0, tzinfo=TZ)
        base_today = datetime(2026, 3, 20, tzinfo=TZ)
        base_tomorrow = datetime(2026, 3, 21, tzinfo=TZ)

        # Expensive today afternoon/evening, very cheap tomorrow midday
        today_hourly = (
            [1.80] * 10  # 00-09: moderate overnight
            + [1.00] * 3  # 10-12: dropping
            + [0.50] * 3  # 13-15: cheap midday
            + [2.00] * 4  # 16-19: expensive evening
            + [1.80] * 4  # 20-23: evening decline
        )
        tomorrow_hourly = (
            [0.80] * 10  # 00-09: moderate
            + [0.30] * 2  # 10-11: fairly cheap
            + [0.08] * 4  # 12-15: very cheap
            + [1.50] * 4  # 16-19: expensive
            + [0.80] * 4  # 20-23: moderate
        )

        prices_today = self._make_prices(base_today, today_hourly)
        prices_tomorrow = self._make_prices(base_tomorrow, tomorrow_hourly)

        # Device was just on 1 minute ago
        last_on = now - timedelta(minutes=1)

        schedule = build_minimum_runtime_schedule(
            raw_today=prices_today,
            raw_tomorrow=prices_tomorrow,
            min_hours_on=4.0,   # 16 slots
            now=now,
            max_hours_off=26.0,  # rolling_window = 30h
            last_on_time=last_on,
            min_consecutive_hours=0.5,
        )

        # The main loop should pick cheap slots tomorrow, not expensive ones now.
        expensive_active = [
            s for s in schedule
            if s["status"] == "active"
            and 2.0 <= s["price"]
            and now <= datetime.fromisoformat(s["time"]).astimezone(TZ) < base_tomorrow
        ]
        assert len(expensive_active) == 0, (
            f"Main loop activated {len(expensive_active)} expensive (>=2.0) slots "
            f"today; expected 0 since the deadline is 26h away. Slots: "
            + ", ".join(
                f"{s['time']} @ {s['price']}" for s in expensive_active
            )
        )

        # The cheapest slots tomorrow (price < 0.10) should be selected
        cheap_tomorrow_active = [
            s for s in schedule
            if s["status"] == "active"
            and s["price"] < 0.10
        ]
        assert len(cheap_tomorrow_active) >= 12, (
            f"Expected at least 12 very cheap (<0.10) active slots, "
            f"got {len(cheap_tomorrow_active)}"
        )

    def test_recompute_with_cheaper_tomorrow_prices(self):
        """When new (even cheaper) tomorrow prices arrive, a recomputation
        selects those cheaper slots instead of the previously scheduled ones.

        Simulates: first run picks best 4h from today+tomorrow_day1.
        Then new tomorrow_day2 prices arrive (much cheaper) and the schedule
        is recomputed from a later `now` with last_on_time from the first block.
        """
        base_day1 = datetime(2026, 3, 21, tzinfo=TZ)
        base_day2 = datetime(2026, 3, 22, tzinfo=TZ)

        # Day 1: moderate prices, cheapest midday (0.30)
        day1_hourly = (
            [0.80] * 10   # 00-09
            + [0.50] * 2  # 10-11
            + [0.30] * 4  # 12-15: cheapest today
            + [0.80] * 8  # 16-23
        )
        # Day 2 (new prices): very cheap midday (0.02)
        day2_hourly = (
            [0.60] * 10   # 00-09
            + [0.20] * 2  # 10-11
            + [0.02] * 4  # 12-15: much cheaper than day 1
            + [0.60] * 8  # 16-23
        )

        prices_day1 = self._make_prices(base_day1, day1_hourly)
        prices_day2 = self._make_prices(base_day2, day2_hourly)

        # First run at 13:00 on day 1 picked 12:00-15:45 (the 0.30 block).
        # Device finished running at ~16:00.
        last_on = datetime(2026, 3, 21, 16, 0, 0, tzinfo=TZ)

        # Recompute at 17:00 on day 1 when day 2 prices have just arrived.
        now_recompute = datetime(2026, 3, 21, 17, 0, 0, tzinfo=TZ)

        schedule = build_minimum_runtime_schedule(
            raw_today=prices_day1,
            raw_tomorrow=prices_day2,
            min_hours_on=4.0,
            now=now_recompute,
            max_hours_off=26.0,
            last_on_time=last_on,
        )

        # The deadline is 16:00 + 26h = Mar 22 18:00.
        # The algorithm should pick the cheapest 4h in that window,
        # which is the 0.02 block on day 2 (12:00-15:45).
        very_cheap_active = [
            s for s in schedule
            if s["status"] == "active" and s["price"] <= 0.02
        ]
        assert len(very_cheap_active) == 16, (
            f"Expected 16 very cheap (<=0.02) active slots from day 2, "
            f"got {len(very_cheap_active)}"
        )

        # No expensive day 1 evening slots should be activated
        day1_evening_active = [
            s for s in schedule
            if s["status"] == "active"
            and s["price"] >= 0.80
            and datetime.fromisoformat(s["time"]).astimezone(TZ) < base_day2
        ]
        assert len(day1_evening_active) == 0, (
            f"Should not activate expensive day 1 evening slots, "
            f"got {len(day1_evening_active)}"
        )

