"""Pure scheduling algorithm for the Power Saver integration.

This module contains no Home Assistant dependencies and can be tested independently.
It provides two scheduling strategies:
- Lowest Price: activate cheapest hours within fixed time periods
- Max Off Time: deadline-based scheduling with minimum on-time
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_datetime(value: str | datetime) -> datetime:
    """Convert a value to a datetime, handling both strings and datetime objects.

    Nordpool stores start/end as datetime objects when accessed via hass.states.get(),
    but as ISO strings when accessed via the WebSocket API (e.g., AppDaemon).
    """
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _compute_similarity_threshold(
    sorted_slots: list[dict],
    price_similarity_pct: float | None,
    inverted: bool = False,
) -> float | None:
    """Compute the price similarity threshold for a group of slots.

    In normal mode: threshold is above the cheapest price (sorted_slots[0] when ascending).
    In inverted mode: threshold is below the most expensive price (sorted_slots[0] when descending).
    Uses an additive offset based on the absolute value of the anchor price.
    """
    if not sorted_slots or not price_similarity_pct or price_similarity_pct <= 0:
        return None
    anchor_price = float(sorted_slots[0].get("value", 0))
    if anchor_price == 0:
        _LOGGER.debug("Price similarity disabled: anchor price is 0")
        return None
    offset = (price_similarity_pct / 100) * abs(anchor_price)
    if inverted:
        threshold = anchor_price - offset
    else:
        threshold = anchor_price + offset
    _LOGGER.debug(
        "Price similarity: anchor=%.3f, pct=%s%%, threshold=%.3f (inverted=%s)",
        anchor_price, price_similarity_pct, threshold, inverted,
    )
    return threshold


def _parse_time(time_str: str) -> time:
    """Parse a time string (HH:MM or HH:MM:SS) into a time object."""
    parts = time_str.split(":")
    return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)


def _is_excluded(
    slot_start: datetime,
    exclude_from: str | None,
    exclude_until: str | None,
) -> bool:
    """Check if a slot falls within the excluded time range.

    Supports cross-midnight ranges (e.g., 22:00 to 06:00).
    Both exclude_from and exclude_until must be set to enable exclusion.
    """
    if not exclude_from or not exclude_until:
        return False

    try:
        from_time = _parse_time(exclude_from)
        until_time = _parse_time(exclude_until)
    except (ValueError, IndexError):
        return False

    slot_time = slot_start.time()

    if from_time <= until_time:
        # Normal range (e.g., 08:00 to 16:00)
        return from_time <= slot_time < until_time
    else:
        # Cross-midnight range (e.g., 22:00 to 06:00)
        return slot_time >= from_time or slot_time < until_time


# ---------------------------------------------------------------------------
# Base schedule construction
# ---------------------------------------------------------------------------

def _build_base_schedule(
    raw_slots: list[dict],
    now: datetime,
    exclude_from: str | None,
    exclude_until: str | None,
) -> list[dict]:
    """Build a time-sorted schedule from raw Nordpool slots.

    All slots are initially marked as standby (or excluded if in the exclusion range).
    """
    schedule: list[dict] = []
    for slot in raw_slots:
        try:
            start = _to_datetime(slot.get("start")).astimezone(now.tzinfo)
            price = float(slot.get("value", 0))
            status = "excluded" if _is_excluded(start, exclude_from, exclude_until) else "standby"
            schedule.append({
                "price": round(price, 3),
                "time": start.isoformat(),
                "status": status,
            })
        except (ValueError, TypeError, KeyError) as e:
            _LOGGER.warning("Error processing slot: %s", e)
    schedule.sort(key=lambda x: x["time"])
    return schedule


# ---------------------------------------------------------------------------
# Slot processing
# ---------------------------------------------------------------------------

def _process_day_slots(
    sorted_slots: list[dict],
    activated_count: int,
    threshold: float | None,
    always_cheap: float | None,
    always_expensive: float | None,
    now: datetime,
    inverted: bool = False,
    exclude_from: str | None = None,
    exclude_until: str | None = None,
) -> tuple[list[dict], int]:
    """Process a group of price-sorted slots into schedule entries.

    This function creates new schedule entries from raw Nordpool slots,
    applying the activation quota, thresholds, and exclusion rules.

    Args:
        sorted_slots: Slots sorted by price (cheapest first in normal mode,
                       most expensive first in inverted mode).
        activated_count: Remaining activation quota.
        threshold: Price similarity threshold, or None if disabled.
        always_cheap: In normal mode: always activate at or below this price.
                      In inverted mode: never activate at or below this price.
        always_expensive: In normal mode: never activate at or above this price.
                         In inverted mode: always activate at or above this price.
        now: Current datetime for timezone conversion.
        inverted: If True, select most expensive hours and swap threshold roles.
        exclude_from: Start of excluded time range ("HH:MM:SS"), or None.
        exclude_until: End of excluded time range ("HH:MM:SS"), or None.

    Returns:
        Tuple of (schedule_entries, remaining_activated_count).
    """
    entries = []
    for slot in sorted_slots:
        try:
            start = _to_datetime(slot.get("start")).astimezone(now.tzinfo)
            price = float(slot.get("value", 0))

            if _is_excluded(start, exclude_from, exclude_until):
                entries.append({
                    "price": round(price, 3),
                    "time": start.isoformat(),
                    "status": "excluded",
                })
                continue

            if inverted:
                is_within_threshold = threshold is not None and price >= threshold
                is_always_activate = always_expensive is not None and price >= always_expensive
                is_never_activate = always_cheap is not None and price <= always_cheap
            else:
                is_within_threshold = threshold is not None and price <= threshold
                is_always_activate = always_cheap is not None and price <= always_cheap
                is_never_activate = always_expensive is not None and price >= always_expensive

            is_active = (
                (is_always_activate or activated_count > 0 or is_within_threshold)
                and not is_never_activate
            )
            status = "active" if is_active else "standby"

            entries.append({
                "price": round(price, 3),
                "time": start.isoformat(),
                "status": status,
            })

            if is_active:
                activated_count -= 1

        except (ValueError, TypeError, KeyError) as e:
            _LOGGER.warning("Error processing slot: %s", e)
            continue

    return entries, activated_count


def _activate_cheapest_in_group(
    schedule: list[dict],
    indices: list[int],
    min_slots: int,
    price_similarity_pct: float | None,
    always_cheap: float | None,
    always_expensive: float | None,
    inverted: bool,
) -> None:
    """Activate the cheapest (or most expensive) slots within a group.

    Operates on a subset of schedule entries identified by their indices.
    Modifies the schedule in-place.
    """
    eligible = [(i, schedule[i]) for i in indices if schedule[i]["status"] != "excluded"]
    if not eligible:
        return

    # Sort by price (cheapest first for normal, most expensive first for inverted)
    eligible.sort(key=lambda x: x[1]["price"], reverse=inverted)

    # Compute similarity threshold for this group
    sorted_for_threshold = [{"value": s["price"]} for _, s in eligible]
    threshold = _compute_similarity_threshold(sorted_for_threshold, price_similarity_pct, inverted)

    quota = min_slots
    for idx, entry in eligible:
        price = entry["price"]

        if inverted:
            is_within_threshold = threshold is not None and price >= threshold
            is_always_activate = always_expensive is not None and price >= always_expensive
            is_never_activate = always_cheap is not None and price <= always_cheap
        else:
            is_within_threshold = threshold is not None and price <= threshold
            is_always_activate = always_cheap is not None and price <= always_cheap
            is_never_activate = always_expensive is not None and price >= always_expensive

        is_active = (
            (is_always_activate or quota > 0 or is_within_threshold)
            and not is_never_activate
        )

        if is_active:
            schedule[idx]["status"] = "active"
            quota -= 1


# ---------------------------------------------------------------------------
# Block utilities
# ---------------------------------------------------------------------------

def _find_active_blocks(schedule: list[dict]) -> list[tuple[int, int]]:
    """Find all contiguous blocks of active slots.

    Returns:
        List of (start_index, length) tuples for each contiguous active block.
    """
    blocks = []
    i = 0
    while i < len(schedule):
        if schedule[i].get("status") == "active":
            start = i
            while i < len(schedule) and schedule[i].get("status") == "active":
                i += 1
            blocks.append((start, i - start))
        else:
            i += 1
    return blocks


def _find_consecutive_candidates(
    schedule: list[dict],
    window_size: int,
    always_expensive: float | None,
    always_cheap: float | None,
    inverted: bool,
    *,
    start_idx: int = 0,
    end_idx: int | None = None,
) -> list[tuple[int, int, float]]:
    """Find and rank candidate consecutive windows for activation.

    Args:
        schedule: The full schedule list.
        window_size: Number of consecutive slots required.
        always_expensive: Price ceiling (normal mode).
        always_cheap: Price floor (inverted mode).
        inverted: Whether using inverted selection mode.
        start_idx: Only consider windows starting at or after this index.
        end_idx: Windows must fit entirely before this index (exclusive).

    Returns:
        List of (start_index, new_activations_needed, total_price) tuples,
        sorted by preference (fewest new activations first, then by price).
    """
    if end_idx is None:
        end_idx = len(schedule)
    candidates = []
    for i in range(max(start_idx, 0), min(end_idx, len(schedule)) - window_size + 1):
        window = schedule[i:i + window_size]

        # Skip windows containing excluded slots
        if any(s.get("status") == "excluded" for s in window):
            continue

        # Check price constraints for each slot in the window
        valid = True
        for s in window:
            price = s.get("price", 0)
            if not inverted and always_expensive is not None and price >= always_expensive:
                valid = False
                break
            if inverted and always_cheap is not None and price <= always_cheap:
                valid = False
                break
        if not valid:
            continue

        active_count = sum(1 for s in window if s.get("status") == "active")
        new_needed = window_size - active_count
        total_price = sum(s.get("price", 0) for s in window)
        candidates.append((i, new_needed, total_price))

    # Sort: fewest new activations first, then by price
    if inverted:
        candidates.sort(key=lambda x: (x[1], -x[2]))
    else:
        candidates.sort(key=lambda x: (x[1], x[2]))

    return candidates


# ---------------------------------------------------------------------------
# Period partitioning (Lowest Price strategy)
# ---------------------------------------------------------------------------

def _partition_into_periods(
    schedule: list[dict],
    period_from: str,
    period_to: str,
    now: datetime,
) -> list[list[int]]:
    """Group schedule indices into fixed time periods.

    Each period runs from period_from to period_to (clock times). Slots
    outside any period are not included in any group (they stay standby).

    Supports cross-midnight periods (e.g., "22:00" to "06:00").

    Returns:
        List of index groups, one per period, sorted by period start date.
    """
    from_time = _parse_time(period_from)
    to_time = _parse_time(period_to)
    cross_midnight = to_time <= from_time

    period_groups: dict[object, list[int]] = {}
    for i, s in enumerate(schedule):
        slot_time = datetime.fromisoformat(s["time"]).astimezone(now.tzinfo)
        slot_tod = slot_time.time()

        if cross_midnight:
            # Period crosses midnight (e.g., 22:00 → 06:00)
            # Slots at or after from_time: belong to period starting today
            # Slots before to_time: belong to period starting yesterday
            if slot_tod >= from_time:
                period_date = slot_time.date()
            elif slot_tod < to_time:
                period_date = slot_time.date() - timedelta(days=1)
            else:
                continue  # Outside any period
        else:
            # Normal period (e.g., 06:00 → 18:00)
            if from_time <= slot_tod < to_time:
                period_date = slot_time.date()
            else:
                continue  # Outside any period

        if period_date not in period_groups:
            period_groups[period_date] = []
        period_groups[period_date].append(i)

    return [period_groups[d] for d in sorted(period_groups.keys())]


def active_hours_in_current_period(
    schedule: list[dict],
    period_from: str,
    period_to: str,
    now: datetime,
) -> float:
    """Count active hours in the period that contains ``now``.

    Uses the same period logic as the scheduling algorithm. If ``now``
    falls outside all periods (e.g. in a gap between two periods),
    returns the active count from the most recent past period, or the
    next upcoming one if no past period exists.

    Each schedule slot is 15 minutes, so 4 active slots = 1 hour.
    """
    periods = _partition_into_periods(schedule, period_from, period_to, now)

    if not periods:
        # No periods at all (unlikely, but safe fallback)
        active = sum(1 for s in schedule if s.get("status") == "active")
        return round(active / 4.0, 1)

    # Try to find the period whose time span covers `now`
    for indices in periods:
        for i in indices:
            slot_time = datetime.fromisoformat(schedule[i]["time"]).astimezone(
                now.tzinfo
            )
            if slot_time <= now < slot_time + timedelta(minutes=15):
                active = sum(
                    1
                    for idx in indices
                    if schedule[idx].get("status") == "active"
                )
                return round(active / 4.0, 1)

    # `now` is between periods — pick the closest one
    # (most recent past period, or the first upcoming one)
    best_indices = periods[0]
    best_distance = None
    for indices in periods:
        first_time = datetime.fromisoformat(
            schedule[indices[0]]["time"]
        ).astimezone(now.tzinfo)
        last_time = datetime.fromisoformat(
            schedule[indices[-1]]["time"]
        ).astimezone(now.tzinfo)
        dist = min(abs((first_time - now).total_seconds()),
                   abs((last_time - now).total_seconds()))
        if best_distance is None or dist < best_distance:
            best_distance = dist
            best_indices = indices

    active = sum(
        1 for idx in best_indices if schedule[idx].get("status") == "active"
    )
    return round(active / 4.0, 1)


# ---------------------------------------------------------------------------
# Consecutive enforcement (shared by both strategies)
# ---------------------------------------------------------------------------

def _enforce_min_consecutive(
    schedule: list[dict],
    min_consecutive_hours: float,
    min_hours: float,
    always_expensive: float | None,
    *,
    now: datetime,
    inverted: bool = False,
    always_cheap: float | None = None,
) -> list[dict]:
    """Ensure all future active blocks are at least min_consecutive_hours long.

    Consolidates short future blocks by deactivating their slots and
    re-allocating them into the best consecutive future windows.

    In normal mode: never activates slots at or above always_expensive.
    In inverted mode: never activates slots at or below always_cheap.

    Args:
        schedule: Time-sorted schedule (modified in-place).
        min_consecutive_hours: Minimum consecutive hours per active block.
        min_hours: Overall minimum hours (caps the consecutive requirement).
        always_expensive: Price threshold; in normal mode, slots at/above are never activated.
        now: Current datetime (timezone-aware). Only future slots are consolidated.
        inverted: If True, use inverted selection logic.
        always_cheap: Price threshold; in inverted mode, slots at/below are never activated.

    Returns:
        The modified schedule.
    """
    effective_hours = min(min_consecutive_hours, min_hours)
    if effective_hours < min_consecutive_hours:
        _LOGGER.warning(
            "min_consecutive_hours (%.1f) capped to min_hours (%.1f)",
            min_consecutive_hours, min_hours,
        )
    effective_slots = int(effective_hours * 4)
    if effective_slots <= 0:
        return schedule

    _LOGGER.debug(
        "Enforcing minimum consecutive constraint: %d slots (%.1f hours)",
        effective_slots, effective_hours,
    )

    # Find the future slot range
    future_start_idx = 0
    found_future = False
    for i, s in enumerate(schedule):
        slot_time = datetime.fromisoformat(s["time"]).astimezone(now.tzinfo)
        if not found_future and slot_time >= now:
            future_start_idx = i
            found_future = True
            break
    if not found_future:
        return schedule

    # Protect in-progress blocks: count trailing active slots before now
    trailing_past_active = 0
    idx = future_start_idx - 1
    while idx >= 0:
        slot = schedule[idx]
        slot_status = slot.get("status")
        if slot_status == "excluded":
            break
        if slot_status == "active":
            trailing_past_active += 1
            idx -= 1
        else:
            break

    _LOGGER.debug(
        "In-progress block detection: trailing_past_active=%d, effective_slots=%d",
        trailing_past_active, effective_slots,
    )

    # Extend in-progress block into future if needed
    if 0 < trailing_past_active < effective_slots:
        needed_extension = effective_slots - trailing_past_active
        extended = 0
        for i in range(
            future_start_idx,
            min(future_start_idx + needed_extension, len(schedule)),
        ):
            slot = schedule[i]
            if slot.get("status") == "excluded":
                break
            price = slot.get("price", 0)
            if not inverted and always_expensive is not None and price >= always_expensive:
                break
            if inverted and always_cheap is not None and price <= always_cheap:
                break
            if slot.get("status") != "active":
                slot["status"] = "active"
                extended += 1
        if extended > 0:
            _LOGGER.debug(
                "Protected in-progress block: extended %d past active slots "
                "with %d future slots to meet min consecutive",
                trailing_past_active, extended,
            )

    # Find short blocks that are entirely in the future
    blocks = _find_active_blocks(schedule)
    short_blocks = [
        (start, length) for start, length in blocks
        if length < effective_slots
        and start >= future_start_idx
        and not (
            start == future_start_idx
            and trailing_past_active > 0
            and trailing_past_active + length >= effective_slots
        )
    ]

    if not short_blocks:
        return schedule

    # Deactivate all slots in short future blocks to free them for consolidation
    freed = 0
    for block_start, block_len in short_blocks:
        for i in range(block_start, block_start + block_len):
            if schedule[i].get("status") == "active":
                schedule[i]["status"] = "standby"
                freed += 1

    _LOGGER.debug(
        "Deactivated %d future slots from %d short blocks for consolidation",
        freed, len(short_blocks),
    )

    # Find candidate consecutive windows
    candidates = _find_consecutive_candidates(
        schedule, effective_slots, always_expensive, always_cheap, inverted,
        start_idx=future_start_idx, end_idx=len(schedule),
    )

    activated_indices: set[int] = set()
    slots_activated = 0

    for win_start, _new_needed, _score in candidates:
        if freed <= 0:
            break
        win_range = set(range(win_start, win_start + effective_slots))
        if win_range & activated_indices:
            continue  # Skip overlapping windows

        # Recount new_needed (may have changed from earlier window activations)
        new_needed = sum(
            1 for i in range(win_start, win_start + effective_slots)
            if schedule[i].get("status") == "standby"
        )
        # Allow first window even when new_needed > freed to ensure at least
        # one consecutive block is placed.
        if slots_activated > 0 and new_needed > freed:
            continue

        for i in range(win_start, win_start + effective_slots):
            if schedule[i].get("status") == "standby":
                schedule[i]["status"] = "active"
                freed -= 1
                slots_activated += 1
        activated_indices |= win_range

    if freed > 0:
        _LOGGER.debug(
            "%d freed slots could not be placed in consecutive blocks", freed,
        )

    total_active = sum(1 for s in schedule if s.get("status") == "active")
    _LOGGER.info(
        "After consecutive enforcement: %d total active slots (%.1f hours), "
        "consolidated %d short blocks",
        total_active, total_active / 4.0, len(short_blocks),
    )

    return schedule


# ---------------------------------------------------------------------------
# Strategy: Lowest Price
# ---------------------------------------------------------------------------

def build_lowest_price_schedule(
    raw_today: list[dict],
    raw_tomorrow: list[dict],
    min_hours: float,
    now: datetime,
    *,
    period_from: str = "00:00",
    period_to: str = "00:00",
    always_cheap: float | None = None,
    always_expensive: float | None = None,
    price_similarity_pct: float | None = None,
    min_consecutive_hours: float | None = None,
    selection_mode: str = "cheapest",
    exclude_from: str | None = None,
    exclude_until: str | None = None,
) -> list[dict]:
    """Build a schedule using the Lowest Price strategy.

    Activates the cheapest (or most expensive) hours within fixed time periods.
    Each period gets its own independent activation quota.

    Args:
        raw_today: Nordpool raw_today attribute (list of dicts with start, end, value).
        raw_tomorrow: Nordpool raw_tomorrow attribute (may be empty).
        min_hours: Hours to activate per period.
        now: Current datetime (timezone-aware).
        period_from: Period start time ("HH:MM"). Default "00:00".
        period_to: Period end time ("HH:MM"). Default "00:00".
            When period_from == period_to, each calendar day is one period.
        always_cheap: Always activate at or below this price. None = disabled.
        always_expensive: Never activate at or above this price. None = disabled.
        price_similarity_pct: Expand selection to similarly priced slots. None = disabled.
        min_consecutive_hours: Minimum consecutive hours per active block. None = disabled.
        selection_mode: "cheapest" or "most_expensive".
        exclude_from: Excluded time range start ("HH:MM:SS"). None = disabled.
        exclude_until: Excluded time range end ("HH:MM:SS"). None = disabled.

    Returns:
        List of schedule dicts: [{"price": float, "time": str, "status": str}, ...]
    """
    inverted = selection_mode == "most_expensive"
    min_slots = int(min_hours * 4)
    full_day = period_from == period_to
    schedule: list[dict] = []

    _LOGGER.debug(
        "Lowest Price strategy: min_hours=%.1f (%d slots), period=%s→%s, "
        "full_day=%s, inverted=%s",
        min_hours, min_slots, period_from, period_to, full_day, inverted,
    )

    if full_day:
        # Per-day scheduling: each calendar day is an independent period.
        # Use _process_day_slots() directly for compatibility with existing behavior.
        sorted_today = sorted(raw_today, key=lambda x: x.get("value", 999), reverse=inverted)
        today_threshold = _compute_similarity_threshold(sorted_today, price_similarity_pct, inverted)
        today_entries, _ = _process_day_slots(
            sorted_today, min_slots, today_threshold,
            always_cheap, always_expensive, now, inverted,
            exclude_from, exclude_until,
        )
        schedule.extend(today_entries)

        if raw_tomorrow:
            sorted_tomorrow = sorted(raw_tomorrow, key=lambda x: x.get("value", 999), reverse=inverted)
            tomorrow_threshold = _compute_similarity_threshold(sorted_tomorrow, price_similarity_pct, inverted)
            tomorrow_entries, _ = _process_day_slots(
                sorted_tomorrow, min_slots, tomorrow_threshold,
                always_cheap, always_expensive, now, inverted,
                exclude_from, exclude_until,
            )
            schedule.extend(tomorrow_entries)
    else:
        # Custom period scheduling: partition slots into periods and activate per-period.
        all_raw = list(raw_today) + list(raw_tomorrow or [])
        schedule = _build_base_schedule(all_raw, now, exclude_from, exclude_until)

        periods = _partition_into_periods(schedule, period_from, period_to, now)
        for period_indices in periods:
            _activate_cheapest_in_group(
                schedule, period_indices, min_slots,
                price_similarity_pct, always_cheap, always_expensive, inverted,
            )

    # Sort by time
    schedule.sort(key=lambda x: x["time"])

    # Apply minimum consecutive hours constraint if enabled
    if min_consecutive_hours is not None and min_consecutive_hours > 0:
        schedule = _enforce_min_consecutive(
            schedule, min_consecutive_hours, min_hours, always_expensive,
            now=now, inverted=inverted, always_cheap=always_cheap,
        )

    # Log statistics
    active_count = sum(1 for s in schedule if s.get("status") == "active")
    _LOGGER.debug(
        "Lowest Price schedule: %d active slots (%.1f hours) out of %d total",
        active_count, active_count / 4.0, len(schedule),
    )

    return schedule


# ---------------------------------------------------------------------------
# Strategy: Minimum Runtime
# ---------------------------------------------------------------------------

def build_minimum_runtime_schedule(
    raw_today: list[dict],
    raw_tomorrow: list[dict],
    min_hours_on: float,
    now: datetime,
    *,
    max_hours_off: float = 24.0,
    last_on_time: datetime | None = None,
    min_consecutive_hours: float | None = None,
    always_cheap: float | None = None,
    always_expensive: float | None = None,
    selection_mode: str = "cheapest",
    exclude_from: str | None = None,
    exclude_until: str | None = None,
) -> list[dict]:
    """Build a schedule using the Minimum Runtime strategy.

    Ensures the device runs for at least min_hours_on within each rolling
    window of (max_hours_off + min_hours_on) hours. Active slots are spread
    across the cheapest available times rather than forced into one block.

    Iteratively fills rolling windows across the schedule horizon.

    Args:
        raw_today: Nordpool raw_today attribute.
        raw_tomorrow: Nordpool raw_tomorrow attribute (may be empty).
        min_hours_on: Minimum total hours to activate per rolling window.
        now: Current datetime (timezone-aware).
        max_hours_off: Maximum hours the device can stay off.
        last_on_time: When the device was last active.
            None means first run — full window available.
        min_consecutive_hours: Minimum consecutive hours per active block.
            None = disabled (individual 15-min slots allowed).
        always_cheap: Always activate at or below this price. None = disabled.
        always_expensive: Never activate at or above this price. None = disabled.
        selection_mode: "cheapest" or "most_expensive".
        exclude_from: Excluded time range start ("HH:MM:SS"). None = disabled.
        exclude_until: Excluded time range end ("HH:MM:SS"). None = disabled.

    Returns:
        List of schedule dicts: [{"price": float, "time": str, "status": str}, ...]
    """
    inverted = selection_mode == "most_expensive"
    required_slots = int(min_hours_on * 4)

    # Build base schedule (all standby/excluded)
    all_raw = list(raw_today) + list(raw_tomorrow or [])
    schedule = _build_base_schedule(all_raw, now, exclude_from, exclude_until)

    if not schedule or required_slots <= 0:
        return schedule

    _LOGGER.debug(
        "Minimum Runtime strategy: min_hours_on=%.1f (%d slots), "
        "max_hours_off=%.1f, last_on_time=%s, inverted=%s",
        min_hours_on, required_slots, max_hours_off,
        last_on_time.isoformat() if last_on_time else "None", inverted,
    )

    # Find the first future slot index
    future_start_idx = len(schedule)
    for i, s in enumerate(schedule):
        slot_time = datetime.fromisoformat(s["time"]).astimezone(now.tzinfo)
        if slot_time >= now:
            future_start_idx = i
            break

    # Compute the first deadline (device must be on by this time)
    if last_on_time is None:
        next_deadline = now + timedelta(hours=max_hours_off)
        _LOGGER.info(
            "No last_on_time — assuming recently on, deadline in %.1f hours",
            max_hours_off,
        )
    else:
        next_deadline = last_on_time + timedelta(hours=max_hours_off)
        if next_deadline < now:
            next_deadline = now  # Overdue — schedule immediately
            _LOGGER.warning("Deadline already passed — scheduling immediate activation")
        else:
            _LOGGER.debug("Next deadline: %s", next_deadline.isoformat())

    # Iteratively fill rolling windows
    search_from = future_start_idx
    windows_filled = 0

    while search_from < len(schedule):
        # Window extends from search_from until deadline + min_hours_on
        window_end_time = next_deadline + timedelta(hours=min_hours_on)

        # Find window end index
        window_end_idx = len(schedule)
        for i in range(search_from, len(schedule)):
            slot_time = datetime.fromisoformat(schedule[i]["time"]).astimezone(now.tzinfo)
            if slot_time >= window_end_time:
                window_end_idx = i
                break

        if search_from >= window_end_idx:
            break  # No slots in this window

        # Collect eligible standby slots in this window
        candidates = []
        for i in range(search_from, window_end_idx):
            s = schedule[i]
            if s["status"] != "standby":
                continue
            price = s["price"]
            if not inverted and always_expensive is not None and price >= always_expensive:
                continue
            if inverted and always_cheap is not None and price <= always_cheap:
                continue
            candidates.append((i, price))

        # Sort by price (cheapest first, or most expensive first if inverted)
        candidates.sort(key=lambda x: x[1], reverse=inverted)

        # Activate the best slots up to the required count
        last_activated_time = None
        activated = 0
        for idx, _ in candidates[:required_slots]:
            schedule[idx]["status"] = "active"
            activated += 1
            slot_time = datetime.fromisoformat(schedule[idx]["time"]).astimezone(
                now.tzinfo
            )
            if last_activated_time is None or slot_time > last_activated_time:
                last_activated_time = slot_time

        if activated == 0:
            # No eligible slots — emergency: activate from search_from
            _LOGGER.warning(
                "No eligible slots in window ending %s — emergency activation",
                window_end_time.isoformat(),
            )
            for i in range(search_from, min(search_from + required_slots, len(schedule))):
                if schedule[i]["status"] != "excluded":
                    schedule[i]["status"] = "active"
                    activated += 1
                    slot_time = datetime.fromisoformat(
                        schedule[i]["time"]
                    ).astimezone(now.tzinfo)
                    if last_activated_time is None or slot_time > last_activated_time:
                        last_activated_time = slot_time
            if activated == 0:
                break

        windows_filled += 1

        # Next deadline: from end of last activated slot + max_hours_off
        next_deadline = (
            last_activated_time + timedelta(minutes=15) + timedelta(hours=max_hours_off)
        )
        search_from = window_end_idx

    # Apply always_cheap / always_expensive bonus activations
    for s in schedule:
        if s["status"] != "standby":
            continue
        price = s["price"]
        if not inverted and always_cheap is not None and price <= always_cheap:
            s["status"] = "active"
        elif inverted and always_expensive is not None and price >= always_expensive:
            s["status"] = "active"

    # Enforce minimum consecutive hours if set
    if min_consecutive_hours:
        schedule = _enforce_min_consecutive(
            schedule, min_consecutive_hours, min_hours_on,
            always_expensive, now=now, inverted=inverted,
            always_cheap=always_cheap,
        )

    active_count = sum(1 for s in schedule if s.get("status") == "active")
    _LOGGER.debug(
        "Minimum Runtime schedule: %d windows filled, %d active slots "
        "(%.1f hours) out of %d total",
        windows_filled, active_count, active_count / 4.0, len(schedule),
    )

    return schedule


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def build_schedule(
    raw_today: list[dict],
    raw_tomorrow: list[dict],
    min_hours: float,
    now: datetime,
    *,
    strategy: str = "lowest_price",
    # Lowest Price specific
    period_from: str = "00:00",
    period_to: str = "00:00",
    min_consecutive_hours: float | None = None,
    # Max Off Time specific
    max_hours_off: float | None = None,
    last_on_time: datetime | None = None,
    # Shared
    always_cheap: float | None = None,
    always_expensive: float | None = None,
    price_similarity_pct: float | None = None,
    selection_mode: str = "cheapest",
    exclude_from: str | None = None,
    exclude_until: str | None = None,
) -> list[dict]:
    """Build a schedule by dispatching to the appropriate strategy.

    Args:
        raw_today: Nordpool raw_today attribute (list of dicts with start, end, value).
        raw_tomorrow: Nordpool raw_tomorrow attribute (may be empty).
        min_hours: In Lowest Price: hours to activate per period.
                   In Minimum Runtime: minimum hours to run per window.
        now: Current datetime (timezone-aware).
        strategy: "lowest_price" or "minimum_runtime".
        period_from: (Lowest Price) Period start time. Default "00:00".
        period_to: (Lowest Price) Period end time. Default "00:00".
        min_consecutive_hours: Min consecutive hours per block. None = disabled.
        max_hours_off: (Minimum Runtime) Max hours the device can stay off.
        last_on_time: (Minimum Runtime) When device was last active.
        always_cheap: Always activate at or below this price. None = disabled.
        always_expensive: Never activate at or above this price. None = disabled.
        price_similarity_pct: (Lowest Price) Expand to similarly priced slots. None = disabled.
        selection_mode: "cheapest" or "most_expensive".
        exclude_from: Excluded time range start. None = disabled.
        exclude_until: Excluded time range end. None = disabled.

    Returns:
        List of schedule dicts: [{"price": float, "time": str, "status": str}, ...]
    """
    if strategy == "minimum_runtime":
        return build_minimum_runtime_schedule(
            raw_today=raw_today,
            raw_tomorrow=raw_tomorrow,
            min_hours_on=min_hours,
            now=now,
            max_hours_off=max_hours_off or 24.0,
            last_on_time=last_on_time,
            min_consecutive_hours=min_consecutive_hours,
            always_cheap=always_cheap,
            always_expensive=always_expensive,
            selection_mode=selection_mode,
            exclude_from=exclude_from,
            exclude_until=exclude_until,
        )
    return build_lowest_price_schedule(
        raw_today=raw_today,
        raw_tomorrow=raw_tomorrow,
        min_hours=min_hours,
        now=now,
        period_from=period_from,
        period_to=period_to,
        always_cheap=always_cheap,
        always_expensive=always_expensive,
        price_similarity_pct=price_similarity_pct,
        min_consecutive_hours=min_consecutive_hours,
        selection_mode=selection_mode,
        exclude_from=exclude_from,
        exclude_until=exclude_until,
    )


# ---------------------------------------------------------------------------
# State queries
# ---------------------------------------------------------------------------

def find_current_slot(schedule: list[dict], now: datetime) -> dict | None:
    """Find the schedule slot that contains the current time.

    Args:
        schedule: The full schedule list.
        now: Current datetime (timezone-aware).

    Returns:
        The matching slot dict, or None if no slot covers the current time.
    """
    for i, s in enumerate(schedule):
        slot_time = datetime.fromisoformat(s["time"]).astimezone(now.tzinfo)

        # Determine slot end time
        if i + 1 < len(schedule):
            next_slot_time = datetime.fromisoformat(schedule[i + 1]["time"]).astimezone(now.tzinfo)
        else:
            if i > 0:
                prev_slot_time = datetime.fromisoformat(schedule[i - 1]["time"]).astimezone(now.tzinfo)
                slot_duration = slot_time - prev_slot_time
            else:
                slot_duration = timedelta(minutes=15)
            next_slot_time = slot_time + slot_duration

        if slot_time <= now < next_slot_time:
            return s

    return None


def find_next_change(
    schedule: list[dict],
    current_slot: dict | None,
    now: datetime,
) -> str | None:
    """Find the ISO timestamp of the next state transition.

    Args:
        schedule: The full schedule list.
        current_slot: The current slot (from find_current_slot), or None.
        now: Current datetime (timezone-aware).

    Returns:
        ISO timestamp of the next state change, or None.
    """
    if current_slot is None:
        return None

    current_state = current_slot.get("status")
    future_slots = [
        s for s in schedule
        if datetime.fromisoformat(s["time"]).astimezone(now.tzinfo) > now
    ]

    for slot in future_slots:
        if slot.get("status") != current_state:
            return slot["time"]

    return None


# ---------------------------------------------------------------------------
# Committed block protection
# ---------------------------------------------------------------------------

def apply_committed_block_protection(
    current_state: str,
    active_block_start: datetime | None,
    now: datetime,
    effective_consecutive_hours: float,
    current_price: float | None,
    always_expensive: float | None,
    always_cheap: float | None,
    inverted: bool,
    current_slot: dict | None,
) -> tuple[str, datetime | None]:
    """Ensure an appliance stays active for the full committed duration.

    Once an appliance turns on, this function guarantees it remains active for
    the committed duration to prevent 15-minute schedule recalculations from
    fragmenting consecutive blocks.

    Args:
        current_state: Current slot state ("active", "standby", "excluded").
        active_block_start: When the current committed block started, or None.
        now: Current datetime (timezone-aware).
        effective_consecutive_hours: The committed on-duration.
            Pass 0 if feature is disabled.
        current_price: Price of the current slot.
        always_expensive: Always-expensive price threshold (cheapest mode).
        always_cheap: Always-cheap price threshold (most_expensive mode).
        inverted: True when selection_mode is "most_expensive".
        current_slot: Current schedule slot dict (modified in-place if
            state is overridden).

    Returns:
        (new_current_state, new_active_block_start) tuple.
    """
    if effective_consecutive_hours <= 0:
        return current_state, None

    if current_state == "active":
        if active_block_start is None:
            # New committed block starts now
            active_block_start = now
            _LOGGER.debug(
                "Committed block started at %s (duration: %.1fh)",
                now.isoformat(),
                effective_consecutive_hours,
            )
        return current_state, active_block_start

    # State is not active — check if we're within a committed block
    if active_block_start is None:
        return current_state, None

    # Excluded slots always end a committed block immediately
    if current_state == "excluded":
        _LOGGER.info(
            "Committed block ended: slot is excluded (started %s)",
            active_block_start.isoformat(),
        )
        return current_state, None

    committed_end = active_block_start + timedelta(
        hours=effective_consecutive_hours
    )

    if now >= committed_end:
        # Committed block has completed its full duration
        _LOGGER.debug(
            "Committed block completed (started %s)",
            active_block_start.isoformat(),
        )
        return current_state, None

    # Still within committed duration — check price constraints
    price_blocked = False
    if (
        not inverted
        and always_expensive is not None
        and current_price is not None
        and current_price >= always_expensive
    ):
        price_blocked = True
    elif (
        inverted
        and always_cheap is not None
        and current_price is not None
        and current_price <= always_cheap
    ):
        price_blocked = True

    if price_blocked:
        _LOGGER.info(
            "Committed block ended early: price constraint at %.3f (started %s)",
            current_price,
            active_block_start.isoformat(),
        )
        return current_state, None

    # Override: keep active for the remaining committed duration
    remaining_min = (committed_end - now).total_seconds() / 60
    _LOGGER.info(
        "Committed block protection: keeping active (%.0f min remaining, started %s)",
        remaining_min,
        active_block_start.isoformat(),
    )
    if current_slot is not None:
        current_slot["status"] = "active"
    return "active", active_block_start
