"""Switch platform for the Power Saver integration."""

from __future__ import annotations

import logging
from typing import Any

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


class _ForceSwitch(
    CoordinatorEntity[PowerSaverCoordinator], SwitchEntity, RestoreEntity
):
    """Base class for force on/off override switches."""

    _attr_has_entity_name = True
    _force_property: str  # coordinator property name, e.g. "force_on_active"
    _set_method: str  # coordinator method name, e.g. "async_set_force_on"
    _log_label: str  # human-readable label for logging, e.g. "Always on"

    def __init__(
        self, coordinator: PowerSaverCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{self._attr_translation_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_NAME],
            manufacturer="Power Saver",
            model="Price Optimizer",
            entry_type="service",
        )

    @property
    def is_on(self) -> bool:
        """Return True if this force switch is active."""
        return getattr(self.coordinator, self._force_property)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Activate the force state."""
        await getattr(self.coordinator, self._set_method)(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Deactivate the force state (resume schedule)."""
        await getattr(self.coordinator, self._set_method)(False)

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state == "on":
            _LOGGER.info("Restoring %s state: ON", self._log_label)
            await getattr(self.coordinator, self._set_method)(True)


class ForceOnSwitch(_ForceSwitch):
    """Switch to force all controlled entities ON, bypassing the schedule."""

    _attr_translation_key = "force_on"
    _attr_icon = "mdi:hand-back-right"
    _force_property = "force_on_active"
    _set_method = "async_set_force_on"
    _log_label = "Always on"


class ForceOffSwitch(_ForceSwitch):
    """Switch to force all controlled entities OFF, bypassing the schedule."""

    _attr_translation_key = "force_off"
    _attr_icon = "mdi:hand-back-right-off"
    _force_property = "force_off_active"
    _set_method = "async_set_force_off"
    _log_label = "Always off"
