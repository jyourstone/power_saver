"""Tests for the Power Saver binary sensor entities."""

from __future__ import annotations

from unittest.mock import MagicMock

from tests.helpers import make_config_entry

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.helpers.entity import EntityCategory

from custom_components.power_saver.binary_sensor import EmergencyModeBinarySensor
from custom_components.power_saver.coordinator import PowerSaverData


def test_emergency_mode_unique_id():
    """Test emergency mode sensor has correct unique ID."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData()
    sensor = EmergencyModeBinarySensor(coordinator, make_config_entry("abc"))
    assert sensor.unique_id == "abc_emergency_mode"


def test_emergency_mode_device_class():
    """Test emergency mode sensor has problem device class."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData()
    sensor = EmergencyModeBinarySensor(coordinator, make_config_entry())
    assert sensor.device_class == BinarySensorDeviceClass.PROBLEM


def test_emergency_mode_entity_category():
    """Test emergency mode sensor is diagnostic."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData()
    sensor = EmergencyModeBinarySensor(coordinator, make_config_entry())
    assert sensor.entity_category == EntityCategory.DIAGNOSTIC


def test_emergency_mode_is_on_true():
    """Test emergency mode returns True when active."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(emergency_mode=True)
    sensor = EmergencyModeBinarySensor(coordinator, make_config_entry())
    assert sensor.is_on is True


def test_emergency_mode_is_on_false():
    """Test emergency mode returns False when inactive."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(emergency_mode=False)
    sensor = EmergencyModeBinarySensor(coordinator, make_config_entry())
    assert sensor.is_on is False


def test_emergency_mode_no_data():
    """Test emergency mode returns False when no data."""
    coordinator = MagicMock()
    coordinator.data = None
    sensor = EmergencyModeBinarySensor(coordinator, make_config_entry())
    assert sensor.is_on is False
