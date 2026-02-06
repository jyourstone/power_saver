"""Tests for the Power Saver config flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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


@pytest.fixture
def mock_nordpool_state():
    """Create a mock Nordpool sensor state."""
    state = MagicMock()
    state.attributes = {
        "raw_today": [{"start": "2026-02-06T00:00:00+01:00", "end": "2026-02-06T01:00:00+01:00", "value": 0.5}],
        "raw_tomorrow": [],
    }
    return state


async def test_full_config_flow(hass: HomeAssistant, mock_nordpool_state):
    """Test a successful config flow."""
    with patch.object(hass.states, "get", return_value=mock_nordpool_state):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch.object(hass.states, "get", return_value=mock_nordpool_state):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "Water Heater",
                CONF_NORDPOOL_SENSOR: "sensor.nordpool_kwh_se4_sek",
                CONF_MIN_HOURS: 6.0,
                CONF_ALWAYS_CHEAP: 0.05,
                CONF_ALWAYS_EXPENSIVE: 2.0,
                CONF_ROLLING_WINDOW_HOURS: 24.0,
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Water Heater"
    assert result["data"] == {
        CONF_NORDPOOL_SENSOR: "sensor.nordpool_kwh_se4_sek",
        CONF_NAME: "Water Heater",
    }
    assert result["options"] == {
        CONF_MIN_HOURS: 6.0,
        CONF_ALWAYS_CHEAP: 0.05,
        CONF_ALWAYS_EXPENSIVE: 2.0,
        CONF_ROLLING_WINDOW_HOURS: 24.0,
    }


async def test_invalid_nordpool_sensor(hass: HomeAssistant):
    """Test validation when Nordpool sensor is missing raw_today."""
    # State exists but has no raw_today attribute
    bad_state = MagicMock()
    bad_state.attributes = {}

    with patch.object(hass.states, "get", return_value=bad_state):
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
                CONF_ROLLING_WINDOW_HOURS: 0.0,
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert "nordpool_sensor" in result["errors"]


async def test_invalid_rolling_window_config(hass: HomeAssistant, mock_nordpool_state):
    """Test validation when rolling window is set but min_hours is 0."""
    with patch.object(hass.states, "get", return_value=mock_nordpool_state):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "Test",
                CONF_NORDPOOL_SENSOR: "sensor.nordpool_kwh_se4_sek",
                CONF_MIN_HOURS: 0.0,  # Invalid: must be > 0 when rolling window is set
                CONF_ALWAYS_CHEAP: 0.0,
                CONF_ALWAYS_EXPENSIVE: 0.0,
                CONF_ROLLING_WINDOW_HOURS: 8.0,
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert "rolling_window_hours" in result["errors"]
