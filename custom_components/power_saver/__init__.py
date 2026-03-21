"""The Power Saver integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr

try:
    from homeassistant.config_entries import OptionsFlowWithReload  # noqa: F401
    _OPTIONS_FLOW_RELOADS = True
except ImportError:
    _OPTIONS_FLOW_RELOADS = False

from .const import (
    ATTR_DEVICE_ID,
    ATTR_HOURS,
    DOMAIN,
    SERVICE_CLEAR_SCHEDULE_HOURS_OVERRIDE,
    SERVICE_SET_SCHEDULE_HOURS,
)
from .coordinator import PowerSaverCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]

SERVICE_SET_HOURS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): str,
        vol.Required(ATTR_HOURS): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=24)
        ),
    }
)

SERVICE_CLEAR_OVERRIDE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): str,
    }
)


def _find_coordinator(
    hass: HomeAssistant, device_id: str
) -> PowerSaverCoordinator:
    """Resolve a device_id to its PowerSaverCoordinator.

    Raises ValueError if the device doesn't belong to this integration.
    """
    registry = dr.async_get(hass)
    device = registry.async_get(device_id)
    if device is None:
        raise ValueError(f"Device {device_id} not found")
    # Find the config entry that belongs to Power Saver
    for entry_id in device.config_entries:
        coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
        if coordinator is not None:
            return coordinator
    raise ValueError(
        f"Device {device_id} is not a Power Saver device"
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Power Saver from a config entry."""
    coordinator = PowerSaverCoordinator(hass, entry)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Refresh schedule when user changes options.
    # OptionsFlowWithReload (HA 2025.x+) auto-reloads the entry, so a manual
    # update listener must only be registered on older HA versions.
    if not _OPTIONS_FLOW_RELOADS:
        entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services once (on first entry setup).
    if not hass.services.has_service(DOMAIN, SERVICE_SET_SCHEDULE_HOURS):
        async def handle_set_schedule_hours(call: ServiceCall) -> None:
            """Handle the set_schedule_hours service call."""
            device_id = call.data[ATTR_DEVICE_ID]
            hours = call.data[ATTR_HOURS]
            coord = _find_coordinator(hass, device_id)
            await coord.async_set_hours_override(hours)

        async def handle_clear_override(call: ServiceCall) -> None:
            """Handle the clear_schedule_hours_override service call."""
            device_id = call.data[ATTR_DEVICE_ID]
            coord = _find_coordinator(hass, device_id)
            await coord.async_clear_hours_override()

        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_SCHEDULE_HOURS,
            handle_set_schedule_hours,
            schema=SERVICE_SET_HOURS_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_CLEAR_SCHEDULE_HOURS_OVERRIDE,
            handle_clear_override,
            schema=SERVICE_CLEAR_OVERRIDE_SCHEMA,
        )

    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle options update — trigger coordinator refresh."""
    coordinator: PowerSaverCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    # Remove services when the last entry is unloaded.
    if not hass.data.get(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_SET_SCHEDULE_HOURS)
        hass.services.async_remove(DOMAIN, SERVICE_CLEAR_SCHEDULE_HOURS_OVERRIDE)

    return unload_ok
