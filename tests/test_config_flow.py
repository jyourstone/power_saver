"""Tests for the Power Saver config flow."""

from __future__ import annotations

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.power_saver.const import (
    CONF_ALWAYS_CHEAP,
    CONF_ALWAYS_EXPENSIVE,
    CONF_MIN_HOURS,
    CONF_NAME,
    CONF_NORDPOOL_SENSOR,
    CONF_NORDPOOL_TYPE,
    CONF_ROLLING_WINDOW_HOURS,
    DOMAIN,
    NORDPOOL_TYPE_HACS,
    NORDPOOL_TYPE_NATIVE,
)

NORDPOOL_ENTITY = "sensor.nordpool_kwh_se4_sek"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of custom integrations for all tests in this module."""
    yield


@pytest.fixture
def setup_hacs_nordpool(hass: HomeAssistant):
    """Set up a fake HACS Nordpool sensor with raw_today attribute."""
    hass.states.async_set(
        NORDPOOL_ENTITY,
        "0.50",
        {
            "raw_today": [
                {
                    "start": "2026-02-06T00:00:00+01:00",
                    "end": "2026-02-06T01:00:00+01:00",
                    "value": 0.5,
                }
            ],
            "raw_tomorrow": [],
        },
    )


@pytest.fixture
async def setup_native_nordpool(hass: HomeAssistant):
    """Set up a fake native Nordpool integration with config entry and entity."""
    # Create a mock config entry for the nordpool domain
    nordpool_config_entry = MockConfigEntry(
        domain="nordpool",
        title="Nord Pool",
        entry_id="nordpool_test_entry",
    )
    nordpool_config_entry.add_to_hass(hass)

    # Register a sensor entity belonging to that config entry
    registry = er.async_get(hass)
    entity_entry = registry.async_get_or_create(
        domain="sensor",
        platform="nordpool",
        unique_id="se4_sek_current_price",
        suggested_object_id="nordpool_se4_sek_current_price",
        config_entry=nordpool_config_entry,
    )
    hass.states.async_set(
        entity_entry.entity_id, "0.45", {"unit_of_measurement": "SEK/kWh"}
    )
    return entity_entry


async def test_full_config_flow_hacs(hass: HomeAssistant, setup_hacs_nordpool):
    """Test a successful config flow with HACS Nordpool auto-detected."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Water Heater",
            CONF_MIN_HOURS: 6.0,
            CONF_ALWAYS_CHEAP: 0.05,
            CONF_ALWAYS_EXPENSIVE: 2.0,
            CONF_ROLLING_WINDOW_HOURS: 24.0,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Water Heater"
    assert result["data"] == {
        CONF_NORDPOOL_SENSOR: NORDPOOL_ENTITY,
        CONF_NORDPOOL_TYPE: NORDPOOL_TYPE_HACS,
        CONF_NAME: "Water Heater",
    }
    assert result["options"][CONF_MIN_HOURS] == 6.0
    assert result["options"][CONF_ALWAYS_CHEAP] == 0.05
    assert result["options"][CONF_ALWAYS_EXPENSIVE] == 2.0
    assert result["options"][CONF_ROLLING_WINDOW_HOURS] == 24.0


async def test_full_config_flow_native(hass: HomeAssistant, setup_native_nordpool):
    """Test a successful config flow with native Nordpool auto-detected."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Floor Heating",
            CONF_MIN_HOURS: 4.0,
            CONF_ALWAYS_CHEAP: 0.0,
            CONF_ALWAYS_EXPENSIVE: 0.0,
            CONF_ROLLING_WINDOW_HOURS: 24.0,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_NORDPOOL_TYPE] == NORDPOOL_TYPE_NATIVE
    assert result["data"][CONF_NORDPOOL_SENSOR] == setup_native_nordpool.entity_id


async def test_no_nordpool_found(hass: HomeAssistant):
    """Test validation when no Nordpool integration is present."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Test",
            CONF_MIN_HOURS: 2.5,
            CONF_ALWAYS_CHEAP: 0.0,
            CONF_ALWAYS_EXPENSIVE: 0.0,
            CONF_ROLLING_WINDOW_HOURS: 24.0,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert "base" in result["errors"]
    assert result["errors"]["base"] == "nordpool_not_found"
