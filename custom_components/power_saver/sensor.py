"""Sensor platform for the Power Saver integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_NAME, DOMAIN, STATE_STANDBY
from .coordinator import PowerSaverCoordinator, PowerSaverData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Power Saver sensor from a config entry."""
    coordinator: PowerSaverCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PowerSaverSensor(coordinator, entry)])


class PowerSaverSensor(CoordinatorEntity[PowerSaverCoordinator], SensorEntity):
    """Sensor entity for Power Saver schedule."""

    _attr_has_entity_name = True
    _attr_translation_key = "schedule"

    def __init__(
        self, coordinator: PowerSaverCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_schedule"
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
        """Return schedule and metrics as attributes."""
        if self.coordinator.data is None:
            return {}
        data: PowerSaverData = self.coordinator.data
        return {
            "schedule": data.schedule,
            "min_price": data.min_price,
            "current_price": data.current_price,
            "next_change": data.next_change,
            "active_slots": data.active_slots,
            "last_active_time": data.last_active_time,
            "hours_since_last_active": data.hours_since_last_active,
            "active_slots_in_window": data.active_slots_in_window,
            "active_hours_in_window": data.active_hours_in_window,
            "recent_activity_history": data.activity_history,
            "emergency_mode": data.emergency_mode,
        }
