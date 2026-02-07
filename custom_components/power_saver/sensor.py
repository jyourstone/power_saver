"""Sensor platform for the Power Saver integration."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_NAME, DOMAIN, STATE_ACTIVE, STATE_STANDBY
from .coordinator import PowerSaverCoordinator, PowerSaverData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Power Saver sensors from a config entry."""
    coordinator: PowerSaverCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        PowerSaverSensor(coordinator, entry),
        ScheduleSensor(coordinator, entry),
        LastActiveSensor(coordinator, entry),
        ActiveHoursInWindowSensor(coordinator, entry),
    ])


class PowerSaverSensor(CoordinatorEntity[PowerSaverCoordinator], SensorEntity):
    """Main sensor entity for Power Saver status."""

    _attr_has_entity_name = True
    _attr_translation_key = "status"

    def __init__(
        self, coordinator: PowerSaverCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_NAME],
            manufacturer="Power Saver",
            model="Price Optimizer",
            entry_type="service",
        )

    @property
    def native_value(self) -> str:
        """Return current state: 'active' or 'standby'."""
        if self.coordinator.data is None:
            return STATE_STANDBY
        return self.coordinator.data.current_state

    @property
    def icon(self) -> str:
        """Return icon based on state."""
        if self.coordinator.data and self.coordinator.data.emergency_mode:
            return "mdi:alert-circle"
        if self.coordinator.data and self.coordinator.data.current_state == "active":
            return "mdi:power-plug"
        return "mdi:power-plug-off"

    @property
    def extra_state_attributes(self) -> dict:
        """Return user-facing attributes."""
        if self.coordinator.data is None:
            return {}
        data: PowerSaverData = self.coordinator.data
        return {
            "current_price": data.current_price,
            "min_price": data.min_price,
            "max_price": data.max_price,
            "next_change": data.next_change,
            "active_slots": data.active_slots,
            "emergency_mode": data.emergency_mode,
        }


# --- Diagnostic sensors ---


class _DiagnosticBase(CoordinatorEntity[PowerSaverCoordinator], SensorEntity):
    """Base class for Power Saver diagnostic sensors."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: PowerSaverCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the diagnostic sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{self._attr_translation_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_NAME],
            manufacturer="Power Saver",
            model="Price Optimizer",
            entry_type="service",
        )


class ScheduleSensor(_DiagnosticBase):
    """Diagnostic sensor exposing the full schedule."""

    _attr_translation_key = "schedule"
    _attr_icon = "mdi:calendar-clock"

    @property
    def native_value(self) -> int | None:
        """Return number of active slots in the schedule."""
        if self.coordinator.data is None:
            return None
        return sum(
            1 for s in self.coordinator.data.schedule
            if s.get("status") == STATE_ACTIVE
        )

    @property
    def extra_state_attributes(self) -> dict:
        """Return the full schedule as an attribute."""
        if self.coordinator.data is None:
            return {}
        return {"schedule": self.coordinator.data.schedule}


class LastActiveSensor(_DiagnosticBase):
    """Diagnostic sensor showing when the last active slot occurred."""

    _attr_translation_key = "last_active"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        """Return timestamp of last active slot."""
        if (
            self.coordinator.data is None
            or self.coordinator.data.last_active_time is None
        ):
            return None
        return datetime.fromisoformat(self.coordinator.data.last_active_time)


class ActiveHoursInWindowSensor(_DiagnosticBase):
    """Diagnostic sensor showing active hours within the rolling window."""

    _attr_translation_key = "active_hours_in_window"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS

    @property
    def native_value(self) -> float | None:
        """Return active hours in the rolling window."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.active_hours_in_window


