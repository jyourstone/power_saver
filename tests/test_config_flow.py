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
    CONF_CONTROLLED_ENTITIES,
    CONF_EXCLUDE_FROM,
    CONF_EXCLUDE_UNTIL,
    CONF_HOURS_PER_PERIOD,
    CONF_ROLLING_WINDOW,
    CONF_MIN_CONSECUTIVE_HOURS,
    CONF_MIN_HOURS_ON,
    CONF_NAME,
    CONF_NORDPOOL_SENSOR,
    CONF_NORDPOOL_TYPE,
    CONF_PERIOD_FROM,
    CONF_PERIOD_TO,
    CONF_PRICE_SIMILARITY_PCT,
    CONF_SELECTION_MODE,
    CONF_STRATEGY,
    DEFAULT_HOURS_PER_PERIOD,
    DEFAULT_ROLLING_WINDOW,
    DEFAULT_MIN_HOURS_ON,
    DEFAULT_PERIOD_FROM,
    DEFAULT_PERIOD_TO,
    DEFAULT_SELECTION_MODE,
    DEFAULT_STRATEGY,
    DOMAIN,
    NORDPOOL_TYPE_HACS,
    NORDPOOL_TYPE_NATIVE,
    SELECTION_MODE_CHEAPEST,
    SELECTION_MODE_MOST_EXPENSIVE,
    STRATEGY_LOWEST_PRICE,
    STRATEGY_MINIMUM_RUNTIME,
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
    nordpool_config_entry = MockConfigEntry(
        domain="nordpool",
        title="Nordpool HACS",
        entry_id="nordpool_hacs_entry",
    )
    nordpool_config_entry.add_to_hass(hass)

    registry = er.async_get(hass)
    registry.async_get_or_create(
        domain="sensor",
        platform="nordpool",
        unique_id="kwh_se4_sek",
        suggested_object_id="nordpool_kwh_se4_sek",
        config_entry=nordpool_config_entry,
    )

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
    nordpool_config_entry = MockConfigEntry(
        domain="nordpool",
        title="Nord Pool",
        entry_id="nordpool_test_entry",
    )
    nordpool_config_entry.add_to_hass(hass)

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


# --- Initial config flow tests (3-step: user → strategy → common_options) ---


async def test_full_config_flow_lowest_price(hass: HomeAssistant, setup_hacs_nordpool):
    """Test config flow: user → lowest_price → common_options."""
    # Step 1: user
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
            CONF_STRATEGY: STRATEGY_LOWEST_PRICE,
        },
    )

    # Step 2: lowest_price
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "lowest_price"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOURS_PER_PERIOD: 4.0,
            CONF_PERIOD_FROM: "00:00:00",
            CONF_PERIOD_TO: "00:00:00",
        },
    )

    # Step 3: common_options
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "common_options"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SELECTION_MODE: SELECTION_MODE_CHEAPEST,
            CONF_ALWAYS_CHEAP: 0.05,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Water Heater"
    assert result["data"] == {
        CONF_NORDPOOL_SENSOR: NORDPOOL_ENTITY,
        CONF_NORDPOOL_TYPE: NORDPOOL_TYPE_HACS,
        CONF_NAME: "Water Heater",
    }
    assert result["options"][CONF_STRATEGY] == STRATEGY_LOWEST_PRICE
    assert result["options"][CONF_SELECTION_MODE] == SELECTION_MODE_CHEAPEST
    assert result["options"][CONF_HOURS_PER_PERIOD] == 4.0
    assert result["options"][CONF_PERIOD_FROM] == "00:00:00"
    assert result["options"][CONF_PERIOD_TO] == "00:00:00"
    assert result["options"][CONF_ALWAYS_CHEAP] == 0.05


