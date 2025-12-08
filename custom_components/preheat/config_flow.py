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
    CONF_HEATING_PROFILE,
    HEATING_PROFILES,
    PROFILE_RADIATOR_NEW,
    # Presets
    PRESET_BALANCED,
    PRESET_AGGRESSIVE,
    PRESET_CONSERVATIVE,
    # Keys
    CONF_EMA_ALPHA,
    CONF_BUFFER_MIN,
    CONF_INITIAL_GAIN,
    CONF_MAX_PREHEAT_HOURS,
    CONF_DONT_START_IF_WARM,
    CONF_ARRIVAL_WINDOW_START,
    CONF_ARRIVAL_WINDOW_END,
    CONF_AIR_TO_OPER_BIAS,
    CONF_EARLIEST_START,
    # Defaults
    DEFAULT_EMA_ALPHA,
    DEFAULT_BUFFER_MIN,
    DEFAULT_INITIAL_GAIN,
    DEFAULT_MAX_HOURS,
    DEFAULT_ARRIVAL_WINDOW_START,
    DEFAULT_ARRIVAL_WINDOW_END,
    CONF_COMFORT_MIN,
    CONF_COMFORT_MAX,
    CONF_COMFORT_FALLBACK,
    DEFAULT_COMFORT_MIN,
    DEFAULT_COMFORT_MAX,
    DEFAULT_COMFORT_FALLBACK,
)

class PreheatingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Preheat."""

    VERSION = 3

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
             # V3: Profile defines defaults. We just save the selection.
             return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={},
                options={
                    CONF_PRESET_MODE: user_input.get(CONF_PRESET_MODE, PRESET_BALANCED),
                    CONF_EXPERT_MODE: False,
                    **user_input
                }
            )

        # Build Profile Options
        profile_options = [
            {"value": k, "label": v["name"]} 
            for k,v in HEATING_PROFILES.items()
        ]

        data_schema = vol.Schema({
            vol.Required(CONF_NAME, default="Office"): str,
            vol.Required(CONF_OCCUPANCY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
            vol.Required(CONF_TEMPERATURE): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number"])
            ),
            # Climate is now strongly encouraged as it replaces Setpoint Sensor
            vol.Optional(CONF_CLIMATE): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            # Weather & Outdoor (Non-Expert)
            vol.Optional(CONF_WEATHER_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            vol.Optional(CONF_OUTDOOR_TEMP): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number"], device_class="temperature")
            ),
            vol.Required(CONF_HEATING_PROFILE, default=PROFILE_RADIATOR_NEW): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=profile_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="heating_profile" # Ensure we add this to strings.json
                )
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
        # Build Profile Options
        profile_options = [
            {"value": k, "label": v["name"]} 
            for k,v in HEATING_PROFILES.items()
        ]

        schema = {
            vol.Optional(CONF_OCCUPANCY): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor")),
            vol.Optional(CONF_TEMPERATURE): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor", "input_number"])),
            vol.Optional(CONF_CLIMATE): selector.EntitySelector(selector.EntitySelectorConfig(domain="climate")),
            # Removed: Setpoint Sensor
            vol.Optional(CONF_WEATHER_ENTITY): selector.EntitySelector(selector.EntitySelectorConfig(domain="weather")),
            
            vol.Required(CONF_HEATING_PROFILE, default=PROFILE_RADIATOR_NEW): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=profile_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="heating_profile"
                )
            ),

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
                    selector.EntitySelectorConfig(domain=["sensor", "input_number"]) 
                ),
                vol.Optional(CONF_LOCK): selector.EntitySelector(selector.EntitySelectorConfig(domain="input_boolean")),
                vol.Optional(CONF_WORKDAY): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor")),
                
                # Removed: Initial Gain
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
                # Removed: Earliest Start (Redundant with Max Duration)
                vol.Optional(CONF_COMFORT_MIN): selector.NumberSelector(
                     selector.NumberSelectorConfig(min=15.0, max=25.0, step=0.5, unit_of_measurement="°C", mode="box")
                ),
                vol.Optional(CONF_COMFORT_MAX): selector.NumberSelector(
                     selector.NumberSelectorConfig(min=18.0, max=30.0, step=0.5, unit_of_measurement="°C", mode="box")
                ),
                vol.Optional(CONF_COMFORT_FALLBACK): selector.NumberSelector(
                     selector.NumberSelectorConfig(min=15.0, max=25.0, step=0.5, unit_of_measurement="°C", mode="box")
                ),
            })

        # Fill defaults
        data = {**self.config_entry.data, **self.config_entry.options}
        
        # Resolve Profile Defaults
        profile_key = data.get(CONF_HEATING_PROFILE, PROFILE_RADIATOR_NEW)
        profile_data = HEATING_PROFILES.get(profile_key, HEATING_PROFILES[PROFILE_RADIATOR_NEW])
        
        if CONF_BUFFER_MIN not in data:
             data[CONF_BUFFER_MIN] = profile_data.get("buffer", DEFAULT_BUFFER_MIN)
        if CONF_MAX_PREHEAT_HOURS not in data:
             data[CONF_MAX_PREHEAT_HOURS] = profile_data.get("max_duration", DEFAULT_MAX_HOURS)
        if CONF_EMA_ALPHA not in data:
             data[CONF_EMA_ALPHA] = DEFAULT_EMA_ALPHA
        if CONF_DONT_START_IF_WARM not in data:
             data[CONF_DONT_START_IF_WARM] = True

        if CONF_VALVE_POSITION not in data: data[CONF_VALVE_POSITION] = None
        if CONF_LOCK not in data: data[CONF_LOCK] = None
        if CONF_WORKDAY not in data: data[CONF_WORKDAY] = None
        
        if CONF_ARRIVAL_WINDOW_START not in data: data[CONF_ARRIVAL_WINDOW_START] = DEFAULT_ARRIVAL_WINDOW_START
        if CONF_ARRIVAL_WINDOW_END not in data: data[CONF_ARRIVAL_WINDOW_END] = DEFAULT_ARRIVAL_WINDOW_END
        
        if CONF_AIR_TO_OPER_BIAS not in data: data[CONF_AIR_TO_OPER_BIAS] = 0.0
        if CONF_EARLIEST_START not in data: data[CONF_EARLIEST_START] = 180 # 3h default
        
        if CONF_COMFORT_MIN not in data: data[CONF_COMFORT_MIN] = DEFAULT_COMFORT_MIN
        if CONF_COMFORT_MAX not in data: data[CONF_COMFORT_MAX] = DEFAULT_COMFORT_MAX
        if CONF_COMFORT_FALLBACK not in data: data[CONF_COMFORT_FALLBACK] = DEFAULT_COMFORT_FALLBACK

        data[CONF_EXPERT_MODE] = show_expert
        
        return self.add_suggested_values_to_schema(vol.Schema(schema), data)