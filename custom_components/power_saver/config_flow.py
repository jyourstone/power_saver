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
    SELECTION_MODE_CHEAPEST,
    SELECTION_MODE_MOST_EXPENSIVE,
    STRATEGY_LOWEST_PRICE,
    STRATEGY_MINIMUM_RUNTIME,
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


def _strategy_selector() -> SelectSelector:
    """Build strategy dropdown selector."""
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(
                    value=STRATEGY_LOWEST_PRICE,
                    label=STRATEGY_LOWEST_PRICE,
                ),
                SelectOptionDict(
                    value=STRATEGY_MINIMUM_RUNTIME,
                    label=STRATEGY_MINIMUM_RUNTIME,
                ),
            ],
            mode="dropdown",
            translation_key=CONF_STRATEGY,
        )
    )


class PowerSaverConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Power Saver."""

    VERSION = 3

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._user_input: dict[str, Any] = {}

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
        """Step 1: Sensor + Name + Strategy."""
        errors: dict[str, str] = {}

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
                name = user_input[CONF_NAME]
                unique_id = f"{nordpool_entity}_{slugify(name)}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                self._user_input = {
                    CONF_NORDPOOL_SENSOR: nordpool_entity,
                    CONF_NORDPOOL_TYPE: nordpool_type,
                    CONF_NAME: name,
                    CONF_STRATEGY: user_input[CONF_STRATEGY],
                }

                strategy = user_input[CONF_STRATEGY]
                if strategy == STRATEGY_MINIMUM_RUNTIME:
                    return await self.async_step_minimum_runtime()
                return await self.async_step_lowest_price()

        if not all_sensors:
            errors["base"] = "nordpool_not_found"

        sensor_options = [
            SelectOptionDict(value=entity_id, label=label)
            for entity_id, _, label in all_sensors
        ]

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
                vol.Required(
                    CONF_STRATEGY, default=DEFAULT_STRATEGY
                ): _strategy_selector(),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_lowest_price(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2a: Lowest Price settings."""
        if user_input is not None:
            self._user_input.update(user_input)
            return await self.async_step_common_options()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOURS_PER_PERIOD, default=DEFAULT_HOURS_PER_PERIOD
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=24, step=0.25, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_PERIOD_FROM, default=DEFAULT_PERIOD_FROM
                ): TimeSelector(),
                vol.Required(
                    CONF_PERIOD_TO, default=DEFAULT_PERIOD_TO
                ): TimeSelector(),
                vol.Optional(CONF_MIN_CONSECUTIVE_HOURS): NumberSelector(
                    NumberSelectorConfig(
                        min=0.25, max=24, step=0.25, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="hours",
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="lowest_price",
            data_schema=schema,
        )

    async def async_step_minimum_runtime(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2b: Minimum Runtime settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input[CONF_ROLLING_WINDOW] < user_input[CONF_MIN_HOURS_ON]:
                errors["base"] = "rolling_window_too_small"
            else:
                self._user_input.update(user_input)
                return await self.async_step_common_options()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MIN_HOURS_ON, default=DEFAULT_MIN_HOURS_ON
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.25, max=24, step=0.25, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="hours",
                    )
                ),
                vol.Required(
                    CONF_ROLLING_WINDOW, default=DEFAULT_ROLLING_WINDOW
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=2, max=72, step=0.5, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="hours",
                    )
                ),
                vol.Optional(CONF_MIN_CONSECUTIVE_HOURS): NumberSelector(
                    NumberSelectorConfig(
                        min=0.25, max=24, step=0.25, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="hours",
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="minimum_runtime",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_common_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: Common options (mode, thresholds, exclusion, entities)."""
        if user_input is not None:
            data = {
                CONF_NORDPOOL_SENSOR: self._user_input[CONF_NORDPOOL_SENSOR],
                CONF_NORDPOOL_TYPE: self._user_input[CONF_NORDPOOL_TYPE],
                CONF_NAME: self._user_input[CONF_NAME],
            }
            strategy = self._user_input[CONF_STRATEGY]
            options: dict[str, Any] = {
                CONF_STRATEGY: strategy,
                CONF_SELECTION_MODE: user_input.get(
                    CONF_SELECTION_MODE, DEFAULT_SELECTION_MODE
                ),
            }
            # Add strategy-specific keys
            if strategy == STRATEGY_LOWEST_PRICE:
                options[CONF_HOURS_PER_PERIOD] = self._user_input[CONF_HOURS_PER_PERIOD]
                options[CONF_PERIOD_FROM] = self._user_input[CONF_PERIOD_FROM]
                options[CONF_PERIOD_TO] = self._user_input[CONF_PERIOD_TO]
                if self._user_input.get(CONF_MIN_CONSECUTIVE_HOURS) is not None:
                    options[CONF_MIN_CONSECUTIVE_HOURS] = self._user_input[
                        CONF_MIN_CONSECUTIVE_HOURS
                    ]
            else:
                options[CONF_ROLLING_WINDOW] = self._user_input[CONF_ROLLING_WINDOW]
                options[CONF_MIN_HOURS_ON] = self._user_input[CONF_MIN_HOURS_ON]
                if self._user_input.get(CONF_MIN_CONSECUTIVE_HOURS) is not None:
                    options[CONF_MIN_CONSECUTIVE_HOURS] = self._user_input[
                        CONF_MIN_CONSECUTIVE_HOURS
                    ]

            # Add common optional keys
            for key in (
                CONF_ALWAYS_CHEAP,
                CONF_ALWAYS_EXPENSIVE,
                CONF_PRICE_SIMILARITY_PCT,
                CONF_EXCLUDE_FROM,
                CONF_EXCLUDE_UNTIL,
            ):
                if user_input.get(key) is not None:
                    options[key] = user_input[key]
            if user_input.get(CONF_CONTROLLED_ENTITIES):
                options[CONF_CONTROLLED_ENTITIES] = user_input[
                    CONF_CONTROLLED_ENTITIES
                ]

            return self.async_create_entry(
                title=self._user_input[CONF_NAME],
                data=data,
                options=options,
            )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SELECTION_MODE, default=DEFAULT_SELECTION_MODE
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
                vol.Optional(CONF_ALWAYS_CHEAP): NumberSelector(
                    NumberSelectorConfig(
                        min=-10, max=100, step=0.01, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="SEK/kWh",
                    )
                ),
                vol.Optional(CONF_ALWAYS_EXPENSIVE): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=100, step=0.01, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="SEK/kWh",
                    )
                ),
                vol.Optional(CONF_PRICE_SIMILARITY_PCT): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=100, step=1, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="%",
                    )
                ),
                vol.Optional(CONF_EXCLUDE_FROM): TimeSelector(),
                vol.Optional(CONF_EXCLUDE_UNTIL): TimeSelector(),
                vol.Optional(
                    CONF_CONTROLLED_ENTITIES, default=[]
                ): EntitySelector(
                    EntitySelectorConfig(
                        domain=["switch", "input_boolean", "light"],
                        multiple=True,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="common_options",
            data_schema=schema,
        )


class PowerSaverOptionsFlow(OptionsFlowWithReload):
    """Handle options flow for Power Saver."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the options flow."""
        super().__init__(*args, **kwargs)
        self._options: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: Strategy + Nord Pool sensor."""
        errors: dict[str, str] = {}
        defaults = dict(self.config_entry.options)

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
                self._options = dict(user_input)
                strategy = user_input.get(CONF_STRATEGY, DEFAULT_STRATEGY)
                if strategy == STRATEGY_MINIMUM_RUNTIME:
                    return await self.async_step_minimum_runtime()
                return await self.async_step_lowest_price()

        # Build sensor selector
        all_sensors = find_all_nordpool_sensors(self.hass)
        current_sensor = self.config_entry.data.get(CONF_NORDPOOL_SENSOR, "")

        sensor_options = [
            SelectOptionDict(value=entity_id, label=label)
            for entity_id, _, label in all_sensors
        ]

        current_in_list = any(s[0] == current_sensor for s in all_sensors)
        if not current_in_list and current_sensor:
            sensor_options.append(
                SelectOptionDict(value=current_sensor, label=current_sensor)
            )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_NORDPOOL_SENSOR, default=current_sensor
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=sensor_options,
                        mode="dropdown",
                    )
                ),
                vol.Required(
                    CONF_STRATEGY,
                    default=defaults.get(CONF_STRATEGY, DEFAULT_STRATEGY),
                ): _strategy_selector(),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_lowest_price(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2a: Lowest Price strategy options."""
        defaults = dict(self.config_entry.options)

        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_common_options()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOURS_PER_PERIOD,
                    default=defaults.get(CONF_HOURS_PER_PERIOD, DEFAULT_HOURS_PER_PERIOD),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=24, step=0.25, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_PERIOD_FROM,
                    default=defaults.get(CONF_PERIOD_FROM, DEFAULT_PERIOD_FROM),
                ): TimeSelector(),
                vol.Required(
                    CONF_PERIOD_TO,
                    default=defaults.get(CONF_PERIOD_TO, DEFAULT_PERIOD_TO),
                ): TimeSelector(),
                _optional_number(CONF_MIN_CONSECUTIVE_HOURS, defaults): NumberSelector(
                    NumberSelectorConfig(
                        min=0.25, max=24, step=0.25, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="hours",
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="lowest_price",
            data_schema=schema,
        )

    async def async_step_minimum_runtime(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2b: Minimum Runtime strategy options."""
        defaults = dict(self.config_entry.options)
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input[CONF_ROLLING_WINDOW] < user_input[CONF_MIN_HOURS_ON]:
                errors["base"] = "rolling_window_too_small"
            else:
                self._options.update(user_input)
                return await self.async_step_common_options()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MIN_HOURS_ON,
                    default=defaults.get(CONF_MIN_HOURS_ON, DEFAULT_MIN_HOURS_ON),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.25, max=24, step=0.25, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="hours",
                    )
                ),
                vol.Required(
                    CONF_ROLLING_WINDOW,
                    default=defaults.get(CONF_ROLLING_WINDOW, DEFAULT_ROLLING_WINDOW),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=2, max=72, step=0.5, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="hours",
                    )
                ),
                _optional_number(CONF_MIN_CONSECUTIVE_HOURS, defaults): NumberSelector(
                    NumberSelectorConfig(
                        min=0.25, max=24, step=0.25, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="hours",
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="minimum_runtime",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_common_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: Common options (mode, thresholds, exclusion, entities)."""
        defaults = dict(self.config_entry.options)

        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(data=self._options)

        schema = vol.Schema(
            {
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
                _optional_time(CONF_EXCLUDE_FROM, defaults): TimeSelector(),
                _optional_time(CONF_EXCLUDE_UNTIL, defaults): TimeSelector(),
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

        return self.async_show_form(
            step_id="common_options",
            data_schema=schema,
        )
