"""Shared test fixtures for Power Saver tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

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


@pytest.fixture
def now() -> datetime:
    """Return a fixed 'now' for deterministic testing."""
    return datetime(2026, 2, 6, 14, 30, 0, tzinfo=TZ)


@pytest.fixture
def today_prices() -> list[dict]:
    """Return 96 quarter-hour slots of today's price data with varying prices.

    Prices simulate a typical Nordic winter day:
    cheap at night, expensive in morning/evening, moderate midday.
    Each hour has 4 identical 15-minute slots.
    """
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
