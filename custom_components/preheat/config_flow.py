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
    CONF_ONLY_ON_WORKDAYS,
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
    DEFAULT_USE_FORECAST,
    DEFAULT_RISK_MODE,
    # Optimal Stop
    CONF_ENABLE_OPTIMAL_STOP,
    CONF_STOP_TOLERANCE,
    CONF_MAX_COAST_HOURS,
    CONF_SCHEDULE_ENTITY,
    DEFAULT_STOP_TOLERANCE,
    DEFAULT_MAX_COAST_HOURS,
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
            # Climate is now REQUIRED (Central control unit)
            vol.Required(CONF_CLIMATE): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            # Temperature is now OPTIONAL (Fallback if Climate is inaccurate)
            vol.Optional(CONF_TEMPERATURE): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number"])
            ),
            # Weather & Outdoor (Recommended for Physics)
            vol.Optional(CONF_WEATHER_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            # Key Learning Settings (Now on Main Page)
            vol.Required(CONF_HEATING_PROFILE, default=PROFILE_RADIATOR_NEW): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=profile_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="heating_profile"
                )
            ),
            vol.Optional(CONF_ARRIVAL_WINDOW_START, default=DEFAULT_ARRIVAL_WINDOW_START): selector.TimeSelector(),
            vol.Optional(CONF_ARRIVAL_WINDOW_END, default=DEFAULT_ARRIVAL_WINDOW_END): selector.TimeSelector(),
            
            # Key Feature: Optimal Stop (Promoted)
            vol.Optional(CONF_ENABLE_OPTIMAL_STOP, default=False): selector.BooleanSelector(),

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
        stored_expert = self._get_val(CONF_EXPERT_MODE, False)
        errors = {}
        
        # Determine if we are currently SHOWING the expert form (based on input)
        # If user_input has a key that only exists in expert mode (e.g. CONF_VALVE_POSITION or CONF_BUFFER_MIN),
        # then we are submitting the Expert Form.
        # Note: CONF_BUFFER_MIN is now expert-only.
        is_submitting_expert_form = user_input is not None and CONF_BUFFER_MIN in user_input
        
        if user_input is not None:
             # 1. Validation
            if user_input.get(CONF_BUFFER_MIN, 0) > 60:
                 errors[CONF_BUFFER_MIN] = "buffer_too_high"
            if user_input.get(CONF_MAX_PREHEAT_HOURS, 3.0) > 5.0:
                 errors[CONF_MAX_PREHEAT_HOURS] = "max_duration_too_high"
            
            # 2. Logic: Should we Reload or Save?
            requested_expert = user_input.get(CONF_EXPERT_MODE, False)
            
            # Case A: We want to switch Mode (Simple <-> Expert)
            # This happens if requested mode != what we see. 
            # But "what we see" is inferred. 
            # If we submitted Simple Form (no buffer_min) and requested Expert -> Reload.
            # If we submitted Expert Form (has buffer_min) and requested Simple -> Reload.
            # If we submitted Expert Form and requested Expert -> Save.
            
            should_reload = False
            
            if requested_expert and not is_submitting_expert_form:
                # User checked "Show Expert" on Simple Form -> Expand
                should_reload = True
            elif not requested_expert and is_submitting_expert_form:
                 # User unchecked "Show Expert" on Expert Form -> Collapse
                 should_reload = True
            
            # If errors exist, always reload (to show errors)
            if errors or should_reload:
                 return self.async_show_form(
                    step_id="init", 
                    data_schema=self._build_schema(show_expert=requested_expert, user_input=user_input),
                    errors=errors
                )
            
            # 3. Save
            return self.async_create_entry(title="", data=user_input)

        # First Open: Use stored expert state
        return self.async_show_form(step_id="init", data_schema=self._build_schema(show_expert=stored_expert), errors=errors)

    def _build_schema(self, show_expert: bool, user_input: dict[str, Any] | None = None) -> vol.Schema:

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
            
            # Key Settings (Moved from Expert)
            vol.Optional(CONF_ARRIVAL_WINDOW_START): selector.TimeSelector(),
            vol.Optional(CONF_ARRIVAL_WINDOW_END): selector.TimeSelector(),
            vol.Optional(CONF_ENABLE_OPTIMAL_STOP): selector.BooleanSelector(),

            vol.Optional(CONF_EXPERT_MODE): selector.BooleanSelector()
        }

        if show_expert:
            schema.update({
                vol.Optional(CONF_VALVE_POSITION): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "input_number"]) 
                ),
                vol.Optional(CONF_LOCK): selector.EntitySelector(selector.EntitySelectorConfig(domain="input_boolean")),
                vol.Optional(CONF_WORKDAY): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor")),
                vol.Optional(CONF_ONLY_ON_WORKDAYS): selector.BooleanSelector(),
                
                # Forecast Integration
                vol.Optional(CONF_USE_FORECAST): selector.BooleanSelector(),
                vol.Optional(CONF_RISK_MODE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": RISK_BALANCED, "label": "Balanced (Integral)"},
                            {"value": RISK_PESSIMISTIC, "label": "Pessimistic (P10 - Comfort)"},
                            {"value": RISK_OPTIMISTIC, "label": "Optimistic (P90 - Savings)"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                        translation_key="risk_mode"
                    )
                ),

                # Optimal Stop (Advanced Tuning)
                vol.Optional(CONF_SCHEDULE_ENTITY): selector.EntitySelector(
                     selector.EntitySelectorConfig(domain="schedule")
                ),
                vol.Optional(CONF_STOP_TOLERANCE): selector.NumberSelector(
                     selector.NumberSelectorConfig(min=0.1, max=2.0, step=0.1, unit_of_measurement="K", mode="box")
                ),
                vol.Optional(CONF_MAX_COAST_HOURS): selector.NumberSelector(
                     selector.NumberSelectorConfig(min=0.5, max=12.0, step=0.5, unit_of_measurement="h", mode="box")
                ),
                
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
        # 1. Start with Stored Data
        data = {**self.config_entry.data, **self.config_entry.options}
        
        # 2. Merge with User Input (if reloading form)
        if user_input:
            data.update(user_input)
            
        # 3. Resolve Profile Defaults (Only if still missing)
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
        if CONF_WORKDAY not in data: data[CONF_WORKDAY] = None
        if CONF_ONLY_ON_WORKDAYS not in data: data[CONF_ONLY_ON_WORKDAYS] = False
        
        if CONF_USE_FORECAST not in data: data[CONF_USE_FORECAST] = DEFAULT_USE_FORECAST
        if CONF_RISK_MODE not in data: data[CONF_RISK_MODE] = DEFAULT_RISK_MODE
        
        if CONF_ENABLE_OPTIMAL_STOP not in data: data[CONF_ENABLE_OPTIMAL_STOP] = False
        if CONF_SCHEDULE_ENTITY not in data: data[CONF_SCHEDULE_ENTITY] = None
        if CONF_STOP_TOLERANCE not in data: data[CONF_STOP_TOLERANCE] = DEFAULT_STOP_TOLERANCE
        if CONF_MAX_COAST_HOURS not in data: data[CONF_MAX_COAST_HOURS] = DEFAULT_MAX_COAST_HOURS
        
        if CONF_ARRIVAL_WINDOW_START not in data: data[CONF_ARRIVAL_WINDOW_START] = DEFAULT_ARRIVAL_WINDOW_START
        if CONF_ARRIVAL_WINDOW_END not in data: data[CONF_ARRIVAL_WINDOW_END] = DEFAULT_ARRIVAL_WINDOW_END
        
        if CONF_AIR_TO_OPER_BIAS not in data: data[CONF_AIR_TO_OPER_BIAS] = 0.0
        if CONF_EARLIEST_START not in data: data[CONF_EARLIEST_START] = 180 # 3h default
        
        if CONF_COMFORT_MIN not in data: data[CONF_COMFORT_MIN] = DEFAULT_COMFORT_MIN
        if CONF_COMFORT_MAX not in data: data[CONF_COMFORT_MAX] = DEFAULT_COMFORT_MAX
        if CONF_COMFORT_FALLBACK not in data: data[CONF_COMFORT_FALLBACK] = DEFAULT_COMFORT_FALLBACK

        data[CONF_EXPERT_MODE] = show_expert
        
        return self.add_suggested_values_to_schema(vol.Schema(schema), data)