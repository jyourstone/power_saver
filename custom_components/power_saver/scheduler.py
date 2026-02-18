"""Pure scheduling algorithm for the Power Saver integration.

This module contains no Home Assistant dependencies and can be tested independently.
It is a direct port of the AppDaemon PowerSaverManager scheduling logic.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

_LOGGER = logging.getLogger(__name__)


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
    """Compute the price similarity threshold for a day's slots.

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
        "Price similarity threshold: %.3f (anchor: %.3f, pct: %.1f%%, mode: %s)",
        threshold, anchor_price, price_similarity_pct,
        "inverted" if inverted else "normal",
    )
    return threshold


def _parse_time(value: str) -> time:
    """Parse a time string ('HH:MM:SS' or 'HH:MM') into a time object."""
    parts = value.strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    second = int(parts[2]) if len(parts) > 2 else 0
    return time(hour, minute, second)


def _is_excluded(
    slot_start: datetime,
    exclude_from: str | None,
    exclude_until: str | None,
) -> bool:
    """Check if a slot falls within the excluded time range.

    Args:
        slot_start: The start time of the slot (timezone-aware datetime).
        exclude_from: Start of excluded range ("HH:MM:SS" or "HH:MM"), or None.
        exclude_until: End of excluded range ("HH:MM:SS" or "HH:MM"), or None.

    Returns:
        True if the slot should be excluded, False otherwise.
        Returns False if either parameter is None (feature disabled).
    """
    if not exclude_from or not exclude_until:
        return False

    slot_time = slot_start.time()
    start = _parse_time(exclude_from)
    end = _parse_time(exclude_until)

    if start == end:
        # Zero-length range: nothing excluded
        return False

    if start < end:
        # Normal range (e.g., 00:00 to 06:00)
        return start <= slot_time < end
    else:
        # Cross-midnight range (e.g., 22:00 to 06:00)
        return slot_time >= start or slot_time < end


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
    """Process a day's price-sorted slots into schedule entries.

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

            # Check if slot falls in excluded time range
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


def build_schedule(
    raw_today: list[dict],
    raw_tomorrow: list[dict],
    min_hours: float,
    now: datetime,
    *,
    always_cheap: float | None = None,
    always_expensive: float | None = None,
    rolling_window_hours: float = 24.0,
    prev_activity_history: list[str] | None = None,
    price_similarity_pct: float | None = None,
    min_consecutive_hours: float | None = None,
    selection_mode: str = "cheapest",
    exclude_from: str | None = None,
    exclude_until: str | None = None,
) -> list[dict]:
    """Build a schedule from Nordpool price data.

    Activation logic (default 'cheapest' mode):
    - Activate the cheapest slots up to min_hours (converted to 15-min slots)
    - Activate any slots with price <= always_cheap regardless of quota
    - If price_similarity_pct > 0, also activate slots within that percentage
      of the cheapest price (e.g. 20% means slots up to 1.2x the cheapest)
    - Never activate if price >= always_expensive (safety cutoff)
    - If rolling window constraint is enabled, additional slots are activated as needed
    - If min_consecutive_hours is set, short active blocks are extended to meet the minimum

    In 'most_expensive' mode the logic is inverted:
    - Activate the most expensive slots up to min_hours
    - always_expensive forces activation at or above its price
    - always_cheap prevents activation at or below its price
    - price_similarity_pct expands from the most expensive price downward

    Args:
        raw_today: Nordpool raw_today attribute (list of dicts with start, end, value).
        raw_tomorrow: Nordpool raw_tomorrow attribute (may be empty).
        min_hours: Minimum active hours per day.
        now: Current datetime (timezone-aware).
        always_cheap: Price at or below which slots are always active. None = disabled.
            In 'most_expensive' mode: never activate at or below this price.
        always_expensive: Price at or above which slots are never active. None = disabled.
            In 'most_expensive' mode: always activate at or above this price.
        rolling_window_hours: Rolling window size in hours (always >= 1).
        prev_activity_history: List of ISO timestamps of previously active slots.
        price_similarity_pct: Percentage threshold for price similarity. Slots within
            this percentage of the cheapest price are also activated. None = disabled.
            In 'most_expensive' mode: computed from the most expensive price downward.
        min_consecutive_hours: Minimum consecutive active hours per block. Short blocks
            are extended by activating adjacent slots. None = disabled.
        selection_mode: "cheapest" (default) selects the cheapest slots;
            "most_expensive" inverts the logic to select the most expensive slots
            and swaps the roles of always_cheap/always_expensive thresholds.
        exclude_from: Start of excluded time range ("HH:MM:SS"). Slots in this
            range are never activated and marked as "excluded". None = disabled.
        exclude_until: End of excluded time range ("HH:MM:SS"). Both exclude_from
            and exclude_until must be set to enable. Supports cross-midnight
            ranges (e.g., "22:00:00" to "06:00:00"). None = disabled.

    Returns:
        List of schedule dicts: [{"price": float, "time": str, "status": str}, ...]
    """
    if prev_activity_history is None:
        prev_activity_history = []

    inverted = selection_mode == "most_expensive"
    min_slots = int(min_hours * 4)
    schedule: list[dict] = []

    # Rolling window is always enabled; only skip if min_hours is zero
    use_rolling_window = min_hours > 0

    if use_rolling_window:
        _LOGGER.debug(
            "Rolling window mode: base activation for min_slots (%d) + always_cheap (<=%s). "
            "Constraint will ensure %sh in any %sh window.",
            min_slots, always_cheap, min_hours, rolling_window_hours,
        )
    else:
        _LOGGER.debug(
            "Standard mode: activating min_slots (%d) + always_cheap (<=%s)",
            min_slots, always_cheap,
        )

    # Process today's slots (sorted by price)
    sorted_today = sorted(raw_today, key=lambda x: x.get("value", 999), reverse=inverted)
    activated_count = min_slots
    today_threshold = _compute_similarity_threshold(sorted_today, price_similarity_pct, inverted)
    today_entries, activated_count = _process_day_slots(
        sorted_today, activated_count, today_threshold,
        always_cheap, always_expensive, now, inverted,
        exclude_from, exclude_until,
    )
    schedule.extend(today_entries)

    # Process tomorrow's slots if available
    if raw_tomorrow:
        sorted_tomorrow = sorted(raw_tomorrow, key=lambda x: x.get("value", 999), reverse=inverted)
        # In rolling window mode, share quota across both days
        # In standard mode, reset to give each day its own quota
        if not use_rolling_window:
            activated_count = min_slots
        tomorrow_threshold = _compute_similarity_threshold(sorted_tomorrow, price_similarity_pct, inverted)
        tomorrow_entries, activated_count = _process_day_slots(
            sorted_tomorrow, activated_count, tomorrow_threshold,
            always_cheap, always_expensive, now, inverted,
            exclude_from, exclude_until,
        )
        schedule.extend(tomorrow_entries)

    # Sort by time
    schedule.sort(key=lambda x: x["time"])

    # Apply rolling window constraint if enabled
    if use_rolling_window:
        schedule = _apply_rolling_window_constraint(
            schedule, rolling_window_hours, min_hours, now, prev_activity_history,
            inverted=inverted,
        )

    # Apply minimum consecutive hours constraint if enabled
    if min_consecutive_hours is not None and min_consecutive_hours > 0:
        schedule = _enforce_min_consecutive(
            schedule, min_consecutive_hours, min_hours, always_expensive,
            now=now, rolling_window_hours=rolling_window_hours,
            inverted=inverted, always_cheap=always_cheap,
        )

    # Log statistics
    active_count = sum(1 for s in schedule if s.get("status") == "active")
    future_active = sum(
        1 for s in schedule
        if s.get("status") == "active"
        and datetime.fromisoformat(s["time"]).astimezone(now.tzinfo) > now
    )
    _LOGGER.debug(
        "Built schedule with %d active slots (%.1f hours, %.1f hours in future) out of %d total slots",
        active_count, active_count / 4.0, future_active / 4.0, len(schedule),
    )

    return schedule


def _apply_rolling_window_constraint(
    schedule: list[dict],
    window_hours: float,
    min_hours: float,
    now: datetime,
    prev_activity_history: list[str] | None = None,
    *,
    inverted: bool = False,
) -> list[dict]:
    """Ensure minimum activity within any rolling window.

    This function modifies the schedule in-place and returns it.
    """
    _LOGGER.debug(
        "Applying rolling window constraint: %s hours within any %s hour window",
        min_hours, window_hours,
    )

    min_slots = int(min_hours * 4)
    window_slots = int(window_hours * 4)
    slots_activated = 0

    if prev_activity_history is None:
        prev_activity_history = []

    # Check windows that include NOW (look back into the past)
    window_start_time = now - timedelta(hours=window_hours)

    # Count active slots from the current schedule (past slots)
    past_active_from_schedule = [
        s["time"] for s in schedule
        if datetime.fromisoformat(s["time"]).astimezone(now.tzinfo) >= window_start_time
        and datetime.fromisoformat(s["time"]).astimezone(now.tzinfo) < now
        and s.get("status") == "active"
    ]

    # Count active slots from previous activity history (cross-day data)
    past_active_from_history = [
        t for t in prev_activity_history
        if datetime.fromisoformat(t).astimezone(now.tzinfo) >= window_start_time
        and datetime.fromisoformat(t).astimezone(now.tzinfo) < now
    ]

    # Combine both sources (deduplicate)
    all_past_active = list(set(past_active_from_schedule + past_active_from_history))
    past_active_count = len(all_past_active)

    _LOGGER.info(
        "Looking back %sh from now: found %d/%d active slots (%.1f/%.1fh) "
        "[schedule:%d, history:%d]",
        window_hours, past_active_count, min_slots,
        past_active_count / 4, min_hours,
        len(past_active_from_schedule), len(past_active_from_history),
    )

    # If not enough activity in recent past, activate slots ASAP
    if past_active_count < min_slots:
        shortfall = min_slots - past_active_count
        _LOGGER.info(
            "Constraint check: Need %d more slots (%.1fh) to meet minimum activity requirement",
            shortfall, shortfall / 4,
        )

        # Get current and future slots (slots that haven't ended yet)
        current_and_future = []
        for idx, s in enumerate(schedule):
            slot_time = datetime.fromisoformat(s["time"]).astimezone(now.tzinfo)
            if idx + 1 < len(schedule):
                next_slot_time = datetime.fromisoformat(schedule[idx + 1]["time"]).astimezone(now.tzinfo)
            else:
                next_slot_time = slot_time + timedelta(minutes=15)

            if next_slot_time > now:
                current_and_future.append({
                    "slot": s,
                    "start": slot_time,
                    "end": next_slot_time,
                    "status": s.get("status"),
                    "price": s.get("price", 999),
                })

        # Activate standby slots starting from NOW (sorted by time for urgency)
        standby_slots = [s for s in current_and_future if s["status"] == "standby"]
        standby_slots.sort(key=lambda x: x["start"])

        slots_to_activate = min(shortfall, len(standby_slots))
        for i in range(slots_to_activate):
            slot_info = standby_slots[i]
            for s in schedule:
                if s["time"] == slot_info["slot"]["time"] and s.get("status") == "standby":
                    s["status"] = "active"
                    slots_activated += 1
                    _LOGGER.info(
                        "CRITICAL activation: %s at price %.3f (slot time %s)",
                        slot_info["slot"]["time"], slot_info["price"],
                        slot_info["start"].strftime("%H:%M"),
                    )
                    break

    # Forward-looking windows
    future_schedule = [
        s for s in schedule
        if datetime.fromisoformat(s["time"]).astimezone(now.tzinfo) >= now
    ]

    # Fallback strategy when not enough future slots for a full window
    if len(future_schedule) < window_slots:
        available_hours = len(future_schedule) / 4.0
        hours_that_will_age_out = min(available_hours, window_hours)

        aging_out_cutoff = now + timedelta(hours=available_hours) - timedelta(hours=window_hours)

        past_slots_that_will_age_out = sum(
            1 for t in all_past_active
            if window_start_time <= datetime.fromisoformat(t).astimezone(now.tzinfo) < aging_out_cutoff
        )

        active_in_future = sum(1 for s in future_schedule if s.get("status") == "active")
        remaining_active_after_aging = past_active_count - past_slots_that_will_age_out
        required_future_slots = max(0, min_slots - remaining_active_after_aging)

        _LOGGER.debug(
            "Fallback check: %.1fh future data, %d past active, %d will age out, need %d future slots",
            available_hours, past_active_count, past_slots_that_will_age_out, required_future_slots,
        )

        if active_in_future < required_future_slots:
            shortfall = required_future_slots - active_in_future
            _LOGGER.warning(
                "Fallback: Only %d/%d active slots in next %.1fh "
                "(need %d more to maintain constraint as past activity ages out)",
                active_in_future, required_future_slots, available_hours, shortfall,
            )

            # Activate preferred standby slots (cheapest in normal, most expensive in inverted)
            standby_slots = [s for s in future_schedule if s.get("status") == "standby"]
            standby_slots.sort(key=lambda x: x["price"], reverse=inverted)

            for i in range(min(shortfall, len(standby_slots))):
                for s in schedule:
                    if s["time"] == standby_slots[i]["time"]:
                        s["status"] = "active"
                        slots_activated += 1
                        _LOGGER.info(
                            "Fallback activation: %s at price %.3f",
                            standby_slots[i]["time"], standby_slots[i]["price"],
                        )
                        standby_slots[i]["status"] = "active"
                        break
        else:
            _LOGGER.info(
                "Fallback: Future has %d active slots, sufficient to maintain constraint as past ages out",
                active_in_future,
            )

        return schedule  # Skip normal window checking if insufficient data

    # Check each possible window
    for window_start_idx in range(len(future_schedule) - window_slots + 1):
        window_end_idx = window_start_idx + window_slots
        window_slots_list = future_schedule[window_start_idx:window_end_idx]

        active_in_window = sum(1 for s in window_slots_list if s.get("status") == "active")

        if active_in_window < min_slots:
            shortfall = min_slots - active_in_window
            _LOGGER.info(
                "Window starting at %s has only %d/%d active slots (need %d more)",
                window_slots_list[0]["time"], active_in_window, min_slots, shortfall,
            )

            standby_in_window = [s for s in window_slots_list if s.get("status") == "standby"]
            standby_in_window.sort(key=lambda x: x["price"], reverse=inverted)

            for i in range(min(shortfall, len(standby_in_window))):
                for s in schedule:
                    if s["time"] == standby_in_window[i]["time"]:
                        s["status"] = "active"
                        slots_activated += 1
                        _LOGGER.info(
                            "Rolling window activation: %s at price %.3f",
                            standby_in_window[i]["time"], standby_in_window[i]["price"],
                        )
                        standby_in_window[i]["status"] = "active"
                        break

    if slots_activated > 0:
        _LOGGER.info(
            "Activated %d slots (%.1f hours) to satisfy rolling window constraint",
            slots_activated, slots_activated / 4,
        )

    return schedule


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


def _enforce_min_consecutive(
    schedule: list[dict],
    min_consecutive_hours: float,
    min_hours: float,
    always_expensive: float | None,
    *,
    now: datetime,
    rolling_window_hours: float = 24.0,
    inverted: bool = False,
    always_cheap: float | None = None,
) -> list[dict]:
    """Ensure all future active blocks are at least min_consecutive_hours long.

    Consolidates short future blocks by deactivating their slots and
    re-allocating them into the best consecutive future windows. Only operates
    on future slots within the rolling window horizon to avoid undoing the
    rolling window constraint's temporal placement.

    In normal mode: never activates slots at or above always_expensive.
    In inverted mode: never activates slots at or below always_cheap.

    Args:
        schedule: Time-sorted schedule (modified in-place).
        min_consecutive_hours: Minimum consecutive hours per active block.
        min_hours: Overall minimum hours (caps the consecutive requirement).
        always_expensive: Price threshold; in normal mode, slots at/above are never activated.
        now: Current datetime (timezone-aware). Only future slots are consolidated.
        rolling_window_hours: Rolling window size, limits how far candidates can be.
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

    # Find the future slot range — only consolidate within rolling window horizon
    window_end_time = now + timedelta(hours=rolling_window_hours)
    future_start_idx = 0
    future_end_idx = len(schedule)
    found_future = False
    for i, s in enumerate(schedule):
        slot_time = datetime.fromisoformat(s["time"]).astimezone(now.tzinfo)
        if not found_future and slot_time >= now:
            future_start_idx = i
            found_future = True
        if found_future and slot_time >= window_end_time:
            future_end_idx = i
            break
    if not found_future:
        # All slots are in the past, nothing to consolidate
        return schedule

    blocks = _find_active_blocks(schedule)
    # Only consolidate blocks that are entirely in the future
    short_blocks = [
        (start, length) for start, length in blocks
        if length < effective_slots and start >= future_start_idx
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

    # Find candidate consecutive windows within rolling window horizon
    candidates = _find_consecutive_candidates(
        schedule, effective_slots, always_expensive, always_cheap, inverted,
        start_idx=future_start_idx, end_idx=future_end_idx,
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
        if new_needed > freed:
            continue  # Not enough budget for this window

        for i in range(win_start, win_start + effective_slots):
            if schedule[i].get("status") == "standby":
                schedule[i]["status"] = "active"
                freed -= 1
                slots_activated += 1
                _LOGGER.debug(
                    "Consecutive consolidation: activated %s at price %.3f",
                    schedule[i]["time"], schedule[i].get("price", 0),
                )
        activated_indices |= win_range

    if freed > 0:
        _LOGGER.debug(
            "%d freed slots could not be placed in consecutive blocks",
            freed,
        )

    total_active = sum(1 for s in schedule if s.get("status") == "active")
    _LOGGER.info(
        "After consecutive enforcement: %d total active slots (%.1f hours), "
        "consolidated %d short blocks",
        total_active, total_active / 4.0, len(short_blocks),
    )

    return schedule


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
        List of (start_index, new_activations_needed, score) tuples,
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


def build_activity_history(
    schedule: list[dict],
    prev_history: list[str],
    now: datetime,
    window_hours: float,
) -> list[str]:
    """Build the activity history by merging schedule data with previous history.

    Args:
        schedule: Current schedule.
        prev_history: Previous activity history (list of ISO timestamps).
        now: Current datetime (timezone-aware).
        window_hours: Window size for pruning old entries.

    Returns:
        Sorted, deduplicated list of ISO timestamps of active slots within the window.
    """
    # Collect active slots from schedule that have started
    activity_history = [
        s["time"] for s in schedule
        if datetime.fromisoformat(s["time"]).astimezone(now.tzinfo) <= now
        and s.get("status") == "active"
    ]

    # Merge with previous history (deduplicate)
    activity_set = set(activity_history)
    for prev_time in prev_history:
        if prev_time not in activity_set:
            activity_history.append(prev_time)

    # Prune to window
    cutoff_time = now - timedelta(hours=window_hours)
    activity_history = [
        t for t in activity_history
        if datetime.fromisoformat(t).astimezone(now.tzinfo) >= cutoff_time
    ]
    activity_history.sort()

    return activity_history
