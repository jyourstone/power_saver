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
    try:
        parts = time_str.split(":")
        if len(parts) not in (2, 3):
            raise ValueError(f"Expected HH:MM or HH:MM:SS, got {time_str!r}")
        return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
    except (ValueError, IndexError) as exc:
        raise ValueError(f"Invalid time string: {time_str!r}") from exc


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
    except (ValueError, IndexError) as exc:
        _LOGGER.warning(
            "Invalid exclusion time range '%s' - '%s': %s",
            exclude_from, exclude_until, exc,
        )
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
    try:
        from_time = _parse_time(period_from)
        to_time = _parse_time(period_to)
    except ValueError as exc:
        raise ValueError(
            f"Invalid period time: {period_from}/{period_to}: {exc}"
        ) from exc
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
        return active / 4.0

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
                return active / 4.0

    # `now` is between periods — prefer the most recent past period,
    # otherwise fall back to the earliest upcoming period.
    best_past_indices = None
    best_past_end = None
    best_future_indices = None
    best_future_start = None
    for indices in periods:
        first_time = datetime.fromisoformat(
            schedule[indices[0]]["time"]
        ).astimezone(now.tzinfo)
        last_time = datetime.fromisoformat(
            schedule[indices[-1]]["time"]
        ).astimezone(now.tzinfo)
        if last_time <= now:
            if best_past_end is None or last_time > best_past_end:
                best_past_end = last_time
                best_past_indices = indices
        else:
            if best_future_start is None or first_time < best_future_start:
                best_future_start = first_time
                best_future_indices = indices
    best_indices = best_past_indices if best_past_indices is not None else (
        best_future_indices if best_future_indices is not None else periods[0]
    )

    active = sum(
        1 for idx in best_indices if schedule[idx].get("status") == "active"
    )
    return active / 4.0


# ---------------------------------------------------------------------------
# Consecutive enforcement (shared by both strategies)
# ---------------------------------------------------------------------------

def _can_activate(
    price: float,
    inverted: bool,
    always_cheap: float | None,
    always_expensive: float | None,
) -> bool:
    """Whether a slot at this price may be activated at all.

    Normal mode never activates at or above always_expensive; inverted mode
    never activates at or below always_cheap.
    """
    if inverted:
        return always_cheap is None or price > always_cheap
    return always_expensive is None or price < always_expensive


def _place_in_runs(
    schedule: list[dict],
    count: int,
    run_len: int,
    placeable: set[int],
    inverted: bool,
    *,
    lo: int = 0,
    hi: int | None = None,
    must_idx: int | None = None,
) -> list[int] | None:
    """Pick ``count`` slots from ``placeable`` within schedule[lo:hi] at the
    lowest total price (highest if inverted) so every run of active slots is
    at least ``run_len`` long. A run that touches an already-active slot
    (including one just before ``lo``) counts as long enough, since those
    slots are given.

    Takes exactly ``count`` slots if possible, else the smallest overshoot,
    else the largest under-run. ``must_idx`` is a slot that has to be picked.

    Returns the picked indices (not yet activated), or None if no valid
    placement exists (only possible with ``must_idx``).
    """
    # Dynamic programming over the slots with state (slots picked, current
    # run length capped at run_len).
    # ponytail: O(slots * count * run_len) states — ~20 ms worst measured,
    # with long consecutive minimums (large run_len × count); prune if it lags.
    hi = len(schedule) if hi is None else hi
    start_run = run_len if lo > 0 and schedule[lo - 1].get("status") == "active" else 0

    def solve(max_placed: int) -> list[dict]:
        # layers[k][(placed, run)] = (cost, previous state, slot lo+k-1 picked)
        layers: list[dict] = [{(0, start_run): (0.0, None, False)}]
        for i in range(lo, hi):
            kept = schedule[i].get("status") == "active"
            price = schedule[i].get("price", 0)
            slot_cost = -price if inverted else price
            nxt: dict = {}
            for (placed, run), (cost, _, _) in layers[-1].items():
                options = []
                if kept:
                    options.append(((placed, run_len), cost, False))
                else:
                    # A run may only end once it is long enough
                    if run in (0, run_len) and i != must_idx:
                        options.append(((placed, 0), cost, False))
                    if i in placeable and placed < max_placed:
                        options.append(
                            ((placed + 1, min(run + 1, run_len)), cost + slot_cost, True)
                        )
                for state, new_cost, is_new in options:
                    if state not in nxt or new_cost < nxt[state][0]:
                        nxt[state] = (new_cost, (placed, run), is_new)
            layers.append(nxt)
        return layers

    # Overshoot states double the work and are rarely needed, so only add
    # them when the exact count is impossible.
    for max_placed in (count, count + run_len - 1):
        layers = solve(max_placed)
        final = {s: v[0] for s, v in layers[-1].items() if s[1] in (0, run_len)}
        if any(placed == count for placed, _ in final):
            break
    if not final:
        return None
    # Exact count, else the smallest overshoot, else the largest under-run.
    state = min(final, key=lambda s: (s[0] < count, abs(s[0] - count), final[s], s[1]))
    picked = []
    for k in range(len(layers) - 1, 0, -1):
        _, state_before, is_new = layers[k][state]
        if is_new:
            picked.append(lo + k - 1)
        state = state_before
    return picked


