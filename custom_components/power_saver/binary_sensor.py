"""Binary sensor platform for the Power Saver integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_NAME, DOMAIN
from .coordinator import PowerSaverCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Power Saver binary sensors from a config entry."""
    coordinator: PowerSaverCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        EmergencyModeBinarySensor(coordinator, entry),
    ])


class EmergencyModeBinarySensor(
    CoordinatorEntity[PowerSaverCoordinator], BinarySensorEntity
):
    """Binary sensor indicating whether emergency mode is active."""

    _attr_has_entity_name = True
    _attr_translation_key = "emergency_mode"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self, coordinator: PowerSaverCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_emergency_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_NAME],
            manufacturer="Power Saver",
            model="Price Optimizer",
            entry_type="service",
        )

    @property
    def is_on(self) -> bool:
        """Return True if emergency mode is active."""
        if self.coordinator.data is None:
            return False
        return self.coordinator.data.emergency_mode
