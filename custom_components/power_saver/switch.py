"""Switch platform for the Power Saver integration."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_NAME, DOMAIN
from .coordinator import PowerSaverCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Power Saver switches from a config entry."""
    coordinator: PowerSaverCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        ForceOnSwitch(coordinator, entry),
        ForceOffSwitch(coordinator, entry),
    ])


class ForceOnSwitch(
    CoordinatorEntity[PowerSaverCoordinator], SwitchEntity, RestoreEntity
):
    """Switch to force all controlled entities ON, bypassing the schedule."""

    _attr_has_entity_name = True
    _attr_translation_key = "force_on"
    _attr_icon = "mdi:hand-back-right"

    def __init__(
        self, coordinator: PowerSaverCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_force_on"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_NAME],
            manufacturer="Power Saver",
            model="Price Optimizer",
            entry_type="service",
        )

    @property
    def is_on(self) -> bool:
        """Return True if Always on is active."""
        return self.coordinator.force_on_active

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on the Always on state (force entities on)."""
        await self.coordinator.async_set_force_on(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the Always on state (resume schedule)."""
        await self.coordinator.async_set_force_on(False)

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state == "on":
            _LOGGER.info("Restoring Always on state: ON")
            await self.coordinator.async_set_force_on(True)


class ForceOffSwitch(
    CoordinatorEntity[PowerSaverCoordinator], SwitchEntity, RestoreEntity
):
    """Switch to force all controlled entities OFF, bypassing the schedule."""

    _attr_has_entity_name = True
    _attr_translation_key = "force_off"
    _attr_icon = "mdi:hand-back-right-off"

    def __init__(
        self, coordinator: PowerSaverCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_force_off"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_NAME],
            manufacturer="Power Saver",
            model="Price Optimizer",
            entry_type="service",
        )

    @property
    def is_on(self) -> bool:
        """Return True if Always off is active."""
        return self.coordinator.force_off_active

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on the Always off state (force entities off)."""
        await self.coordinator.async_set_force_off(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the Always off state (resume schedule)."""
        await self.coordinator.async_set_force_off(False)

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state == "on":
            _LOGGER.info("Restoring Always off state: ON")
            await self.coordinator.async_set_force_off(True)
