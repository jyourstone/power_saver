"""Tests for the Power Saver sensor entities."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from helpers import make_config_entry

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfTime
from homeassistant.helpers.entity import EntityCategory

from custom_components.power_saver.coordinator import PowerSaverData
from custom_components.power_saver.sensor import (
    ActiveHoursInPeriodSensor,
    LastActiveSensor,
    NextChangeSensor,
    PowerSaverSensor,
    ScheduleSensor,
)


# --- Main status sensor ---


def test_status_sensor_unique_id():
    """Test main sensor has correct unique ID."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData()
    sensor = PowerSaverSensor(coordinator, make_config_entry("abc"))
    assert sensor.unique_id == "abc_status"


def test_status_sensor_native_value_active():
    """Test sensor returns 'active' when coordinator says active."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(current_state="active")
    sensor = PowerSaverSensor(coordinator, make_config_entry())
    assert sensor.native_value == "active"


def test_status_sensor_native_value_standby():
    """Test sensor returns 'standby' when coordinator says standby."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(current_state="standby")
    sensor = PowerSaverSensor(coordinator, make_config_entry())
    assert sensor.native_value == "standby"


def test_status_sensor_native_value_no_data():
    """Test sensor returns 'standby' when coordinator has no data."""
    coordinator = MagicMock()
    coordinator.data = None
    sensor = PowerSaverSensor(coordinator, make_config_entry())
    assert sensor.native_value == "standby"


def test_status_sensor_icon_active():
    """Test icon when active."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(current_state="active")
    sensor = PowerSaverSensor(coordinator, make_config_entry())
    assert sensor.icon == "mdi:power-plug"


def test_status_sensor_icon_standby():
    """Test icon when standby."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(current_state="standby")
    sensor = PowerSaverSensor(coordinator, make_config_entry())
    assert sensor.icon == "mdi:power-plug-off"


def test_status_sensor_native_value_forced_on():
    """Test sensor returns 'forced_on' when coordinator says forced_on."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(current_state="forced_on")
    sensor = PowerSaverSensor(coordinator, make_config_entry())
    assert sensor.native_value == "forced_on"


def test_status_sensor_native_value_forced_off():
    """Test sensor returns 'forced_off' when coordinator says forced_off."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(current_state="forced_off")
    sensor = PowerSaverSensor(coordinator, make_config_entry())
    assert sensor.native_value == "forced_off"


def test_status_sensor_icon_forced_on():
    """Test icon when in forced_on state."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(current_state="forced_on")
    sensor = PowerSaverSensor(coordinator, make_config_entry())
    assert sensor.icon == "mdi:hand-back-right"


def test_status_sensor_icon_forced_off():
    """Test icon when in forced_off state."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(current_state="forced_off")
    sensor = PowerSaverSensor(coordinator, make_config_entry())
    assert sensor.icon == "mdi:hand-back-right-off"


def test_status_sensor_icon_no_data():
    """Test icon returns plug-off when no data."""
    coordinator = MagicMock()
    coordinator.data = None
    sensor = PowerSaverSensor(coordinator, make_config_entry())
    assert sensor.icon == "mdi:power-plug-off"


def test_status_sensor_attributes():
    """Test that main sensor exposes user-facing attributes including strategy."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(
        current_state="active",
        current_price=0.1,
        min_price=0.03,
        max_price=0.60,
        next_change="2026-02-06T11:00:00+01:00",
        active_slots=10,
        strategy="lowest_price",
        emergency_mode=False,
    )
    sensor = PowerSaverSensor(coordinator, make_config_entry())
    attrs = sensor.extra_state_attributes

    assert attrs == {
        "current_price": 0.1,
        "min_price": 0.03,
        "max_price": 0.60,
        "active_slots": 10,
        "strategy": "lowest_price",
    }
    assert "schedule" not in attrs
    assert "next_change" not in attrs
    assert "emergency_mode" not in attrs


def test_status_sensor_attributes_no_data():
    """Test that attributes return empty dict when no data."""
    coordinator = MagicMock()
    coordinator.data = None
    sensor = PowerSaverSensor(coordinator, make_config_entry())
    assert sensor.extra_state_attributes == {}


# --- Schedule diagnostic sensor ---


def test_schedule_sensor_entity_category():
    """Test schedule sensor is diagnostic."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData()
    sensor = ScheduleSensor(coordinator, make_config_entry())
    assert sensor.entity_category == EntityCategory.DIAGNOSTIC


def test_schedule_sensor_unique_id():
    """Test schedule sensor unique ID."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData()
    sensor = ScheduleSensor(coordinator, make_config_entry("abc"))
    assert sensor.unique_id == "abc_schedule"


def test_schedule_sensor_native_value():
    """Test schedule sensor returns count of active slots."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(
        schedule=[
            {"price": 0.1, "time": "2026-02-06T10:00:00+01:00", "status": "active"},
            {"price": 0.5, "time": "2026-02-06T11:00:00+01:00", "status": "standby"},
            {"price": 0.2, "time": "2026-02-06T12:00:00+01:00", "status": "active"},
        ],
    )
    sensor = ScheduleSensor(coordinator, make_config_entry())
    assert sensor.native_value == 2


