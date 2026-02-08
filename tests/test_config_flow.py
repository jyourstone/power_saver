"""Tests for the Power Saver config flow."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.power_saver.const import (
    CONF_ALWAYS_CHEAP,
    CONF_ALWAYS_EXPENSIVE,
    CONF_MIN_CONSECUTIVE_HOURS,
    CONF_MIN_HOURS,
    CONF_NAME,
    CONF_NORDPOOL_SENSOR,
    CONF_NORDPOOL_TYPE,
    CONF_PRICE_SIMILARITY_PCT,
    CONF_ROLLING_WINDOW_HOURS,
    CONF_SELECTION_MODE,
    DOMAIN,
    NORDPOOL_TYPE_HACS,
    NORDPOOL_TYPE_NATIVE,
    SELECTION_MODE_CHEAPEST,
    SELECTION_MODE_MOST_EXPENSIVE,
)

NORDPOOL_ENTITY = "sensor.nordpool_kwh_se4_sek"
NORDPOOL_ENTITY_SE3 = "sensor.nordpool_kwh_se3_sek"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of custom integrations for all tests in this module."""
    yield


@pytest.fixture
async def setup_hacs_nordpool(hass: HomeAssistant):
    """Set up a fake HACS Nordpool sensor with raw_today attribute."""
    # Create a mock config entry for the nordpool HACS integration
    nordpool_config_entry = MockConfigEntry(
        domain="nordpool",
        title="Nordpool HACS",
        entry_id="nordpool_hacs_entry",
    )
    nordpool_config_entry.add_to_hass(hass)

    # Register the entity in the entity registry (auto_detect searches the registry)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        domain="sensor",
        platform="nordpool",
        unique_id="kwh_se4_sek",
        suggested_object_id="nordpool_kwh_se4_sek",
        config_entry=nordpool_config_entry,
    )

    # Set the state with raw_today attribute (HACS signature)
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
    # Native unique_id format: "{area}-{key}"
    registry = er.async_get(hass)
    entity_entry = registry.async_get_or_create(
        domain="sensor",
        platform="nordpool",
        unique_id="se4-current_price",
        suggested_object_id="nordpool_se4_sek_current_price",
        config_entry=nordpool_config_entry,
    )
    hass.states.async_set(
        entity_entry.entity_id, "0.45", {"unit_of_measurement": "SEK/kWh"}
    )
    return entity_entry


@pytest.fixture
async def setup_two_native_nordpool(hass: HomeAssistant):
    """Set up two native Nordpool sensors (different price regions)."""
    registry = er.async_get(hass)

    # First config entry (SE4)
    entry_se4 = MockConfigEntry(
        domain="nordpool",
        title="Nord Pool SE4",
        entry_id="nordpool_se4_entry",
    )
    entry_se4.add_to_hass(hass)
    entity_se4 = registry.async_get_or_create(
        domain="sensor",
        platform="nordpool",
        unique_id="se4-current_price",
        suggested_object_id="nordpool_kwh_se4_sek",
        config_entry=entry_se4,
    )
    hass.states.async_set(
        entity_se4.entity_id, "0.45", {"unit_of_measurement": "SEK/kWh"}
    )

    # Second config entry (SE3)
    entry_se3 = MockConfigEntry(
        domain="nordpool",
        title="Nord Pool SE3",
        entry_id="nordpool_se3_entry",
    )
    entry_se3.add_to_hass(hass)
    entity_se3 = registry.async_get_or_create(
        domain="sensor",
        platform="nordpool",
        unique_id="se3-current_price",
        suggested_object_id="nordpool_kwh_se3_sek",
        config_entry=entry_se3,
    )
    hass.states.async_set(
        entity_se3.entity_id, "0.50", {"unit_of_measurement": "SEK/kWh"}
    )

    return entity_se4, entity_se3


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
            CONF_NORDPOOL_SENSOR: NORDPOOL_ENTITY,
            CONF_NAME: "Water Heater",
            CONF_SELECTION_MODE: SELECTION_MODE_CHEAPEST,
            CONF_MIN_HOURS: 6.0,
            CONF_ALWAYS_CHEAP: 0.05,
            CONF_ALWAYS_EXPENSIVE: 2.0,
            CONF_ROLLING_WINDOW_HOURS: 24.0,
            CONF_PRICE_SIMILARITY_PCT: 10.0,
            CONF_MIN_CONSECUTIVE_HOURS: 2,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Water Heater"
    assert result["data"] == {
        CONF_NORDPOOL_SENSOR: NORDPOOL_ENTITY,
        CONF_NORDPOOL_TYPE: NORDPOOL_TYPE_HACS,
        CONF_NAME: "Water Heater",
    }
    assert result["options"][CONF_SELECTION_MODE] == SELECTION_MODE_CHEAPEST
    assert result["options"][CONF_MIN_HOURS] == 6.0
    assert result["options"][CONF_ALWAYS_CHEAP] == 0.05
    assert result["options"][CONF_ALWAYS_EXPENSIVE] == 2.0
    assert result["options"][CONF_ROLLING_WINDOW_HOURS] == 24.0
    assert result["options"][CONF_PRICE_SIMILARITY_PCT] == 10.0
    assert result["options"][CONF_MIN_CONSECUTIVE_HOURS] == 2