async def test_full_config_flow_minimum_runtime(hass: HomeAssistant, setup_hacs_nordpool):
    """Test config flow: user → minimum_runtime → common_options."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NORDPOOL_SENSOR: NORDPOOL_ENTITY,
            CONF_NAME: "Water Heater",
            CONF_STRATEGY: STRATEGY_MINIMUM_RUNTIME,
        },
    )

    # Step 2: minimum_runtime
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "minimum_runtime"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_ROLLING_WINDOW: 26.0,
            CONF_MIN_HOURS_ON: 2.0,
        },
    )

    # Step 3: common_options
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "common_options"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SELECTION_MODE: SELECTION_MODE_CHEAPEST,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_STRATEGY] == STRATEGY_MINIMUM_RUNTIME
    assert result["options"][CONF_ROLLING_WINDOW] == 26.0
    assert result["options"][CONF_MIN_HOURS_ON] == 2.0


async def test_full_config_flow_native(hass: HomeAssistant, setup_native_nordpool):
    """Test config flow with native Nordpool auto-detected."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NORDPOOL_SENSOR: setup_native_nordpool.entity_id,
            CONF_NAME: "Floor Heating",
            CONF_STRATEGY: STRATEGY_LOWEST_PRICE,
        },
    )

    # Step 2: lowest_price
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOURS_PER_PERIOD: 6.0,
            CONF_PERIOD_FROM: "00:00:00",
            CONF_PERIOD_TO: "00:00:00",
        },
    )

    # Step 3: common_options
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "common_options"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SELECTION_MODE: SELECTION_MODE_CHEAPEST,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_NORDPOOL_TYPE] == NORDPOOL_TYPE_NATIVE
    assert result["data"][CONF_NORDPOOL_SENSOR] == setup_native_nordpool.entity_id


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

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NORDPOOL_SENSOR: entity_se3.entity_id,
            CONF_NAME: "Floor Heating SE3",
            CONF_STRATEGY: STRATEGY_LOWEST_PRICE,
        },
    )

    # Step 2: lowest_price
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOURS_PER_PERIOD: 4.0,
            CONF_PERIOD_FROM: "00:00:00",
            CONF_PERIOD_TO: "00:00:00",
        },
    )

    # Step 3: common_options
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "common_options"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SELECTION_MODE: SELECTION_MODE_CHEAPEST,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_NORDPOOL_SENSOR] == entity_se3.entity_id
    assert result["data"][CONF_NORDPOOL_TYPE] == NORDPOOL_TYPE_NATIVE


# --- Options flow tests (3-step: init → strategy → common_options) ---


def _make_config_entry(
    hass: HomeAssistant,
    entity_id: str = NORDPOOL_ENTITY,
    nordpool_type: str = NORDPOOL_TYPE_HACS,
    strategy: str = STRATEGY_LOWEST_PRICE,
) -> MockConfigEntry:
    """Create a config entry with standard defaults."""
    options = {
        CONF_STRATEGY: strategy,
        CONF_SELECTION_MODE: SELECTION_MODE_CHEAPEST,
    }
    if strategy == STRATEGY_LOWEST_PRICE:
        options[CONF_HOURS_PER_PERIOD] = 4.0
        options[CONF_PERIOD_FROM] = DEFAULT_PERIOD_FROM
        options[CONF_PERIOD_TO] = DEFAULT_PERIOD_TO
    else:
        options[CONF_ROLLING_WINDOW] = DEFAULT_ROLLING_WINDOW
        options[CONF_MIN_HOURS_ON] = DEFAULT_MIN_HOURS_ON

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Water Heater",
        version=3,
        data={
            CONF_NORDPOOL_SENSOR: entity_id,
            CONF_NORDPOOL_TYPE: nordpool_type,
            CONF_NAME: "Water Heater",
        },
        options=options,
    )
    config_entry.add_to_hass(hass)
    return config_entry


async def test_options_flow_lowest_price(hass: HomeAssistant, setup_hacs_nordpool):
    """Test options flow: init → lowest_price → common_options."""
    config_entry = _make_config_entry(hass)

    # Step 1: init
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_NORDPOOL_SENSOR: NORDPOOL_ENTITY,
            CONF_STRATEGY: STRATEGY_LOWEST_PRICE,
        },
    )

    # Step 2: lowest_price
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "lowest_price"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_HOURS_PER_PERIOD: 6.0,
            CONF_PERIOD_FROM: "06:00:00",
            CONF_PERIOD_TO: "22:00:00",
            CONF_MIN_CONSECUTIVE_HOURS: 2.0,
        },
    )

    # Step 3: common_options
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "common_options"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SELECTION_MODE: SELECTION_MODE_CHEAPEST,
            CONF_ALWAYS_CHEAP: 0.05,
            CONF_ALWAYS_EXPENSIVE: 2.0,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    opts = config_entry.options
    assert opts[CONF_STRATEGY] == STRATEGY_LOWEST_PRICE
    assert opts[CONF_HOURS_PER_PERIOD] == 6.0
    assert opts[CONF_PERIOD_FROM] == "06:00:00"
    assert opts[CONF_PERIOD_TO] == "22:00:00"
    assert opts[CONF_MIN_CONSECUTIVE_HOURS] == 2.0
    assert opts[CONF_ALWAYS_CHEAP] == 0.05
    assert opts[CONF_ALWAYS_EXPENSIVE] == 2.0


