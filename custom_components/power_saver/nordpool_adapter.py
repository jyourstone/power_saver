"""Adapter for fetching prices from HACS Nordpool or native HA Nordpool."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import NORDPOOL_TYPE_HACS, NORDPOOL_TYPE_NATIVE

_LOGGER = logging.getLogger(__name__)


def detect_nordpool_type(hass: HomeAssistant, entity_id: str) -> str:
    """Detect whether an entity is a HACS Nord Pool or native HA Nord Pool sensor.

    Returns:
        "hacs", "native", or "unknown".
    """
    state = hass.states.get(entity_id)
    if state is not None and state.attributes.get("raw_today") is not None:
        return NORDPOOL_TYPE_HACS

    registry = er.async_get(hass)
    entity_entry = registry.async_get(entity_id)
    if entity_entry is not None and entity_entry.platform == "nordpool":
        return NORDPOOL_TYPE_NATIVE

    return "unknown"


def _get_friendly_name(hass: HomeAssistant, entity_id: str) -> str:
    """Get the friendly name for an entity, falling back to entity_id."""
    state = hass.states.get(entity_id)
    if state is not None:
        return state.attributes.get("friendly_name", entity_id)
    return entity_id


def find_all_nordpool_sensors(
    hass: HomeAssistant,
) -> list[tuple[str, str, str]]:
    """Find all available Nord Pool sensors (HACS and native).

    For native Nord Pool, only returns the main "current price" sensor per
    config entry (filters out diagnostic/statistical sensors).

    Returns:
        List of (entity_id, nordpool_type, label) tuples.
    """
    registry = er.async_get(hass)
    found: list[tuple[str, str, str]] = []
    seen_entity_ids: set[str] = set()

    # Check for HACS Nord Pool: nordpool platform sensor with raw_today attribute
    for entity_entry in registry.entities.values():
        if entity_entry.domain != "sensor" or entity_entry.platform != "nordpool":
            continue
        state = hass.states.get(entity_entry.entity_id)
        if state is not None and state.attributes.get("raw_today") is not None:
            label = _get_friendly_name(hass, entity_entry.entity_id)
            _LOGGER.debug("Found HACS Nord Pool sensor: %s", entity_entry.entity_id)
            found.append((entity_entry.entity_id, NORDPOOL_TYPE_HACS, label))
            seen_entity_ids.add(entity_entry.entity_id)

    # Check for native Nord Pool: all config entries with domain "nordpool"
    # Native unique_id format: "{area}-{key}" — only include "current_price" sensors
    for config_entry in hass.config_entries.async_entries("nordpool"):
        entity_entries = er.async_entries_for_config_entry(
            registry, config_entry.entry_id
        )
        for entity_entry in entity_entries:
            if (
                entity_entry.domain == "sensor"
                and entity_entry.entity_id not in seen_entity_ids
                and entity_entry.unique_id is not None
                and entity_entry.unique_id.endswith("-current_price")
            ):
                label = _get_friendly_name(hass, entity_entry.entity_id)
                _LOGGER.debug(
                    "Found native Nord Pool sensor: %s",
                    entity_entry.entity_id,
                )
                found.append((entity_entry.entity_id, NORDPOOL_TYPE_NATIVE, label))
                seen_entity_ids.add(entity_entry.entity_id)

    return found


def auto_detect_nordpool(
    hass: HomeAssistant,
) -> tuple[str, str] | tuple[None, None]:
    """Auto-detect a Nord Pool integration (HACS or native).

    Checks for HACS Nord Pool first (entity with raw_today attribute),
    then falls back to native HA Nord Pool (config entry with domain "nordpool").

    Returns:
        Tuple of (entity_id, nordpool_type) or (None, None) if not found.
    """
    sensors = find_all_nordpool_sensors(hass)
    if sensors:
        entity_id, nordpool_type, _label = sensors[0]
        return entity_id, nordpool_type
    return None, None


async def async_get_prices(
    hass: HomeAssistant,
    entity_id: str,
    nordpool_type: str,
) -> tuple[list[dict], list[dict]]:
    """Fetch today's and tomorrow's prices, normalized to [{start, end, value}].

    Args:
        hass: Home Assistant instance.
        entity_id: The Nord Pool sensor entity ID.
        nordpool_type: "hacs" or "native".

    Returns:
        Tuple of (raw_today, raw_tomorrow) in HACS-compatible format.
    """
    if nordpool_type == NORDPOOL_TYPE_HACS:
        return _get_hacs_prices(hass, entity_id)
    if nordpool_type == NORDPOOL_TYPE_NATIVE:
        return await _async_get_native_prices(hass, entity_id)

    _LOGGER.error("Unknown nordpool_type: %s", nordpool_type)
    return [], []


def _get_hacs_prices(
    hass: HomeAssistant, entity_id: str
) -> tuple[list[dict], list[dict]]:
    """Read prices from HACS Nord Pool sensor attributes."""
    state = hass.states.get(entity_id)
    if state is None:
        return [], []

    raw_today = state.attributes.get("raw_today") or []
    raw_tomorrow = state.attributes.get("raw_tomorrow") or []
    return raw_today, raw_tomorrow


async def _async_get_native_prices(
    hass: HomeAssistant, entity_id: str
) -> tuple[list[dict], list[dict]]:
    """Fetch prices from native HA Nord Pool via service call."""
    registry = er.async_get(hass)
    entity_entry = registry.async_get(entity_id)
    if entity_entry is None or entity_entry.config_entry_id is None:
        _LOGGER.error(
            "Cannot find config entry for native Nord Pool entity %s", entity_id
        )
        return [], []

    config_entry_id = entity_entry.config_entry_id
    today = dt_util.now().date()
    tomorrow = today + timedelta(days=1)

    raw_today = await _async_fetch_native_date(hass, config_entry_id, today)
    raw_tomorrow = await _async_fetch_native_date(hass, config_entry_id, tomorrow)

    return raw_today, raw_tomorrow


async def _async_fetch_native_date(
    hass: HomeAssistant, config_entry_id: str, target_date: date
) -> list[dict]:
    """Call nordpool.get_prices_for_date and convert to standard format."""
    try:
        response = await hass.services.async_call(
            "nordpool",
            "get_prices_for_date",
            {
                "config_entry": config_entry_id,
                "date": str(target_date),
            },
            blocking=True,
            return_response=True,
        )
    except (HomeAssistantError, KeyError, ValueError):
        _LOGGER.debug(
            "Failed to fetch native Nord Pool prices for %s (may not be available yet)",
            target_date,
            exc_info=True,
        )
        return []

    if not response:
        return []

    return _convert_native_response(response)


def _convert_native_response(response: dict) -> list[dict]:
    """Convert native Nord Pool service response to HACS-compatible format.

    Native response is grouped by area: {"SE4": [{"start": ..., "end": ..., "price": ...}, ...]}
    We pick the first area and convert price from Currency/MWh to Currency/kWh.
    """
    # The response may be a dict keyed by area or a list directly
    price_list: list[dict] = []

    if isinstance(response, dict):
        # Grouped by area — pick the first area
        for _area, prices in response.items():
            if isinstance(prices, list):
                price_list = prices
                _LOGGER.debug("Using prices from area: %s", _area)
                break
    elif isinstance(response, list):
        price_list = response

    if not price_list:
        return []

    converted: list[dict] = []
    for entry in price_list:
        try:
            start = entry.get("start")
            end = entry.get("end")
            # Native uses "price" in Currency/MWh
            price_mwh = entry.get("price")

            if start is None or price_mwh is None:
                continue

            # Convert MWh to kWh
            price_kwh = float(price_mwh) / 1000.0

            # If no explicit end, assume 1-hour slots
            if end is None:
                start_dt = (
                    start
                    if isinstance(start, datetime)
                    else datetime.fromisoformat(start)
                )
                end_dt = start_dt + timedelta(hours=1)
                # Preserve the same type as start
                end = end_dt if isinstance(start, datetime) else end_dt.isoformat()

            converted.append({
                "start": start,
                "end": end,
                "value": price_kwh,
            })
        except (ValueError, TypeError) as exc:
            _LOGGER.warning("Error converting native Nord Pool entry: %s", exc)
            continue

    return converted
