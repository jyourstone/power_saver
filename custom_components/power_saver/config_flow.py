"""Config flow for the Power Saver integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithConfigEntry,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)
from homeassistant.util import slugify

from .const import (
    CONF_ALWAYS_CHEAP,
    CONF_ALWAYS_EXPENSIVE,
    CONF_MIN_HOURS,
    CONF_NAME,
    CONF_NORDPOOL_SENSOR,
    CONF_ROLLING_WINDOW_HOURS,
    DEFAULT_ALWAYS_CHEAP,
    DEFAULT_ALWAYS_EXPENSIVE,
    DEFAULT_MIN_HOURS,
    DEFAULT_ROLLING_WINDOW_HOURS,
    DOMAIN,
)


def _options_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build the schema for tunable options."""
    if defaults is None:
        defaults = {}
    return vol.Schema(
        {
            vol.Required(
                CONF_MIN_HOURS,
                default=defaults.get(CONF_MIN_HOURS, DEFAULT_MIN_HOURS),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=24, step=0.25, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_ALWAYS_CHEAP,
                default=defaults.get(CONF_ALWAYS_CHEAP, DEFAULT_ALWAYS_CHEAP),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=-10, max=100, step=0.01, mode=NumberSelectorMode.BOX,
                    unit_of_measurement="SEK/kWh",
                )
            ),
            vol.Required(
                CONF_ALWAYS_EXPENSIVE,
                default=defaults.get(CONF_ALWAYS_EXPENSIVE, DEFAULT_ALWAYS_EXPENSIVE),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=100, step=0.01, mode=NumberSelectorMode.BOX,
                    unit_of_measurement="SEK/kWh",
                )
            ),
            vol.Required(
                CONF_ROLLING_WINDOW_HOURS,
                default=defaults.get(CONF_ROLLING_WINDOW_HOURS, DEFAULT_ROLLING_WINDOW_HOURS),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=48, step=0.5, mode=NumberSelectorMode.BOX
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
        return PowerSaverOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate Nordpool sensor
            nordpool_entity = user_input[CONF_NORDPOOL_SENSOR]
            state = self.hass.states.get(nordpool_entity)
            if state is None or state.attributes.get("raw_today") is None:
                errors["nordpool_sensor"] = "invalid_nordpool_sensor"

            # Validate rolling window config
            rolling_window = user_input.get(CONF_ROLLING_WINDOW_HOURS, 0)
            min_hours = user_input.get(CONF_MIN_HOURS, 0)
            if rolling_window > 0 and min_hours <= 0:
                errors["rolling_window_hours"] = "invalid_rolling_window"

            if not errors:
                # Set unique ID to prevent duplicates
                name = user_input[CONF_NAME]
                unique_id = f"{nordpool_entity}_{slugify(name)}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                # Split data (immutable) and options (mutable)
                data = {
                    CONF_NORDPOOL_SENSOR: nordpool_entity,
                    CONF_NAME: name,
                }
                options = {
                    CONF_MIN_HOURS: user_input[CONF_MIN_HOURS],
                    CONF_ALWAYS_CHEAP: user_input[CONF_ALWAYS_CHEAP],
                    CONF_ALWAYS_EXPENSIVE: user_input[CONF_ALWAYS_EXPENSIVE],
                    CONF_ROLLING_WINDOW_HOURS: user_input[CONF_ROLLING_WINDOW_HOURS],
                }

                return self.async_create_entry(
                    title=name,
                    data=data,
                    options=options,
                )

        # Build the full schema (data + options fields)
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): TextSelector(),
                vol.Required(CONF_NORDPOOL_SENSOR): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
            }
        ).extend(_options_schema().schema)

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )


class PowerSaverOptionsFlow(OptionsFlowWithConfigEntry):
    """Handle options flow for Power Saver."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            # Validate rolling window config
            errors: dict[str, str] = {}
            rolling_window = user_input.get(CONF_ROLLING_WINDOW_HOURS, 0)
            min_hours = user_input.get(CONF_MIN_HOURS, 0)
            if rolling_window > 0 and min_hours <= 0:
                errors["rolling_window_hours"] = "invalid_rolling_window"

            if not errors:
                return self.async_create_entry(data=user_input)

            return self.async_show_form(
                step_id="init",
                data_schema=_options_schema(user_input),
                errors=errors,
            )

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(self.options),
        )
