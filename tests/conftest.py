"""Shared test fixtures for Power Saver tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from helpers import TZ, make_nordpool_hour, make_nordpool_slot  # noqa: F401


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