async def test_options_flow_minimum_runtime(hass: HomeAssistant, setup_hacs_nordpool):
    """Test options flow: init → minimum_runtime → common_options."""
    config_entry = _make_config_entry(hass, strategy=STRATEGY_MINIMUM_RUNTIME)

    # Step 1: init
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_NORDPOOL_SENSOR: NORDPOOL_ENTITY,
            CONF_STRATEGY: STRATEGY_MINIMUM_RUNTIME,
        },
    )

    # Step 2: minimum_runtime
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "minimum_runtime"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_ROLLING_WINDOW: 26.0,
            CONF_MIN_HOURS_ON: 2.0,
        },
    )

    # Step 3: common_options
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "common_options"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SELECTION_MODE: SELECTION_MODE_CHEAPEST,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    opts = config_entry.options
    assert opts[CONF_STRATEGY] == STRATEGY_MINIMUM_RUNTIME
    assert opts[CONF_ROLLING_WINDOW] == 26.0
    assert opts[CONF_MIN_HOURS_ON] == 2.0


async def test_options_flow_change_nordpool_sensor(
    hass: HomeAssistant, setup_two_native_nordpool
):
    """Test changing the Nordpool sensor via the options flow."""
    entity_se4, entity_se3 = setup_two_native_nordpool

    config_entry = _make_config_entry(
        hass, entity_id=entity_se4.entity_id, nordpool_type=NORDPOOL_TYPE_NATIVE
    )

    # Step 1: init — change sensor
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_NORDPOOL_SENSOR: entity_se3.entity_id,
            CONF_STRATEGY: STRATEGY_LOWEST_PRICE,
        },
    )

    # Step 2: lowest_price
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "lowest_price"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_HOURS_PER_PERIOD: 4.0,
            CONF_PERIOD_FROM: DEFAULT_PERIOD_FROM,
            CONF_PERIOD_TO: DEFAULT_PERIOD_TO,
        },
    )

    # Step 3: common_options
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "common_options"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SELECTION_MODE: SELECTION_MODE_CHEAPEST,
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

    config_entry = _make_config_entry(
        hass, entity_id=entity_se4.entity_id, nordpool_type=NORDPOOL_TYPE_NATIVE
    )

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    with patch(
        "custom_components.power_saver.config_flow.detect_nordpool_type",
        return_value="unknown",
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_NORDPOOL_SENSOR: entity_se3.entity_id,
                CONF_STRATEGY: STRATEGY_LOWEST_PRICE,
            },
        )

    # Should re-show the form with an error
    assert result["type"] is FlowResultType.FORM
    assert result["errors"][CONF_NORDPOOL_SENSOR] == "nordpool_not_found"

    # Original data NOT changed
    assert config_entry.data[CONF_NORDPOOL_SENSOR] == entity_se4.entity_id
    assert config_entry.data[CONF_NORDPOOL_TYPE] == NORDPOOL_TYPE_NATIVE


async def test_options_flow_switch_strategy(hass: HomeAssistant, setup_hacs_nordpool):
    """Test switching from Lowest Price to Minimum Runtime strategy."""
    config_entry = _make_config_entry(hass, strategy=STRATEGY_LOWEST_PRICE)

    # Step 1: init — switch to Minimum Runtime
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_NORDPOOL_SENSOR: NORDPOOL_ENTITY,
            CONF_STRATEGY: STRATEGY_MINIMUM_RUNTIME,
        },
    )

    # Should go to minimum_runtime step
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "minimum_runtime"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_ROLLING_WINDOW: 26.0,
            CONF_MIN_HOURS_ON: 2.0,
        },
    )

    # Step 3: common_options
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "common_options"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SELECTION_MODE: SELECTION_MODE_MOST_EXPENSIVE,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[CONF_STRATEGY] == STRATEGY_MINIMUM_RUNTIME
    assert config_entry.options[CONF_ROLLING_WINDOW] == 26.0
    assert config_entry.options[CONF_MIN_HOURS_ON] == 2.0
    assert config_entry.options[CONF_SELECTION_MODE] == SELECTION_MODE_MOST_EXPENSIVE
