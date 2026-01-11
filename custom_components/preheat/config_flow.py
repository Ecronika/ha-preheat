"""Config flow for Preheat integration."""
from __future__ import annotations

from typing import Any
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
    CONF_WEATHER_ENTITY,
    CONF_WORKDAY,
    CONF_CALENDAR_ENTITY,
    CONF_ONLY_ON_WORKDAYS,
    CONF_LOCK,
    CONF_PRESET_MODE,
    CONF_EXPERT_MODE,
    CONF_VALVE_POSITION,
    CONF_HEATING_PROFILE,
    CONF_DEBOUNCE_MIN,      # Fixed Import
    HEATING_PROFILES,
    PROFILE_RADIATOR_NEW,
    # Presets
    PRESET_BALANCED,
    PRESET_AGGRESSIVE,
    PRESET_CONSERVATIVE,
    # Keys
    CONF_EMA_ALPHA,
    CONF_BUFFER_MIN,
    CONF_MAX_PREHEAT_HOURS,
    CONF_DONT_START_IF_WARM,
    CONF_ARRIVAL_WINDOW_START,
    CONF_ARRIVAL_WINDOW_END,
    CONF_AIR_TO_OPER_BIAS,
    CONF_INITIAL_GAIN,      # Re-added
    CONF_EARLIEST_START,    # Re-added
    # Defaults
    DEFAULT_EMA_ALPHA,
    DEFAULT_BUFFER_MIN,
    DEFAULT_MAX_HOURS,
    DEFAULT_DEBOUNCE_MIN,   # Fixed Import
    DEFAULT_ARRIVAL_WINDOW_START,
    DEFAULT_ARRIVAL_WINDOW_END,
    CONF_COMFORT_MIN,
    CONF_COMFORT_MAX,
    CONF_COMFORT_FALLBACK,
    DEFAULT_COMFORT_MIN,
    DEFAULT_COMFORT_MAX,
    DEFAULT_COMFORT_FALLBACK,
    # Forecast
    CONF_USE_FORECAST,
    CONF_RISK_MODE,
    RISK_BALANCED,
    RISK_PESSIMISTIC,
    RISK_OPTIMISTIC,
    DEFAULT_USE_FORECAST,
    DEFAULT_RISK_MODE,
    # Optimal Stop
    CONF_ENABLE_OPTIMAL_STOP,
    CONF_STOP_TOLERANCE,
    CONF_MAX_COAST_HOURS,
    CONF_SCHEDULE_ENTITY,
    DEFAULT_STOP_TOLERANCE,
    DEFAULT_MAX_COAST_HOURS,
    CONF_PHYSICS_MODE,
    PHYSICS_STANDARD,
    PHYSICS_ADVANCED,
)

class PreheatingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Preheat."""

    VERSION = 3

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
             # 1. Validate Entities
             if not self.hass.states.get(user_input[CONF_OCCUPANCY]):
                 errors[CONF_OCCUPANCY] = "entity_not_found"
             if not self.hass.states.get(user_input[CONF_CLIMATE]):
                 errors[CONF_CLIMATE] = "entity_not_found"
                 
             # Validate Optional Entities
             if user_input.get(CONF_TEMPERATURE):
                  if not self.hass.states.get(user_input[CONF_TEMPERATURE]):
                       errors[CONF_TEMPERATURE] = "entity_not_found"
                       
             if user_input.get(CONF_WEATHER_ENTITY):
                  if not self.hass.states.get(user_input[CONF_WEATHER_ENTITY]):
                       errors[CONF_WEATHER_ENTITY] = "entity_not_found"
             
             if not errors:
                 # 2. Set Unique ID (Best Practice) - ONLY if validation passed
                 await self.async_set_unique_id(user_input[CONF_CLIMATE])
                 self._abort_if_unique_id_configured()

                 # V3: Split Core (Data) vs Behavior (Options)
                 return self.async_create_entry(
                    title=user_input.get(CONF_NAME, user_input[CONF_CLIMATE]),
                    data={
                        CONF_OCCUPANCY: user_input[CONF_OCCUPANCY],
                        CONF_CLIMATE: user_input[CONF_CLIMATE],
                        CONF_TEMPERATURE: user_input.get(CONF_TEMPERATURE),
                        CONF_WEATHER_ENTITY: user_input.get(CONF_WEATHER_ENTITY),
                        # Valve Position removed (Behavior Option)
                    },
                    options={
                        CONF_HEATING_PROFILE: user_input.get(CONF_HEATING_PROFILE, PROFILE_RADIATOR_NEW),
                        # Apply Defaults Explicitly
                        CONF_BUFFER_MIN: DEFAULT_BUFFER_MIN, 
                        CONF_ARRIVAL_WINDOW_START: DEFAULT_ARRIVAL_WINDOW_START,
                        CONF_ARRIVAL_WINDOW_END: DEFAULT_ARRIVAL_WINDOW_END,
                    }
                )

        # Build Schema (User)
        # We use explicit defaults or empty for new setup
        defaults = user_input or {}
        
        schema = vol.Schema({
             vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "Intelligent Preheat")): str,
             vol.Required(CONF_OCCUPANCY, default=defaults.get(CONF_OCCUPANCY)): selector.EntitySelector(
                 selector.EntitySelectorConfig(domain="binary_sensor")
             ),
             vol.Required(CONF_CLIMATE, default=defaults.get(CONF_CLIMATE)): selector.EntitySelector(
                 selector.EntitySelectorConfig(domain="climate")
             ),
             vol.Optional(CONF_TEMPERATURE, default=defaults.get(CONF_TEMPERATURE, vol.UNDEFINED)): selector.EntitySelector(
                 selector.EntitySelectorConfig(domain=["sensor", "input_number"])
             ),
             # Valve Position Removed (Strictly Option)
             vol.Optional(CONF_WEATHER_ENTITY, default=defaults.get(CONF_WEATHER_ENTITY, vol.UNDEFINED)): selector.EntitySelector(
                 selector.EntitySelectorConfig(domain="weather")
             ),
             vol.Required(CONF_HEATING_PROFILE, default=defaults.get(CONF_HEATING_PROFILE, PROFILE_RADIATOR_NEW)): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(HEATING_PROFILES.keys()),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="heating_profile"
                )
             ),
        })

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle re-configuration."""
        errors = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            # Update Entry
            return self.async_update_reload_and_abort(
                entry,
                data={
                    CONF_OCCUPANCY: user_input[CONF_OCCUPANCY],
                    CONF_CLIMATE: user_input[CONF_CLIMATE],
                    CONF_TEMPERATURE: user_input.get(CONF_TEMPERATURE),
                    CONF_WEATHER_ENTITY: user_input.get(CONF_WEATHER_ENTITY),
                },
                # We do NOT touch options here, preserving them.
            )

        # Pre-fill
        data = {**entry.data, **entry.options}
        
        data_schema = vol.Schema({
            vol.Required(CONF_OCCUPANCY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
            vol.Required(CONF_CLIMATE): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Optional(CONF_TEMPERATURE): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number"])
            ),
            vol.Optional(CONF_WEATHER_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            # No Valve Here - Accessed via Options
        })

        return self.async_show_form(
            step_id="reconfigure", 
            data_schema=self.add_suggested_values_to_schema(data_schema, data), 
            errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> PreheatingOptionsFlow:
        return PreheatingOptionsFlow(config_entry)


class PreheatingOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    def _get_val(self, key, default=None):
        return self._config_entry.options.get(key, self._config_entry.data.get(key, default))

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage options (Explicit Construction + Suggested Values)."""
        errors = {}
        
        if user_input is not None:
            # Validation
            if user_input.get(CONF_BUFFER_MIN, 0) > 120:
                 errors[CONF_BUFFER_MIN] = "buffer_too_high"
            
            if not errors:
                # EXPLICIT CONSTRUCTION (Fixes Persistence Bug)
                # Instead of merging {**options, **user_input}, we define exactly what goes in.
                # If a key is missing in user_input, we assume it was CLEARED by user (thanks to suggested_values).
                # We explicitly store None to mask any legacy data values.
                
                update_data = {}
                
                # 1. Required/Preserved Fields
                update_data[CONF_HEATING_PROFILE] = user_input.get(CONF_HEATING_PROFILE, PROFILE_RADIATOR_NEW)
                
                # 2. Optional Fields logic
                optional_keys = [
                    CONF_BUFFER_MIN, 
                    CONF_EARLIEST_START,
                    CONF_ARRIVAL_WINDOW_START, 
                    CONF_ARRIVAL_WINDOW_END,
                    CONF_COMFORT_FALLBACK, 
                    CONF_ENABLE_OPTIMAL_STOP,
                    CONF_SCHEDULE_ENTITY,   # The Troublesome Field
                    CONF_LOCK, 
                    CONF_WORKDAY, 
                    CONF_VALVE_POSITION
                ]
                
                for key in optional_keys:
                    if key in user_input:
                        val = user_input[key]
                        # Check for "Empty" markers from UI selectors (but allow False/0)
                        if val in ("", [], vol.UNDEFINED): 
                            update_data[key] = None # Explicitly Store None (Masking)
                        else:
                            update_data[key] = val
                    else:
                        # Missing from input -> Cleared
                        update_data[key] = None
                        
                return self.async_create_entry(title="", data=update_data)
        
        # Build Schema (No Defaults!)
        
        profile_options = list(HEATING_PROFILES.keys())
        
        # Load Defaults for Logic
        current_profile = self._get_val(CONF_HEATING_PROFILE, PROFILE_RADIATOR_NEW)
        profile_data = HEATING_PROFILES.get(current_profile, HEATING_PROFILES[PROFILE_RADIATOR_NEW])
        default_buffer = profile_data.get("buffer", DEFAULT_BUFFER_MIN)

        schema = vol.Schema({
            # primary settings
            vol.Required(CONF_HEATING_PROFILE): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=profile_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="heating_profile"
                )
            ),
            
            # Timing & Comfort
            vol.Optional(CONF_BUFFER_MIN): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=60, mode="box", unit_of_measurement="min")
            ),
            vol.Optional(CONF_EARLIEST_START): selector.NumberSelector(
                 selector.NumberSelectorConfig(min=0, max=1440, step=15, unit_of_measurement="min", mode="box")
            ),
            # Windows
            vol.Optional(CONF_ARRIVAL_WINDOW_START): selector.TimeSelector(),
            vol.Optional(CONF_ARRIVAL_WINDOW_END): selector.TimeSelector(),
            
            vol.Optional(CONF_COMFORT_FALLBACK): selector.NumberSelector(
                 selector.NumberSelectorConfig(min=15.0, max=25.0, step=0.5, unit_of_measurement="\u00B0C", mode="box")
            ),
            
            # Feature Toggles
            vol.Optional(CONF_ENABLE_OPTIMAL_STOP): selector.BooleanSelector(),
            # Schedule
            vol.Optional(CONF_SCHEDULE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["schedule", "input_datetime", "sensor"])
            ),

            # External Control
            vol.Optional(CONF_LOCK): selector.EntitySelector(
                 selector.EntitySelectorConfig(domain=["input_boolean", "binary_sensor", "switch"])
            ),
            vol.Optional(CONF_WORKDAY): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor")),
            vol.Optional(CONF_VALVE_POSITION): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "input_number"]) 
            ),
        })

        # Define Suggestions
        suggestions = {
            CONF_HEATING_PROFILE: current_profile,
            CONF_BUFFER_MIN: self._get_val(CONF_BUFFER_MIN, default_buffer),
            CONF_EARLIEST_START: self._get_val(CONF_EARLIEST_START, 180),
            CONF_ARRIVAL_WINDOW_START: self._get_val(CONF_ARRIVAL_WINDOW_START, DEFAULT_ARRIVAL_WINDOW_START),
            CONF_ARRIVAL_WINDOW_END: self._get_val(CONF_ARRIVAL_WINDOW_END, DEFAULT_ARRIVAL_WINDOW_END),
            CONF_COMFORT_FALLBACK: self._get_val(CONF_COMFORT_FALLBACK, DEFAULT_COMFORT_FALLBACK),
            CONF_ENABLE_OPTIMAL_STOP: self._get_val(CONF_ENABLE_OPTIMAL_STOP, False),
            CONF_SCHEDULE_ENTITY: self._get_val(CONF_SCHEDULE_ENTITY),
            CONF_LOCK: self._get_val(CONF_LOCK),
            CONF_WORKDAY: self._get_val(CONF_WORKDAY),
            CONF_VALVE_POSITION: self._get_val(CONF_VALVE_POSITION),
        }

        return self.async_show_form(
             step_id="init", 
             data_schema=self.add_suggested_values_to_schema(schema, suggestions), 
             errors=errors
        )