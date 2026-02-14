"""Config flow for the Power Saver integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
)

try:
    from homeassistant.config_entries import OptionsFlowWithReload
    _LEGACY_OPTIONS_FLOW = False
except ImportError:
    from homeassistant.config_entries import OptionsFlowWithConfigEntry as OptionsFlowWithReload
    _LEGACY_OPTIONS_FLOW = True
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TimeSelector,
)
from homeassistant.util import slugify

from .const import (
    CONF_ALWAYS_CHEAP,
    CONF_ALWAYS_EXPENSIVE,
    CONF_CONTROLLED_ENTITIES,
    CONF_EXCLUDE_FROM,
    CONF_EXCLUDE_UNTIL,
    CONF_MIN_CONSECUTIVE_HOURS,
    CONF_MIN_HOURS,
    CONF_NAME,
    CONF_NORDPOOL_SENSOR,
    CONF_NORDPOOL_TYPE,
    CONF_PRICE_SIMILARITY_PCT,
    CONF_ROLLING_WINDOW_HOURS,
    CONF_SELECTION_MODE,
    DEFAULT_MIN_HOURS,
    DEFAULT_ROLLING_WINDOW_HOURS,
    DEFAULT_SELECTION_MODE,
    DOMAIN,
    SELECTION_MODE_CHEAPEST,
    SELECTION_MODE_MOST_EXPENSIVE,
)
from .nordpool_adapter import detect_nordpool_type, find_all_nordpool_sensors

_LOGGER = logging.getLogger(__name__)


def _optional_number(key: str, defaults: dict[str, Any]) -> vol.Optional:
    """Create vol.Optional with suggested value pre-fill (allows clearing)."""
    val = defaults.get(key)
    if val is not None:
        return vol.Optional(key, description={"suggested_value": val})
    return vol.Optional(key)


def _optional_time(key: str, defaults: dict[str, Any]) -> vol.Optional:
    """Create vol.Optional for time fields with suggested value pre-fill (allows clearing)."""
    val = defaults.get(key)
    if val is not None:
        return vol.Optional(key, description={"suggested_value": val})
    return vol.Optional(key)


def _options_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build the schema for tunable options."""
    if defaults is None:
        defaults = {}
    return vol.Schema(
        {
            # Selection mode
            vol.Required(
                CONF_SELECTION_MODE,
                default=defaults.get(CONF_SELECTION_MODE, DEFAULT_SELECTION_MODE),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(
                            value=SELECTION_MODE_CHEAPEST,
                            label=SELECTION_MODE_CHEAPEST,
                        ),
                        SelectOptionDict(
                            value=SELECTION_MODE_MOST_EXPENSIVE,
                            label=SELECTION_MODE_MOST_EXPENSIVE,
                        ),
                    ],
                    mode="dropdown",
                    translation_key=CONF_SELECTION_MODE,
                )
            ),
            # Required scheduling parameters
            vol.Required(
                CONF_MIN_HOURS,
                default=defaults.get(CONF_MIN_HOURS, DEFAULT_MIN_HOURS),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=24, step=0.25, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_ROLLING_WINDOW_HOURS,
                default=defaults.get(CONF_ROLLING_WINDOW_HOURS, DEFAULT_ROLLING_WINDOW_HOURS),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1, max=48, step=0.5, mode=NumberSelectorMode.BOX
                )
            ),
            # Optional price thresholds (empty = disabled)
            _optional_number(CONF_ALWAYS_CHEAP, defaults): NumberSelector(
                NumberSelectorConfig(
                    min=-10, max=100, step=0.01, mode=NumberSelectorMode.BOX,
                    unit_of_measurement="SEK/kWh",
                )
            ),
            _optional_number(CONF_ALWAYS_EXPENSIVE, defaults): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=100, step=0.01, mode=NumberSelectorMode.BOX,
                    unit_of_measurement="SEK/kWh",
                )
            ),
            _optional_number(CONF_PRICE_SIMILARITY_PCT, defaults): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=100, step=1, mode=NumberSelectorMode.BOX,
                    unit_of_measurement="%",
                )
            ),
            _optional_number(CONF_MIN_CONSECUTIVE_HOURS, defaults): NumberSelector(
                NumberSelectorConfig(
                    min=0.25, max=24, step=0.25, mode=NumberSelectorMode.BOX,
                    unit_of_measurement="hours",
                )
            ),
            # Optional excluded time range
            _optional_time(CONF_EXCLUDE_FROM, defaults): TimeSelector(),
            _optional_time(CONF_EXCLUDE_UNTIL, defaults): TimeSelector(),
            # Optional entity control
            vol.Optional(
                CONF_CONTROLLED_ENTITIES,
                default=defaults.get(CONF_CONTROLLED_ENTITIES, []),
            ): EntitySelector(
                EntitySelectorConfig(
                    domain=["switch", "input_boolean", "light"],
                    multiple=True,
                )
            ),
        }
    )


class PowerSaverConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Power Saver."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PowerSaverOptionsFlow:
        """Get the options flow for this handler."""
        if _LEGACY_OPTIONS_FLOW:
            return PowerSaverOptionsFlow(config_entry)
        return PowerSaverOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        # Detect all available Nord Pool sensors
        all_sensors = find_all_nordpool_sensors(self.hass)

        if user_input is not None:
            nordpool_entity = user_input.get(CONF_NORDPOOL_SENSOR)
            if not nordpool_entity:
                errors["base"] = "nordpool_not_found"
            else:
                nordpool_type = detect_nordpool_type(self.hass, nordpool_entity)
                if nordpool_type == "unknown":
                    errors["base"] = "nordpool_not_found"

            if not errors:
                # Set unique ID to prevent duplicates
                name = user_input[CONF_NAME]
                unique_id = f"{nordpool_entity}_{slugify(name)}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                # Split data (immutable) and options (mutable)
                data = {
                    CONF_NORDPOOL_SENSOR: nordpool_entity,
                    CONF_NORDPOOL_TYPE: nordpool_type,
                    CONF_NAME: name,
                }
                options = {
                    CONF_SELECTION_MODE: user_input.get(CONF_SELECTION_MODE, DEFAULT_SELECTION_MODE),
                    CONF_MIN_HOURS: user_input[CONF_MIN_HOURS],
                    CONF_ROLLING_WINDOW_HOURS: user_input[CONF_ROLLING_WINDOW_HOURS],
                    CONF_ALWAYS_CHEAP: user_input.get(CONF_ALWAYS_CHEAP),
                    CONF_ALWAYS_EXPENSIVE: user_input.get(CONF_ALWAYS_EXPENSIVE),
                    CONF_PRICE_SIMILARITY_PCT: user_input.get(CONF_PRICE_SIMILARITY_PCT),
                    CONF_MIN_CONSECUTIVE_HOURS: user_input.get(CONF_MIN_CONSECUTIVE_HOURS),
                    CONF_EXCLUDE_FROM: user_input.get(CONF_EXCLUDE_FROM),
                    CONF_EXCLUDE_UNTIL: user_input.get(CONF_EXCLUDE_UNTIL),
                    CONF_CONTROLLED_ENTITIES: user_input.get(CONF_CONTROLLED_ENTITIES, []),
                }

                return self.async_create_entry(
                    title=name,
                    data=data,
                    options=options,
                )

        if not all_sensors:
            errors["base"] = "nordpool_not_found"

        # Build sensor selector options with friendly labels
        sensor_options = [
            SelectOptionDict(value=entity_id, label=label)
            for entity_id, _, label in all_sensors
        ]

        # Pre-select if only one sensor exists
        sensor_default: str | vol.Undefined = vol.UNDEFINED
        if len(all_sensors) == 1:
            sensor_default = all_sensors[0][0]

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_NORDPOOL_SENSOR, default=sensor_default
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=sensor_options,
                        mode="dropdown",
                    )
                ),
                vol.Required(CONF_NAME): TextSelector(),
            }
        ).extend(_options_schema().schema)

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )


class PowerSaverOptionsFlow(OptionsFlowWithReload):
    """Handle options flow for Power Saver."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Handle Nord Pool sensor change (stored in data, not options)
            new_sensor = user_input.pop(CONF_NORDPOOL_SENSOR, None)
            current_sensor = self.config_entry.data.get(CONF_NORDPOOL_SENSOR)

            if new_sensor and new_sensor != current_sensor:
                new_type = detect_nordpool_type(self.hass, new_sensor)
                if new_type == "unknown":
                    _LOGGER.warning(
                        "Selected Nord Pool sensor %s could not be validated",
                        new_sensor,
                    )
                    errors[CONF_NORDPOOL_SENSOR] = "nordpool_not_found"
                else:
                    new_data = dict(self.config_entry.data)
                    new_data[CONF_NORDPOOL_SENSOR] = new_sensor
                    new_data[CONF_NORDPOOL_TYPE] = new_type
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, data=new_data
                    )

            if not errors:
                return self.async_create_entry(data=user_input)

        # Build sensor selector for the options form
        all_sensors = find_all_nordpool_sensors(self.hass)
        current_sensor = self.config_entry.data.get(CONF_NORDPOOL_SENSOR, "")

        sensor_options = [
            SelectOptionDict(value=entity_id, label=label)
            for entity_id, _, label in all_sensors
        ]

        # Ensure the current sensor is in the list (even if no longer detected)
        current_in_list = any(s[0] == current_sensor for s in all_sensors)
        if not current_in_list and current_sensor:
            sensor_options.append(
                SelectOptionDict(value=current_sensor, label=current_sensor)
            )

        sensor_schema = vol.Schema(
            {
                vol.Required(
                    CONF_NORDPOOL_SENSOR, default=current_sensor
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=sensor_options,
                        mode="dropdown",
                    )
                ),
            }
        )

        schema = sensor_schema.extend(
            _options_schema(self.config_entry.options).schema
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
