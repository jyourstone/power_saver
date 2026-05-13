"""Tests for the Power Saver service calls."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from helpers import make_config_entry

from custom_components.power_saver.coordinator import PowerSaverCoordinator


# --- Coordinator hours override unit tests ---


def test_hours_override_default_is_none():
    """Test the hours override is None by default."""
    with patch(
        "custom_components.power_saver.coordinator.DataUpdateCoordinator.__init__"
    ):
        coordinator = PowerSaverCoordinator.__new__(PowerSaverCoordinator)
        coordinator._hours_override = None
        assert coordinator._hours_override is None


async def test_async_set_hours_override():
    """Test setting hours override stores the value and triggers refresh."""
    hass = MagicMock()
    entry = make_config_entry()
    entry.options = {}
    entry.data = {"nordpool_sensor": "sensor.nordpool", "name": "Test", "nordpool_type": "hacs"}

    with patch(
        "custom_components.power_saver.coordinator.DataUpdateCoordinator.__init__"
    ):
        coordinator = PowerSaverCoordinator.__new__(PowerSaverCoordinator)
        coordinator.hass = hass
        coordinator.config_entry = entry
        coordinator._hours_override = None
        coordinator._locked_schedule = [{"time": "2026-01-01T00:00:00", "status": "active"}]
        coordinator._store = MagicMock()
        coordinator._store.async_save = AsyncMock()
        coordinator._last_on_time = None
        coordinator.async_request_refresh = AsyncMock()
        coordinator.logger = MagicMock()

        await coordinator.async_set_hours_override(18.0)

        assert coordinator._hours_override == 18.0
        assert coordinator._locked_schedule is None  # Schedule invalidated
        coordinator.async_request_refresh.assert_awaited_once()
        coordinator._store.async_save.assert_awaited_once()
        # Verify saved data includes the override
        saved_data = coordinator._store.async_save.call_args[0][0]
        assert saved_data["hours_override"] == 18.0


async def test_async_clear_hours_override():
    """Test clearing hours override removes value and triggers refresh."""
    hass = MagicMock()
    entry = make_config_entry()
    entry.options = {}
    entry.data = {"nordpool_sensor": "sensor.nordpool", "name": "Test", "nordpool_type": "hacs"}

    with patch(
        "custom_components.power_saver.coordinator.DataUpdateCoordinator.__init__"
    ):
        coordinator = PowerSaverCoordinator.__new__(PowerSaverCoordinator)
        coordinator.hass = hass
        coordinator.config_entry = entry
        coordinator._hours_override = 18.0
        coordinator._locked_schedule = [{"time": "2026-01-01T00:00:00", "status": "active"}]
        coordinator._store = MagicMock()
        coordinator._store.async_save = AsyncMock()
        coordinator._last_on_time = None
        coordinator.async_request_refresh = AsyncMock()
        coordinator.logger = MagicMock()

        await coordinator.async_clear_hours_override()

        assert coordinator._hours_override is None
        assert coordinator._locked_schedule is None  # Schedule invalidated
        coordinator.async_request_refresh.assert_awaited_once()
        saved_data = coordinator._store.async_save.call_args[0][0]
        assert saved_data["hours_override"] is None


def test_hours_override_included_in_fingerprint():
    """Test that changing hours_override changes the options fingerprint."""
    hass = MagicMock()
    entry = make_config_entry()
    entry.options = {"hours_per_period": 4.0, "strategy": "lowest_price"}
    entry.data = {"nordpool_sensor": "sensor.nordpool", "name": "Test", "nordpool_type": "hacs"}

    with patch(
        "custom_components.power_saver.coordinator.DataUpdateCoordinator.__init__"
    ):
        coordinator = PowerSaverCoordinator.__new__(PowerSaverCoordinator)
        coordinator.hass = hass
        coordinator.config_entry = entry

        coordinator._hours_override = None
        fp_none = coordinator._compute_options_fingerprint()

        coordinator._hours_override = 10.0
        fp_10 = coordinator._compute_options_fingerprint()

        coordinator._hours_override = 15.0
        fp_15 = coordinator._compute_options_fingerprint()

        assert fp_none != fp_10
        assert fp_10 != fp_15
        assert fp_none != fp_15


async def test_hours_override_restored_from_storage():
    """Test hours_override is restored from persisted storage."""
    hass = MagicMock()
    entry = make_config_entry()
    entry.options = {}
    entry.data = {"nordpool_sensor": "sensor.nordpool", "name": "Test", "nordpool_type": "hacs"}

    with patch(
        "custom_components.power_saver.coordinator.DataUpdateCoordinator.__init__"
    ):
        coordinator = PowerSaverCoordinator.__new__(PowerSaverCoordinator)
        coordinator.hass = hass
        coordinator.config_entry = entry
        coordinator._hours_override = None
        coordinator._last_on_time = None
        coordinator._store = MagicMock()
        coordinator._store.async_load = AsyncMock(
            return_value={"last_on_time": None, "hours_override": 12.5}
        )
        coordinator.logger = MagicMock()

        await coordinator._async_load_state()

        assert coordinator._hours_override == 12.5


async def test_hours_override_not_restored_when_absent():
    """Test hours_override stays None when not in stored data."""
    hass = MagicMock()
    entry = make_config_entry()
    entry.options = {}
    entry.data = {"nordpool_sensor": "sensor.nordpool", "name": "Test", "nordpool_type": "hacs"}

    with patch(
        "custom_components.power_saver.coordinator.DataUpdateCoordinator.__init__"
    ):
        coordinator = PowerSaverCoordinator.__new__(PowerSaverCoordinator)
        coordinator.hass = hass
        coordinator.config_entry = entry
        coordinator._hours_override = None
        coordinator._last_on_time = None
        coordinator._store = MagicMock()
        coordinator._store.async_load = AsyncMock(
            return_value={"last_on_time": None}
        )
        coordinator.logger = MagicMock()

        await coordinator._async_load_state()

        assert coordinator._hours_override is None


def test_hours_override_property():
    """Test the hours_override property returns current value."""
    hass = MagicMock()
    entry = make_config_entry()
    entry.options = {}
    entry.data = {"nordpool_sensor": "sensor.nordpool", "name": "Test", "nordpool_type": "hacs"}

    with patch(
        "custom_components.power_saver.coordinator.DataUpdateCoordinator.__init__"
    ):
        coordinator = PowerSaverCoordinator.__new__(PowerSaverCoordinator)
        coordinator._hours_override = None
        assert coordinator.hours_override is None

        coordinator._hours_override = 6.5
        assert coordinator.hours_override == 6.5


# --- Coordinator exclude times override unit tests ---


def test_exclude_times_override_default_is_none():
    """Test the exclude times override is None by default."""
    with patch(
        "custom_components.power_saver.coordinator.DataUpdateCoordinator.__init__"
    ):
        coordinator = PowerSaverCoordinator.__new__(PowerSaverCoordinator)
        coordinator._exclude_from_override = None
        coordinator._exclude_until_override = None
        assert coordinator.exclude_times_override is None


async def test_async_set_exclude_times_override():
    """Test setting exclude times override stores the values and refreshes."""
    hass = MagicMock()
    entry = make_config_entry()
    entry.options = {}
    entry.data = {"nordpool_sensor": "sensor.nordpool", "name": "Test", "nordpool_type": "hacs"}

    with patch(
        "custom_components.power_saver.coordinator.DataUpdateCoordinator.__init__"
    ):
        coordinator = PowerSaverCoordinator.__new__(PowerSaverCoordinator)
        coordinator.hass = hass
        coordinator.config_entry = entry
        coordinator._hours_override = None
        coordinator._exclude_from_override = None
        coordinator._exclude_until_override = None
        coordinator._locked_schedule = [{"time": "2026-01-01T00:00:00", "status": "active"}]
        coordinator._store = MagicMock()
        coordinator._store.async_save = AsyncMock()
        coordinator._last_on_time = None
        coordinator.async_request_refresh = AsyncMock()
        coordinator.logger = MagicMock()

        await coordinator.async_set_exclude_times_override("22:00", "06:00")

        assert coordinator._exclude_from_override == "22:00"
        assert coordinator._exclude_until_override == "06:00"
        assert coordinator._locked_schedule is None
        coordinator.async_request_refresh.assert_awaited_once()
        coordinator._store.async_save.assert_awaited_once()
        saved_data = coordinator._store.async_save.call_args[0][0]
        assert saved_data["exclude_from_override"] == "22:00"
        assert saved_data["exclude_until_override"] == "06:00"


async def test_async_clear_exclude_times_override():
    """Test clearing exclude times override removes values and refreshes."""
    hass = MagicMock()
    entry = make_config_entry()
    entry.options = {}
    entry.data = {"nordpool_sensor": "sensor.nordpool", "name": "Test", "nordpool_type": "hacs"}

    with patch(
        "custom_components.power_saver.coordinator.DataUpdateCoordinator.__init__"
    ):
        coordinator = PowerSaverCoordinator.__new__(PowerSaverCoordinator)
        coordinator.hass = hass
        coordinator.config_entry = entry
        coordinator._hours_override = None
        coordinator._exclude_from_override = "22:00"
        coordinator._exclude_until_override = "06:00"
        coordinator._locked_schedule = [{"time": "2026-01-01T00:00:00", "status": "active"}]
        coordinator._store = MagicMock()
        coordinator._store.async_save = AsyncMock()
        coordinator._last_on_time = None
        coordinator.async_request_refresh = AsyncMock()
        coordinator.logger = MagicMock()

        await coordinator.async_clear_exclude_times_override()

        assert coordinator._exclude_from_override is None
        assert coordinator._exclude_until_override is None
        assert coordinator._locked_schedule is None
        coordinator.async_request_refresh.assert_awaited_once()
        saved_data = coordinator._store.async_save.call_args[0][0]
        assert saved_data["exclude_from_override"] is None
        assert saved_data["exclude_until_override"] is None


def test_exclude_times_override_included_in_fingerprint():
    """Test that changing exclude times override changes the options fingerprint."""
    hass = MagicMock()
    entry = make_config_entry()
    entry.options = {"exclude_from": "00:00", "exclude_until": "06:00"}
    entry.data = {"nordpool_sensor": "sensor.nordpool", "name": "Test", "nordpool_type": "hacs"}

    with patch(
        "custom_components.power_saver.coordinator.DataUpdateCoordinator.__init__"
    ):
        coordinator = PowerSaverCoordinator.__new__(PowerSaverCoordinator)
        coordinator.hass = hass
        coordinator.config_entry = entry
        coordinator._hours_override = None

        coordinator._exclude_from_override = None
        coordinator._exclude_until_override = None
        fp_none = coordinator._compute_options_fingerprint()

        coordinator._exclude_from_override = "22:00"
        coordinator._exclude_until_override = "06:00"
        fp_night = coordinator._compute_options_fingerprint()

        coordinator._exclude_from_override = "23:00"
        coordinator._exclude_until_override = "07:00"
        fp_late = coordinator._compute_options_fingerprint()

        assert fp_none != fp_night
        assert fp_night != fp_late
        assert fp_none != fp_late


async def test_exclude_times_override_restored_from_storage():
    """Test exclude times override is restored from persisted storage."""
    hass = MagicMock()
    entry = make_config_entry()
    entry.options = {}
    entry.data = {"nordpool_sensor": "sensor.nordpool", "name": "Test", "nordpool_type": "hacs"}

    with patch(
        "custom_components.power_saver.coordinator.DataUpdateCoordinator.__init__"
    ):
        coordinator = PowerSaverCoordinator.__new__(PowerSaverCoordinator)
        coordinator.hass = hass
        coordinator.config_entry = entry
        coordinator._hours_override = None
        coordinator._exclude_from_override = None
        coordinator._exclude_until_override = None
        coordinator._last_on_time = None
        coordinator._store = MagicMock()
        coordinator._store.async_load = AsyncMock(
            return_value={
                "last_on_time": None,
                "exclude_from_override": "22:00",
                "exclude_until_override": "06:00:00",
            }
        )
        coordinator.logger = MagicMock()

        await coordinator._async_load_state()

        assert coordinator.exclude_times_override == {
            "exclude_from": "22:00",
            "exclude_until": "06:00:00",
        }


async def test_exclude_times_override_not_restored_when_absent():
    """Test exclude times override stays None when not in stored data."""
    hass = MagicMock()
    entry = make_config_entry()
    entry.options = {}
    entry.data = {"nordpool_sensor": "sensor.nordpool", "name": "Test", "nordpool_type": "hacs"}

    with patch(
        "custom_components.power_saver.coordinator.DataUpdateCoordinator.__init__"
    ):
        coordinator = PowerSaverCoordinator.__new__(PowerSaverCoordinator)
        coordinator.hass = hass
        coordinator.config_entry = entry
        coordinator._hours_override = None
        coordinator._exclude_from_override = None
        coordinator._exclude_until_override = None
        coordinator._last_on_time = None
        coordinator._store = MagicMock()
        coordinator._store.async_load = AsyncMock(
            return_value={"last_on_time": None}
        )
        coordinator.logger = MagicMock()

        await coordinator._async_load_state()

        assert coordinator.exclude_times_override is None


async def test_invalid_exclude_times_override_not_restored():
    """Test invalid persisted exclude times override is ignored."""
    hass = MagicMock()
    entry = make_config_entry()
    entry.options = {}
    entry.data = {"nordpool_sensor": "sensor.nordpool", "name": "Test", "nordpool_type": "hacs"}

    with patch(
        "custom_components.power_saver.coordinator.DataUpdateCoordinator.__init__"
    ):
        coordinator = PowerSaverCoordinator.__new__(PowerSaverCoordinator)
        coordinator.hass = hass
        coordinator.config_entry = entry
        coordinator._hours_override = None
        coordinator._exclude_from_override = None
        coordinator._exclude_until_override = None
        coordinator._last_on_time = None
        coordinator._store = MagicMock()
        coordinator._store.async_load = AsyncMock(
            return_value={
                "last_on_time": None,
                "exclude_from_override": "25:00",
                "exclude_until_override": "06:00",
            }
        )
        coordinator.logger = MagicMock()

        await coordinator._async_load_state()

        assert coordinator.exclude_times_override is None


def test_exclude_times_override_property():
    """Test the exclude_times_override property returns current values."""
    with patch(
        "custom_components.power_saver.coordinator.DataUpdateCoordinator.__init__"
    ):
        coordinator = PowerSaverCoordinator.__new__(PowerSaverCoordinator)
        coordinator._exclude_from_override = None
        coordinator._exclude_until_override = None
        assert coordinator.exclude_times_override is None

        coordinator._exclude_from_override = "22:00"
        coordinator._exclude_until_override = "06:00"
        assert coordinator.exclude_times_override == {
            "exclude_from": "22:00",
            "exclude_until": "06:00",
        }


# --- Status sensor override attribute tests ---


def test_status_sensor_shows_override_attribute():
    """Test that the status sensor includes schedule_hours_override when set."""
    from custom_components.power_saver.coordinator import PowerSaverData
    from custom_components.power_saver.sensor import PowerSaverSensor

    coordinator = MagicMock()
    coordinator.data = PowerSaverData(
        current_state="active",
        current_price=0.15,
        min_price=0.05,
        max_price=0.60,
        active_slots=40,
        strategy="lowest_price",
    )
    coordinator.hours_override = 18.0
    coordinator.exclude_times_override = None

    sensor = PowerSaverSensor(coordinator, make_config_entry())
    attrs = sensor.extra_state_attributes
    assert attrs["schedule_hours_override"] == 18.0


def test_status_sensor_no_override_attribute_when_none():
    """Test that schedule_hours_override is absent when no override is set."""
    from custom_components.power_saver.coordinator import PowerSaverData
    from custom_components.power_saver.sensor import PowerSaverSensor

    coordinator = MagicMock()
    coordinator.data = PowerSaverData(
        current_state="standby",
        current_price=0.10,
        min_price=0.05,
        max_price=0.60,
        active_slots=20,
        strategy="lowest_price",
    )
    coordinator.hours_override = None
    coordinator.exclude_times_override = None

    sensor = PowerSaverSensor(coordinator, make_config_entry())
    attrs = sensor.extra_state_attributes
    assert "schedule_hours_override" not in attrs


def test_status_sensor_shows_exclude_times_override_attribute():
    """Test that status sensor includes exclude_times_override when set."""
    from custom_components.power_saver.coordinator import PowerSaverData
    from custom_components.power_saver.sensor import PowerSaverSensor

    coordinator = MagicMock()
    coordinator.data = PowerSaverData(
        current_state="active",
        current_price=0.15,
        min_price=0.05,
        max_price=0.60,
        active_slots=40,
        strategy="lowest_price",
    )
    coordinator.hours_override = None
    coordinator.exclude_times_override = {
        "exclude_from": "22:00",
        "exclude_until": "06:00",
    }

    sensor = PowerSaverSensor(coordinator, make_config_entry())
    attrs = sensor.extra_state_attributes
    assert attrs["exclude_times_override"] == {
        "exclude_from": "22:00",
        "exclude_until": "06:00",
    }


def test_status_sensor_no_exclude_times_override_attribute_when_none():
    """Test that exclude_times_override is absent when no override is set."""
    from custom_components.power_saver.coordinator import PowerSaverData
    from custom_components.power_saver.sensor import PowerSaverSensor

    coordinator = MagicMock()
    coordinator.data = PowerSaverData(
        current_state="standby",
        current_price=0.10,
        min_price=0.05,
        max_price=0.60,
        active_slots=20,
        strategy="lowest_price",
    )
    coordinator.hours_override = None
    coordinator.exclude_times_override = None

    sensor = PowerSaverSensor(coordinator, make_config_entry())
    attrs = sensor.extra_state_attributes
    assert "exclude_times_override" not in attrs


# --- __init__.py service registration tests ---


def test_set_exclude_times_schema_accepts_supported_time_formats():
    """Test set_exclude_times service schema accepts HH:MM and HH:MM:SS."""
    from custom_components.power_saver import SERVICE_SET_EXCLUDE_TIMES_SCHEMA

    data = SERVICE_SET_EXCLUDE_TIMES_SCHEMA(
        {
            "device_id": "device_abc",
            "exclude_from": "22:00",
            "exclude_until": "06:00:00",
        }
    )

    assert data["exclude_from"] == "22:00"
    assert data["exclude_until"] == "06:00:00"


def test_set_exclude_times_schema_rejects_invalid_time():
    """Test set_exclude_times service schema rejects invalid time strings."""
    from custom_components.power_saver import SERVICE_SET_EXCLUDE_TIMES_SCHEMA

    with pytest.raises(vol.Invalid):
        SERVICE_SET_EXCLUDE_TIMES_SCHEMA(
            {
                "device_id": "device_abc",
                "exclude_from": "25:00",
                "exclude_until": "06:00",
            }
        )


def test_find_coordinator_resolves_device():
    """Test _find_coordinator resolves device_id to coordinator."""
    from custom_components.power_saver import _find_coordinator

    hass = MagicMock()
    coordinator = MagicMock()
    hass.data = {"power_saver": {"entry_123": coordinator}}

    device = MagicMock()
    device.config_entries = {"entry_123"}

    with patch(
        "custom_components.power_saver.dr.async_get"
    ) as mock_dr:
        mock_dr.return_value.async_get.return_value = device
        result = _find_coordinator(hass, "device_abc")
        assert result is coordinator


def test_find_coordinator_raises_for_unknown_device():
    """Test _find_coordinator raises ValueError for unknown device."""
    from custom_components.power_saver import _find_coordinator

    hass = MagicMock()
    hass.data = {"power_saver": {}}

    with patch(
        "custom_components.power_saver.dr.async_get"
    ) as mock_dr:
        mock_dr.return_value.async_get.return_value = None
        with pytest.raises(ValueError, match="not found"):
            _find_coordinator(hass, "device_unknown")


def test_find_coordinator_raises_for_non_power_saver_device():
    """Test _find_coordinator raises ValueError for device from another integration."""
    from custom_components.power_saver import _find_coordinator

    hass = MagicMock()
    hass.data = {"power_saver": {}}

    device = MagicMock()
    device.config_entries = {"other_entry_id"}

    with patch(
        "custom_components.power_saver.dr.async_get"
    ) as mock_dr:
        mock_dr.return_value.async_get.return_value = device
        with pytest.raises(ValueError, match="not a Power Saver device"):
            _find_coordinator(hass, "device_other")
