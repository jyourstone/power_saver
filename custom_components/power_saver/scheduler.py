"""Pure scheduling algorithm for the Power Saver integration.

This module contains no Home Assistant dependencies and can be tested independently.
It is a direct port of the AppDaemon PowerSaverManager scheduling logic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

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
    sorted_slots: list[dict], price_similarity_pct: float | None
) -> float | None:
    """Compute the price similarity threshold for a day's slots.

    Uses an additive offset based on the absolute value of the cheapest price,
    which works correctly for both positive and negative prices.
    For positive prices this is equivalent to: min_price * (1 + pct/100).
    """
    if not sorted_slots or not price_similarity_pct or price_similarity_pct <= 0:
        return None
    min_price = float(sorted_slots[0].get("value", 0))
    if min_price == 0:
        return None
    offset = (price_similarity_pct / 100) * abs(min_price)
    threshold = min_price + offset
    _LOGGER.debug(
        "Price similarity threshold: %.3f (cheapest: %.3f, pct: %.1f%%, strategy: %s)",
        threshold, min_price, price_similarity_pct,
        "additive" if min_price < 0 else "multiplicative",
    )
    return threshold


def _process_day_slots(
    sorted_slots: list[dict],
    activated_count: int,
    threshold: float | None,
    always_cheap: float | None,
    always_expensive: float | None,
    now: datetime,
) -> tuple[list[dict], int]:
    """Process a day's price-sorted slots into schedule entries.

    Args:
        sorted_slots: Slots sorted by price (cheapest first).
        activated_count: Remaining activation quota.
        threshold: Price similarity threshold, or None if disabled.
        always_cheap: Price at or below which slots are always active. None = disabled.
        always_expensive: Price at or above which slots are never active. None = disabled.
        now: Current datetime for timezone conversion.

    Returns:
        Tuple of (schedule_entries, remaining_activated_count).
    """
    entries = []
    for slot in sorted_slots:
        try:
            start = _to_datetime(slot.get("start")).astimezone(now.tzinfo)
            price = float(slot.get("value", 0))

            is_within_threshold = threshold is not None and price <= threshold
            is_cheap = always_cheap is not None and price <= always_cheap
            is_expensive = always_expensive is not None and price >= always_expensive
            is_active = (
                (is_cheap or activated_count > 0 or is_within_threshold)
                and not is_expensive
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
) -> list[dict]:
    """Build a schedule from Nordpool price data.

    Activation logic:
    - Activate the cheapest slots up to min_hours (converted to 15-min slots)
    - Activate any slots with price <= always_cheap regardless of quota
    - If price_similarity_pct > 0, also activate slots within that percentage
      of the cheapest price (e.g. 20% means slots up to 1.2x the cheapest)
    - Never activate if price >= always_expensive (safety cutoff)
    - If rolling window constraint is enabled, additional slots are activated as needed

    Args:
        raw_today: Nordpool raw_today attribute (list of dicts with start, end, value).
        raw_tomorrow: Nordpool raw_tomorrow attribute (may be empty).
        min_hours: Minimum active hours per day.
        now: Current datetime (timezone-aware).
        always_cheap: Price at or below which slots are always active. None = disabled.
        always_expensive: Price at or above which slots are never active. None = disabled.
        rolling_window_hours: Rolling window size in hours (always >= 1).
        prev_activity_history: List of ISO timestamps of previously active slots.
        price_similarity_pct: Percentage threshold for price similarity. Slots within
            this percentage of the cheapest price are also activated. None = disabled.

    Returns:
        List of schedule dicts: [{"price": float, "time": str, "status": str}, ...]
    """
    if prev_activity_history is None:
        prev_activity_history = []

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

    # Process today's slots (sorted by price, cheapest first)
    sorted_today = sorted(raw_today, key=lambda x: x.get("value", 999))
    activated_count = min_slots
    today_threshold = _compute_similarity_threshold(sorted_today, price_similarity_pct)
    today_entries, activated_count = _process_day_slots(
        sorted_today, activated_count, today_threshold,
        always_cheap, always_expensive, now,
    )
    schedule.extend(today_entries)

    # Process tomorrow's slots if available
    if raw_tomorrow:
        sorted_tomorrow = sorted(raw_tomorrow, key=lambda x: x.get("value", 999))
        # In rolling window mode, share quota across both days
        # In standard mode, reset to give each day its own quota
        if not use_rolling_window:
            activated_count = min_slots
        tomorrow_threshold = _compute_similarity_threshold(sorted_tomorrow, price_similarity_pct)
        tomorrow_entries, activated_count = _process_day_slots(
            sorted_tomorrow, activated_count, tomorrow_threshold,
            always_cheap, always_expensive, now,
        )
        schedule.extend(tomorrow_entries)

    # Sort by time
    schedule.sort(key=lambda x: x["time"])

    # Apply rolling window constraint if enabled
    if use_rolling_window:
        schedule = _apply_rolling_window_constraint(
            schedule, rolling_window_hours, min_hours, now, prev_activity_history
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

            # Activate cheapest standby slots
            standby_slots = [s for s in future_schedule if s.get("status") == "standby"]
            standby_slots.sort(key=lambda x: x["price"])

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
            standby_in_window.sort(key=lambda x: x["price"])

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
