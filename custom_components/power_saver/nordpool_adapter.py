"""Adapter for fetching prices from HACS Nordpool or native HA Nordpool."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import NORDPOOL_TYPE_HACS, NORDPOOL_TYPE_NATIVE

_LOGGER = logging.getLogger(__name__)


def detect_nordpool_type(hass: HomeAssistant, entity_id: str) -> str:
    """Detect whether an entity is a HACS Nordpool or native HA Nordpool sensor.

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


def auto_detect_nordpool(
    hass: HomeAssistant,
) -> tuple[str, str] | tuple[None, None]:
    """Auto-detect a Nordpool integration (HACS or native).

    Checks for HACS Nordpool first (entity with raw_today attribute),
    then falls back to native HA Nordpool (config entry with domain "nordpool").

    Returns:
        Tuple of (entity_id, nordpool_type) or (None, None) if not found.
    """
    # Check for HACS nordpool: any sensor with raw_today attribute
    for state in hass.states.async_all("sensor"):
        if state.attributes.get("raw_today") is not None:
            _LOGGER.debug("Auto-detected HACS Nordpool sensor: %s", state.entity_id)
            return state.entity_id, NORDPOOL_TYPE_HACS

    # Check for native nordpool: config entry with domain "nordpool"
    entries = hass.config_entries.async_entries("nordpool")
    if entries:
        config_entry = entries[0]
        registry = er.async_get(hass)
        entity_entries = er.async_entries_for_config_entry(
            registry, config_entry.entry_id
        )
        # Pick the first sensor entity for state change listening
        for entity_entry in entity_entries:
            if entity_entry.domain == "sensor":
                _LOGGER.debug(
                    "Auto-detected native Nordpool sensor: %s",
                    entity_entry.entity_id,
                )
                return entity_entry.entity_id, NORDPOOL_TYPE_NATIVE

    return None, None


async def async_get_prices(
    hass: HomeAssistant,
    entity_id: str,
    nordpool_type: str,
) -> tuple[list[dict], list[dict]]:
    """Fetch today's and tomorrow's prices, normalized to [{start, end, value}].

    Args:
        hass: Home Assistant instance.
        entity_id: The Nordpool sensor entity ID.
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
    """Read prices from HACS Nordpool sensor attributes."""
    state = hass.states.get(entity_id)
    if state is None:
        return [], []

    raw_today = state.attributes.get("raw_today") or []
    raw_tomorrow = state.attributes.get("raw_tomorrow") or []
    return raw_today, raw_tomorrow


async def _async_get_native_prices(
    hass: HomeAssistant, entity_id: str
) -> tuple[list[dict], list[dict]]:
    """Fetch prices from native HA Nordpool via service call."""
    registry = er.async_get(hass)
    entity_entry = registry.async_get(entity_id)
    if entity_entry is None or entity_entry.config_entry_id is None:
        _LOGGER.error(
            "Cannot find config entry for native Nordpool entity %s", entity_id
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
    except Exception:
        _LOGGER.debug(
            "Failed to fetch native Nordpool prices for %s (may not be available yet)",
            target_date,
        )
        return []

    if not response:
        return []

    return _convert_native_response(response)


def _convert_native_response(response: dict) -> list[dict]:
    """Convert native Nordpool service response to HACS-compatible format.

    Native response is grouped by area: {"SE4": [{"start": ..., "end": ..., "price": ...}, ...]}
    We pick the first area and convert price from Currency/MWh to Currency/kWh.
    """
    # The response may be a dict keyed by area or a list directly
    price_list: list[dict] = []

    if isinstance(response, dict):
        # Grouped by area — pick the first area
        for area, prices in response.items():
            if isinstance(prices, list):
                price_list = prices
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
                if isinstance(start, datetime):
                    end = start + timedelta(hours=1)
                elif isinstance(start, str):
                    end = (
                        datetime.fromisoformat(start) + timedelta(hours=1)
                    ).isoformat()

            converted.append({
                "start": start,
                "end": end,
                "value": price_kwh,
            })
        except (ValueError, TypeError) as exc:
            _LOGGER.warning("Error converting native Nordpool entry: %s", exc)
            continue

    return converted
