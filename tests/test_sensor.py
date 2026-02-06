"""Tests for the Power Saver sensor entity."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.power_saver.coordinator import PowerSaverData
from custom_components.power_saver.sensor import PowerSaverSensor


def test_sensor_native_value_active():
    """Test sensor returns 'active' when coordinator says active."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(current_state="active")

    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {"name": "Test"}

    sensor = PowerSaverSensor(coordinator, entry)
    assert sensor.native_value == "active"


def test_sensor_native_value_standby():
    """Test sensor returns 'standby' when coordinator says standby."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(current_state="standby")

    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {"name": "Test"}

    sensor = PowerSaverSensor(coordinator, entry)
    assert sensor.native_value == "standby"


def test_sensor_native_value_no_data():
    """Test sensor returns 'standby' when coordinator has no data."""
    coordinator = MagicMock()
    coordinator.data = None

    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {"name": "Test"}

    sensor = PowerSaverSensor(coordinator, entry)
    assert sensor.native_value == "standby"


def test_sensor_icon_active():
    """Test icon when active."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(current_state="active")

    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {"name": "Test"}

    sensor = PowerSaverSensor(coordinator, entry)
    assert sensor.icon == "mdi:power-plug"


def test_sensor_icon_standby():
    """Test icon when standby."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(current_state="standby")

    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {"name": "Test"}

    sensor = PowerSaverSensor(coordinator, entry)
    assert sensor.icon == "mdi:power-plug-off"


def test_sensor_icon_emergency():
    """Test icon in emergency mode."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(emergency_mode=True)

    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {"name": "Test"}

    sensor = PowerSaverSensor(coordinator, entry)
    assert sensor.icon == "mdi:alert-circle"


def test_sensor_extra_attributes():
    """Test that all expected attributes are exposed."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(
        schedule=[{"price": 0.1, "time": "2026-02-06T10:00:00+01:00", "status": "active"}],
        current_state="active",
        current_price=0.1,
        min_price=0.03,
        next_change="2026-02-06T11:00:00+01:00",
        active_slots=10,
        last_active_time="2026-02-06T10:00:00+01:00",
        hours_since_last_active=0.5,
        active_slots_in_window=8,
        active_hours_in_window=2.0,
        activity_history=["2026-02-06T10:00:00+01:00"],
        emergency_mode=False,
    )

    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {"name": "Test"}

    sensor = PowerSaverSensor(coordinator, entry)
    attrs = sensor.extra_state_attributes

    assert "schedule" in attrs
    assert "current_price" in attrs
    assert "min_price" in attrs
    assert "next_change" in attrs
    assert "active_slots" in attrs
    assert "active_hours_in_window" in attrs
    assert "emergency_mode" in attrs
    assert "recent_activity_history" in attrs
    assert attrs["current_price"] == 0.1
    assert attrs["active_slots"] == 10
    assert attrs["emergency_mode"] is False


def test_sensor_extra_attributes_no_data():
    """Test that attributes return empty dict when no data."""
    coordinator = MagicMock()
    coordinator.data = None

    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {"name": "Test"}

    sensor = PowerSaverSensor(coordinator, entry)
    assert sensor.extra_state_attributes == {}
