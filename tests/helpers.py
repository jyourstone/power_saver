"""Shared test helpers for Power Saver tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

# Timezone for testing (CET)
TZ = timezone(timedelta(hours=1), name="CET")


def make_nordpool_slot(hour: int, price: float, day_offset: int = 0, quarter: int = 0) -> dict:
    """Create a Nordpool-style 15-minute price slot for testing.

    Args:
        hour: Hour of the day (0-23).
        price: Price value.
        day_offset: 0 for today, 1 for tomorrow.
        quarter: Quarter of the hour (0-3, representing :00, :15, :30, :45).

    Returns:
        Dict matching Nordpool raw_today/raw_tomorrow format.
    """
    base = datetime(2026, 2, 6, tzinfo=TZ) + timedelta(days=day_offset)
    start = base.replace(hour=hour, minute=quarter * 15, second=0, microsecond=0)
    end = start + timedelta(minutes=15)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "value": price,
    }


def make_nordpool_hour(hour: int, price: float, day_offset: int = 0) -> list[dict]:
    """Create 4 Nordpool-style 15-minute slots for a full hour.

    All four quarter-hour slots share the same price.

    Args:
        hour: Hour of the day (0-23).
        price: Price value for all four slots.
        day_offset: 0 for today, 1 for tomorrow.

    Returns:
        List of 4 slot dicts covering the full hour.
    """
    return [make_nordpool_slot(hour, price, day_offset, q) for q in range(4)]


def make_config_entry(entry_id="test_entry_id"):
    """Create a mock ConfigEntry for testing."""
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"name": "Test"}
    return entry