def test_schedule_sensor_attributes():
    """Test schedule sensor exposes the full schedule."""
    schedule = [{"price": 0.1, "time": "2026-02-06T10:00:00+01:00", "status": "active"}]
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(schedule=schedule)
    sensor = ScheduleSensor(coordinator, make_config_entry())
    assert sensor.extra_state_attributes == {"schedule": schedule}


def test_schedule_sensor_no_data():
    """Test schedule sensor returns None/empty when no data."""
    coordinator = MagicMock()
    coordinator.data = None
    sensor = ScheduleSensor(coordinator, make_config_entry())
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


# --- Last Active diagnostic sensor ---


def test_last_active_sensor_device_class():
    """Test last active sensor has timestamp device class."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData()
    sensor = LastActiveSensor(coordinator, make_config_entry())
    assert sensor.device_class == SensorDeviceClass.TIMESTAMP


def test_last_active_sensor_unique_id():
    """Test last active sensor unique ID."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData()
    sensor = LastActiveSensor(coordinator, make_config_entry("abc"))
    assert sensor.unique_id == "abc_last_active"


def test_last_active_sensor_native_value():
    """Test last active sensor finds most recent past active slot."""
    tz = timezone(timedelta(hours=1))
    now = datetime(2026, 2, 6, 14, 30, tzinfo=tz)
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(
        schedule=[
            {"price": 0.1, "time": "2026-02-06T10:00:00+01:00", "status": "active"},
            {"price": 0.2, "time": "2026-02-06T12:00:00+01:00", "status": "active"},
            {"price": 0.5, "time": "2026-02-06T16:00:00+01:00", "status": "active"},
            {"price": 0.3, "time": "2026-02-06T13:00:00+01:00", "status": "standby"},
        ],
    )
    sensor = LastActiveSensor(coordinator, make_config_entry())
    with patch("custom_components.power_saver.sensor.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat
        result = sensor.native_value
    expected = datetime(2026, 2, 6, 12, 0, tzinfo=tz)
    assert result == expected


def test_last_active_sensor_no_data():
    """Test last active sensor returns None when no data."""
    coordinator = MagicMock()
    coordinator.data = None
    sensor = LastActiveSensor(coordinator, make_config_entry())
    assert sensor.native_value is None


def test_last_active_sensor_no_past_active():
    """Test last active sensor returns None when no past active slots."""
    tz = timezone(timedelta(hours=1))
    now = datetime(2026, 2, 6, 8, 0, tzinfo=tz)
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(
        schedule=[
            {"price": 0.1, "time": "2026-02-06T10:00:00+01:00", "status": "active"},
        ],
    )
    sensor = LastActiveSensor(coordinator, make_config_entry())
    with patch("custom_components.power_saver.sensor.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat
        result = sensor.native_value
    assert result is None


# --- Active Hours in Period diagnostic sensor ---


def test_active_hours_in_period_sensor_device_class():
    """Test active hours in period has duration device class."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData()
    sensor = ActiveHoursInPeriodSensor(coordinator, make_config_entry())
    assert sensor.device_class == SensorDeviceClass.DURATION
    assert sensor.native_unit_of_measurement == UnitOfTime.HOURS


def test_active_hours_in_period_sensor_native_value():
    """Test active hours in period returns the value."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(active_hours_in_period=3.5)
    sensor = ActiveHoursInPeriodSensor(coordinator, make_config_entry())
    assert sensor.native_value == 3.5


def test_active_hours_in_period_sensor_no_data():
    """Test active hours in period returns None when no data."""
    coordinator = MagicMock()
    coordinator.data = None
    sensor = ActiveHoursInPeriodSensor(coordinator, make_config_entry())
    assert sensor.native_value is None


# --- Next Change diagnostic sensor ---


def test_next_change_sensor_device_class():
    """Test next change sensor has timestamp device class."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData()
    sensor = NextChangeSensor(coordinator, make_config_entry())
    assert sensor.device_class == SensorDeviceClass.TIMESTAMP


def test_next_change_sensor_unique_id():
    """Test next change sensor unique ID."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData()
    sensor = NextChangeSensor(coordinator, make_config_entry("abc"))
    assert sensor.unique_id == "abc_next_change"


def test_next_change_sensor_native_value():
    """Test next change sensor returns parsed datetime."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(
        next_change="2026-02-06T11:00:00+01:00"
    )
    sensor = NextChangeSensor(coordinator, make_config_entry())
    expected = datetime(2026, 2, 6, 11, 0, tzinfo=timezone(timedelta(hours=1)))
    assert sensor.native_value == expected


def test_next_change_sensor_no_data():
    """Test next change sensor returns None when no data."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData(next_change=None)
    sensor = NextChangeSensor(coordinator, make_config_entry())
    assert sensor.native_value is None


# --- Hours Until Deadline diagnostic sensor ---


# --- All diagnostic sensors share base properties ---


def test_all_diagnostic_sensors_are_diagnostic():
    """Test all diagnostic sensors have DIAGNOSTIC entity category."""
    coordinator = MagicMock()
    coordinator.data = PowerSaverData()
    entry = make_config_entry()

    for cls in (
        ScheduleSensor,
        LastActiveSensor,
        ActiveHoursInPeriodSensor,
        NextChangeSensor,
    ):
        sensor = cls(coordinator, entry)
        assert sensor.entity_category == EntityCategory.DIAGNOSTIC, (
            f"{cls.__name__} should be diagnostic"
        )