async def test_full_config_flow_native(hass: HomeAssistant, setup_native_nordpool):
    """Test a successful config flow with native Nordpool auto-detected."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NORDPOOL_SENSOR: setup_native_nordpool.entity_id,
            CONF_NAME: "Floor Heating",
            CONF_MIN_HOURS: 4.0,
            CONF_ROLLING_WINDOW_HOURS: 24.0,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_NORDPOOL_TYPE] == NORDPOOL_TYPE_NATIVE
    assert result["data"][CONF_NORDPOOL_SENSOR] == setup_native_nordpool.entity_id
    # Optional fields left empty should store as None (disabled)
    assert result["options"][CONF_ALWAYS_CHEAP] is None
    assert result["options"][CONF_ALWAYS_EXPENSIVE] is None
    assert result["options"][CONF_PRICE_SIMILARITY_PCT] is None
    assert result["options"][CONF_MIN_CONSECUTIVE_HOURS] is None


async def test_config_flow_most_expensive_mode(hass: HomeAssistant, setup_hacs_nordpool):
    """Test config flow with most_expensive selection mode."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NORDPOOL_SENSOR: NORDPOOL_ENTITY,
            CONF_NAME: "Grid Sell",
            CONF_SELECTION_MODE: SELECTION_MODE_MOST_EXPENSIVE,
            CONF_MIN_HOURS: 3.0,
            CONF_ROLLING_WINDOW_HOURS: 24.0,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_SELECTION_MODE] == SELECTION_MODE_MOST_EXPENSIVE


async def test_no_nordpool_found(hass: HomeAssistant):
    """Test that the form shows an error when no Nordpool integration is present."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "nordpool_not_found"


async def test_multiple_sensors_user_selects(
    hass: HomeAssistant, setup_two_native_nordpool
):
    """Test that user can select between multiple Nordpool sensors."""
    _entity_se4, entity_se3 = setup_two_native_nordpool

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM

    # User selects the SE3 sensor
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NORDPOOL_SENSOR: entity_se3.entity_id,
            CONF_NAME: "Floor Heating SE3",
            CONF_MIN_HOURS: 4.0,
            CONF_ROLLING_WINDOW_HOURS: 24.0,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_NORDPOOL_SENSOR] == entity_se3.entity_id
    assert result["data"][CONF_NORDPOOL_TYPE] == NORDPOOL_TYPE_NATIVE


async def test_options_flow_change_nordpool_sensor(
    hass: HomeAssistant, setup_two_native_nordpool
):
    """Test changing the Nordpool sensor via the options flow."""
    entity_se4, entity_se3 = setup_two_native_nordpool

    # Create an existing config entry using SE4
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Water Heater",
        data={
            CONF_NORDPOOL_SENSOR: entity_se4.entity_id,
            CONF_NORDPOOL_TYPE: NORDPOOL_TYPE_NATIVE,
            CONF_NAME: "Water Heater",
        },
        options={
            CONF_SELECTION_MODE: SELECTION_MODE_CHEAPEST,
            CONF_MIN_HOURS: 4.0,
            CONF_ROLLING_WINDOW_HOURS: 24.0,
        },
    )
    config_entry.add_to_hass(hass)

    # Start options flow
    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    # Change sensor from SE4 to SE3
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_NORDPOOL_SENSOR: entity_se3.entity_id,
            CONF_SELECTION_MODE: SELECTION_MODE_CHEAPEST,
            CONF_MIN_HOURS: 4.0,
            CONF_ROLLING_WINDOW_HOURS: 24.0,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY

    # Verify data was updated with new sensor
    assert config_entry.data[CONF_NORDPOOL_SENSOR] == entity_se3.entity_id
    assert config_entry.data[CONF_NORDPOOL_TYPE] == NORDPOOL_TYPE_NATIVE


async def test_options_flow_rejects_invalid_sensor(
    hass: HomeAssistant, setup_two_native_nordpool
):
    """Test that options flow rejects a sensor whose type can't be detected."""
    entity_se4, entity_se3 = setup_two_native_nordpool

    # Create an existing config entry using SE4
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Water Heater",
        data={
            CONF_NORDPOOL_SENSOR: entity_se4.entity_id,
            CONF_NORDPOOL_TYPE: NORDPOOL_TYPE_NATIVE,
            CONF_NAME: "Water Heater",
        },
        options={
            CONF_SELECTION_MODE: SELECTION_MODE_CHEAPEST,
            CONF_MIN_HOURS: 4.0,
            CONF_ROLLING_WINDOW_HOURS: 24.0,
        },
    )
    config_entry.add_to_hass(hass)

    # Start options flow (renders dropdown with both SE4 and SE3)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    # Simulate: SE3 sensor becomes undetectable between form display and submission
    with patch(
        "custom_components.power_saver.config_flow.detect_nordpool_type",
        return_value="unknown",
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_NORDPOOL_SENSOR: entity_se3.entity_id,
                CONF_SELECTION_MODE: SELECTION_MODE_CHEAPEST,
                CONF_MIN_HOURS: 4.0,
                CONF_ROLLING_WINDOW_HOURS: 24.0,
            },
        )

    # Should re-show the form with an error, not create an entry
    assert result["type"] is FlowResultType.FORM
    assert result["errors"][CONF_NORDPOOL_SENSOR] == "nordpool_not_found"

    # Verify original data was NOT changed
    assert config_entry.data[CONF_NORDPOOL_SENSOR] == entity_se4.entity_id
    assert config_entry.data[CONF_NORDPOOL_TYPE] == NORDPOOL_TYPE_NATIVE
