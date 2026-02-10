"""Shared test helpers for Power Saver tests."""

from __future__ import annotations

from unittest.mock import MagicMock


def make_config_entry(entry_id="test_entry_id"):
    """Create a mock ConfigEntry for testing."""
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"name": "Test"}
    return entry
