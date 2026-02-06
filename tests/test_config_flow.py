"""Tests for the Power Saver config flow."""

from __future__ import annotations

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.power_saver.const import (
    CONF_ALWAYS_CHEAP,
    CONF_ALWAYS_EXPENSIVE,
    CONF_MIN_HOURS,
    CONF_NAME,
    CONF_NORDPOOL_SENSOR,
    CONF_ROLLING_WINDOW_HOURS,
    DOMAIN,
)

NORDPOOL_ENTITY = "sensor.nordpool_kwh_se4_sek"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of custom integrations for all tests in this module."""
    yield


@pytest.fixture
def setup_nordpool(hass: HomeAssistant):
    """Set up a fake Nordpool sensor with raw_today attribute."""
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


async def test_full_config_flow(hass: HomeAssistant, setup_nordpool):
    """Test a successful config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Water Heater",
            CONF_NORDPOOL_SENSOR: NORDPOOL_ENTITY,
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
        CONF_NAME: "Water Heater",
    }
    assert result["options"][CONF_MIN_HOURS] == 6.0
    assert result["options"][CONF_ALWAYS_CHEAP] == 0.05
    assert result["options"][CONF_ALWAYS_EXPENSIVE] == 2.0
    assert result["options"][CONF_ROLLING_WINDOW_HOURS] == 24.0


async def test_invalid_nordpool_sensor(hass: HomeAssistant):
    """Test validation when Nordpool sensor is missing raw_today."""
    # State exists but has no raw_today attribute
    hass.states.async_set("sensor.bad_sensor", "0.0", {})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Test",
            CONF_NORDPOOL_SENSOR: "sensor.bad_sensor",
            CONF_MIN_HOURS: 2.5,
            CONF_ALWAYS_CHEAP: 0.0,
            CONF_ALWAYS_EXPENSIVE: 0.0,
            CONF_ROLLING_WINDOW_HOURS: 24.0,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert "nordpool_sensor" in result["errors"]
