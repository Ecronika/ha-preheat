"""Config flow for Preheat integration."""
from __future__ import annotations

from typing import Any
import datetime
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_OCCUPANCY,
    CONF_TEMPERATURE,
    CONF_CLIMATE,
    CONF_SETPOINT,
    CONF_OUTDOOR_TEMP,
    CONF_WEATHER_ENTITY,
    CONF_WORKDAY,
    CONF_LOCK,
    CONF_PRESET_MODE,
    CONF_EXPERT_MODE,
    CONF_VALVE_POSITION,
    PRESET_BALANCED,
    PRESET_AGGRESSIVE,
    PRESET_CONSERVATIVE,
    CONF_EMA_ALPHA,
    CONF_BUFFER_MIN,
    CONF_INITIAL_GAIN,
    CONF_MAX_PREHEAT_HOURS,
    CONF_DONT_START_IF_WARM,
    CONF_ARRIVAL_WINDOW_START,
    CONF_ARRIVAL_WINDOW_END,
    CONF_AIR_TO_OPER_BIAS,
    CONF_EARLIEST_START,
    DEFAULT_EMA_ALPHA,
    DEFAULT_BUFFER_MIN,
    DEFAULT_INITIAL_GAIN,
    DEFAULT_MAX_HOURS,
    DEFAULT_ARRIVAL_WINDOW_START,
    DEFAULT_ARRIVAL_WINDOW_END,
)

class PreheatingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Preheat."""

    VERSION = 3

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
             return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={},
                options={
                    CONF_PRESET_MODE: user_input.get(CONF_PRESET_MODE, PRESET_BALANCED),
                    CONF_EXPERT_MODE: False,
                    **user_input
                }
            )

        data_schema = vol.Schema({
            vol.Required(CONF_NAME, default="Office"): str,
            vol.Required(CONF_OCCUPANCY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
            vol.Required(CONF_TEMPERATURE): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number"])
            ),
            # Optional basics
            vol.Optional(CONF_CLIMATE): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
             vol.Optional(CONF_PRESET_MODE, default=PRESET_BALANCED): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": PRESET_AGGRESSIVE, "label": "Aggressive"},
                        {"value": PRESET_BALANCED, "label": "Balanced"},
                        {"value": PRESET_CONSERVATIVE, "label": "Eco"},
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="preset_mode"
                )
            ),
        })

        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> PreheatingOptionsFlow:
        return PreheatingOptionsFlow()

class PreheatingOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow."""

    def _get_val(self, key, default=None):
        return self.config_entry.options.get(key, self.config_entry.data.get(key, default))

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage options."""
        is_expert = self._get_val(CONF_EXPERT_MODE, False)
        errors = {}
        
        if user_input is not None:
             # Validation
            if user_input.get(CONF_BUFFER_MIN, 0) > 60:
                 errors[CONF_BUFFER_MIN] = "buffer_too_high"
            
            if user_input.get(CONF_MAX_PREHEAT_HOURS, 3.0) > 5.0:
                 errors[CONF_MAX_PREHEAT_HOURS] = "max_duration_too_high"

            # Handle Expert Switch
            if not errors and user_input.get(CONF_EXPERT_MODE, False) != is_expert:
                 # Reload form with new fields
                 return self.async_show_form(
                    step_id="init", 
                    data_schema=self._build_schema(show_expert=user_input.get(CONF_EXPERT_MODE)),
                    errors=errors
                )
            
            # Save
            if not errors:
                return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(step_id="init", data_schema=self._build_schema(show_expert=is_expert), errors=errors)

    def _build_schema(self, show_expert: bool) -> vol.Schema:
        schema = {
            vol.Optional(CONF_OCCUPANCY): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor")),
            vol.Optional(CONF_TEMPERATURE): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor", "input_number"])),
            vol.Optional(CONF_CLIMATE): selector.EntitySelector(selector.EntitySelectorConfig(domain="climate")),
            vol.Optional(CONF_SETPOINT): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor", "input_number"])),
            vol.Optional(CONF_WEATHER_ENTITY): selector.EntitySelector(selector.EntitySelectorConfig(domain="weather")),
            
            vol.Optional(CONF_PRESET_MODE): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": PRESET_AGGRESSIVE, "label": "Aggressive"},
                        {"value": PRESET_BALANCED, "label": "Balanced"},
                        {"value": PRESET_CONSERVATIVE, "label": "Eco"},
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Optional(CONF_EXPERT_MODE): selector.BooleanSelector()
        }

        if show_expert:
            schema.update({
                vol.Optional(CONF_VALVE_POSITION): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "input_number"]) # Valve is usually a sensor?
                ),
                vol.Optional(CONF_LOCK): selector.EntitySelector(selector.EntitySelectorConfig(domain="input_boolean")),
                vol.Optional(CONF_WORKDAY): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor")),
                
                vol.Optional(CONF_INITIAL_GAIN): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1.0, max=60.0, step=0.5, unit_of_measurement="min/K", mode="box")
                ),
                vol.Optional(CONF_EMA_ALPHA): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=1.0, step=0.05, mode="slider")
                ),
                vol.Optional(CONF_BUFFER_MIN): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=120, mode="box")
                ),
                vol.Optional(CONF_MAX_PREHEAT_HOURS): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1.0, max=12.0, step=0.5, unit_of_measurement="h", mode="box")
                ),
                vol.Optional(CONF_DONT_START_IF_WARM): selector.BooleanSelector(),
                
                vol.Optional(CONF_ARRIVAL_WINDOW_START): selector.TimeSelector(),
                vol.Optional(CONF_ARRIVAL_WINDOW_END): selector.TimeSelector(),
                
                vol.Optional(CONF_AIR_TO_OPER_BIAS): selector.NumberSelector(
                     selector.NumberSelectorConfig(min=-5.0, max=5.0, step=0.5, unit_of_measurement="K", mode="box")
                ),
                vol.Optional(CONF_EARLIEST_START): selector.NumberSelector(
                     selector.NumberSelectorConfig(min=60, max=480, step=15, unit_of_measurement="min", mode="box")
                ),
            })

        # Fill defaults
        data = {**self.config_entry.data, **self.config_entry.options}
        if CONF_VALVE_POSITION not in data: data[CONF_VALVE_POSITION] = None
        if CONF_ARRIVAL_WINDOW_START not in data: data[CONF_ARRIVAL_WINDOW_START] = DEFAULT_ARRIVAL_WINDOW_START
        if CONF_ARRIVAL_WINDOW_END not in data: data[CONF_ARRIVAL_WINDOW_END] = DEFAULT_ARRIVAL_WINDOW_END
        
        if CONF_AIR_TO_OPER_BIAS not in data: data[CONF_AIR_TO_OPER_BIAS] = 0.0
        if CONF_EARLIEST_START not in data: data[CONF_EARLIEST_START] = 180 # 3h default

        data[CONF_EXPERT_MODE] = show_expert
        
        return self.add_suggested_values_to_schema(vol.Schema(schema), data)