def _enforce_min_consecutive(
    schedule: list[dict],
    min_consecutive_hours: float,
    min_hours: float,
    always_expensive: float | None,
    *,
    now: datetime,
    inverted: bool = False,
    always_cheap: float | None = None,
    start_idx: int = 0,
    keep: frozenset[int] = frozenset(),
) -> list[dict]:
    """Ensure all active blocks are at least min_consecutive_hours long.

    Consolidates short blocks by deactivating their slots and re-placing
    them where they cost least (extending long blocks or forming new ones),
    keeping the number of active slots unchanged whenever possible.

    In normal mode: never activates slots at or above always_expensive.
    In inverted mode: never activates slots at or below always_cheap.

    Args:
        schedule: Time-sorted schedule (modified in-place).
        min_consecutive_hours: Minimum consecutive hours per active block.
        min_hours: Overall minimum hours (caps the consecutive requirement).
        always_expensive: Price threshold; in normal mode, slots at/above are never activated.
        now: Current datetime (timezone-aware). Kept for interface compatibility.
        inverted: If True, use inverted selection logic.
        always_cheap: Price threshold; in inverted mode, slots at/below are never activated.
        start_idx: Slots before this index are history: short blocks that end
            before it are left alone and nothing is placed before it.
        keep: Indices that must stay where they are; short blocks containing
            any of them are not moved.

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

    # Find all short blocks
    blocks = _find_active_blocks(schedule)
    short_blocks = [
        (start, length) for start, length in blocks
        if length < effective_slots and start + length > start_idx
        and keep.isdisjoint(range(start, start + length))
    ]

    if not short_blocks:
        return schedule

    # Deactivate all slots in short blocks to free them for consolidation
    freed = 0
    for block_start, block_len in short_blocks:
        for i in range(block_start, block_start + block_len):
            if schedule[i].get("status") == "active":
                schedule[i]["status"] = "standby"
                freed += 1

    _LOGGER.debug(
        "Deactivated %d slots from %d short blocks for consolidation",
        freed, len(short_blocks),
    )

    placeable = {
        i for i in range(start_idx, len(schedule))
        if schedule[i].get("status") == "standby"
        and _can_activate(schedule[i].get("price", 0), inverted, always_cheap, always_expensive)
    }
    # Never None: without must_idx, picking nothing is always valid.
    picked = _place_in_runs(schedule, freed, effective_slots, placeable, inverted)
    for i in picked:
        schedule[i]["status"] = "active"

    if len(picked) != freed:
        _LOGGER.debug(
            "Placed %d slots for %d freed to keep blocks consecutive",
            len(picked), freed,
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
            When period_from == period_to, each period is the 24 hours starting
            at period_from; 00:00 gives calendar days.
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
    # 00:00→00:00 keeps its per-raw-day path (selects on unrounded prices).
    # Any other period, including e.g. 13:15→13:15 (24 h anchored at
    # period_from), goes through the generic period partitioning.
    full_day = _parse_time(period_from) == _parse_time(period_to) == time(0)
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
        # Each period has an independent quota, so consecutive consolidation
        # must stay inside those same bounds (calendar days for 00:00→00:00).
        periods = _partition_into_periods(schedule, period_from, period_to, now)
        for period_indices in periods:
            sub = [schedule[i] for i in period_indices]
            sub = _enforce_min_consecutive(
                sub, min_consecutive_hours, min_hours, always_expensive,
                now=now, inverted=inverted, always_cheap=always_cheap,
            )
            for local_i, global_i in enumerate(period_indices):
                schedule[global_i] = sub[local_i]

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

    # Find the current ongoing slot index (for overdue force-activation)
    current_slot_idx = len(schedule)
    for i, s in enumerate(schedule):
        slot_time = datetime.fromisoformat(s["time"]).astimezone(now.tzinfo)
        slot_end = slot_time + timedelta(minutes=15)
        if slot_end > now:  # This slot hasn't ended yet
            current_slot_idx = i
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

    # When overdue, the current ongoing slot must be activated immediately
    # regardless of price sorting. Track this so the first window honours it.
    overdue = next_deadline <= now

    # Start from the current slot — past slots are already expired and must not
    # consume required_slots quota when the schedule is recomputed mid-day.
    search_from = current_slot_idx
    windows_filled = 0
    run_len = int(min(min_consecutive_hours or 0, min_hours_on) * 4)

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
        candidates = [
            (i, schedule[i]["price"]) for i in range(search_from, window_end_idx)
            if schedule[i]["status"] == "standby"
            and _can_activate(schedule[i]["price"], inverted, always_cheap, always_expensive)
        ]

        # When overdue, force-include the ongoing slot so it's never
        # dropped by price sorting or always_expensive filtering.
        forced_idx = None
        if overdue and current_slot_idx >= search_from and current_slot_idx < window_end_idx:
            csi = current_slot_idx
            if schedule[csi]["status"] == "standby":
                if not any(idx == csi for idx, _ in candidates):
                    candidates.append((csi, schedule[csi]["price"]))
                forced_idx = csi

        # With a consecutive minimum, pick whole blocks inside this window so
        # the next deadline is based on the slots that will actually run.
        picked = None
        if run_len:
            picked = _place_in_runs(
                schedule, required_slots, run_len,
                {idx for idx, _ in candidates}, inverted,
                lo=search_from, hi=window_end_idx, must_idx=forced_idx,
            )

        if picked and len(picked) >= required_slots:
            selected = picked
        else:
            # No room for the full runtime as whole blocks: keep the runtime
            # (scattered) rather than run less than min_hours_on.
            # Sort by price (cheapest first, or most expensive first if inverted)
            candidates.sort(key=lambda x: x[1], reverse=inverted)
            selected = [idx for idx, _ in candidates[:required_slots]]

            # If the forced ongoing slot wasn't selected by price, swap it in
            # for the last (worst-priced) selected slot
            if forced_idx is not None and forced_idx not in selected and selected:
                selected[-1] = forced_idx

        # Activate the selected slots
        last_activated_time = None
        activated = 0

        for idx in selected:
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
        raw_deadline = (
            last_activated_time + timedelta(minutes=15) + timedelta(hours=max_hours_off)
        )
        # Ensure deadline advances past the current window to avoid backward loops
        # when past slots are activated in the locked schedule
        window_end_slot_time = datetime.fromisoformat(
            schedule[min(window_end_idx, len(schedule) - 1)]["time"]
        ).astimezone(now.tzinfo)
        next_deadline = max(raw_deadline, window_end_slot_time)
        search_from = window_end_idx

        # If the next deadline is beyond the schedule data, stop.
        # That window will be handled when the schedule is recomputed
        # with new price data.
        last_slot_end = (
            datetime.fromisoformat(schedule[-1]["time"]).astimezone(now.tzinfo)
            + timedelta(minutes=15)
        )
        if next_deadline > last_slot_end:
            _LOGGER.debug(
                "Next deadline %s is beyond schedule horizon %s — "
                "deferring to next recomputation",
                next_deadline.isoformat(), last_slot_end.isoformat(),
            )
            break

    # Window runtime stays put; the consecutive pass below only consolidates
    # the bonus activations (and never moves a window's slots past its deadline).
    window_slots = frozenset(i for i, s in enumerate(schedule) if s["status"] == "active")

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
            always_cheap=always_cheap, start_idx=current_slot_idx,
            keep=window_slots,
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

def _find_next_active_boundary(
    schedule: list[dict],
    current_slot: dict | None,
    now: datetime,
    target_active: bool,
) -> str | None:
    """Find the next transition into or out of active state."""
    if current_slot is None:
        return None

    previous_active = current_slot.get("status") == "active"

    for slot in schedule:
        try:
            slot_time = datetime.fromisoformat(slot["time"]).astimezone(now.tzinfo)
        except (KeyError, TypeError, ValueError) as exc:
            _LOGGER.warning(
                "Skipping malformed schedule entry while finding active boundary: %s (%s)",
                slot,
                exc,
            )
            continue
        if slot_time <= now:
            continue

        slot_active = slot.get("status") == "active"
        if slot_active != previous_active:
            if slot_active == target_active:
                return slot["time"]
            previous_active = slot_active

    return None


def find_next_active(
    schedule: list[dict],
    current_slot: dict | None,
    now: datetime,
) -> str | None:
    """Find the ISO timestamp of the next transition into active state."""
    return _find_next_active_boundary(schedule, current_slot, now, True)


def find_next_inactive(
    schedule: list[dict],
    current_slot: dict | None,
    now: datetime,
) -> str | None:
    """Find the ISO timestamp of the next transition out of active state."""
    return _find_next_active_boundary(schedule, current_slot, now, False)
