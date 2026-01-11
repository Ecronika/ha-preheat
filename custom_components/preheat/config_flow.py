"""Config flow for Preheat integration."""
from __future__ import annotations

from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector, entity_registry as er

from .const import (
    DOMAIN,
    CONF_OCCUPANCY,
    CONF_TEMPERATURE,
    CONF_CLIMATE,
    CONF_WEATHER_ENTITY,
    CONF_WORKDAY,
    CONF_LOCK,
    CONF_VALVE_POSITION,
    CONF_HEATING_PROFILE,
    HEATING_PROFILES,
    PROFILE_RADIATOR_NEW,
    CONF_BUFFER_MIN,
    CONF_EARLIEST_START,
    CONF_ARRIVAL_WINDOW_START,
    CONF_ARRIVAL_WINDOW_END,
    DEFAULT_BUFFER_MIN,
    DEFAULT_ARRIVAL_WINDOW_START,
    DEFAULT_ARRIVAL_WINDOW_END,
    CONF_COMFORT_FALLBACK,
    DEFAULT_COMFORT_FALLBACK,
    CONF_ENABLE_OPTIMAL_STOP,
    CONF_SCHEDULE_ENTITY,
    CONF_MAX_PREHEAT_HOURS,
    DEFAULT_MAX_HOURS,
)

# Centralized Option Definitions (Key -> {selector, default})
OPTION_SETTINGS = {
    CONF_HEATING_PROFILE: {
        "selector": selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=list(HEATING_PROFILES.keys()),
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key="heating_profile"
            )
        ),
        "default": PROFILE_RADIATOR_NEW
    },
    CONF_BUFFER_MIN: {
        "selector": selector.NumberSelector(
             selector.NumberSelectorConfig(min=0, max=60, mode="box", unit_of_measurement="min")
        ),
        "default": DEFAULT_BUFFER_MIN # Overridden by Profile Check
    },
    CONF_EARLIEST_START: {
        "selector": selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=1440, step=15, unit_of_measurement="min", mode="box")
        ),
        "default": 180
    },
    CONF_ARRIVAL_WINDOW_START: {
        "selector": selector.TimeSelector(),
        "default": DEFAULT_ARRIVAL_WINDOW_START
    },
    CONF_ARRIVAL_WINDOW_END: {
        "selector": selector.TimeSelector(),
        "default": DEFAULT_ARRIVAL_WINDOW_END
    },
    CONF_COMFORT_FALLBACK: {
        "selector": selector.NumberSelector(
            selector.NumberSelectorConfig(min=15.0, max=25.0, step=0.5, unit_of_measurement="\u00B0C", mode="box")
        ),
        "default": DEFAULT_COMFORT_FALLBACK
    },
    CONF_ENABLE_OPTIMAL_STOP: {
        "selector": selector.BooleanSelector(),
        "default": False
    },
    CONF_SCHEDULE_ENTITY: {
        "selector": selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["schedule", "input_datetime", "sensor"])
        ),
        "default": None
    },
    CONF_LOCK: {
        "selector": selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["input_boolean", "binary_sensor", "switch"])
        ),
        "default": None
    },
    CONF_WORKDAY: {
        "selector": selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor")),
        "default": None
    },
    CONF_VALVE_POSITION: {
        "selector": selector.EntitySelector(
             selector.EntitySelectorConfig(domain=["sensor", "input_number"]) 
        ),
        "default": None
    },
    CONF_MAX_PREHEAT_HOURS: {
        "selector": selector.NumberSelector(
             selector.NumberSelectorConfig(min=0.5, max=12.0, step=0.5, unit_of_measurement="h", mode="box")
        ),
        "default": DEFAULT_MAX_HOURS # Overridden by Profile Check
    },
}

class PreheatingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Preheat."""

    VERSION = 4

    def _validate_entity_ids(self, user_input: dict[str, Any]) -> dict[str, str]:
        """Validate existence of entities using Entity Registry and State Machine."""
        errors = {}
        registry = er.async_get(self.hass)
        
        # Keys that expect entities
        keys_to_check = [
            CONF_OCCUPANCY, CONF_CLIMATE, 
            CONF_TEMPERATURE, CONF_WEATHER_ENTITY
        ]

        for key in keys_to_check:
            entity_id = user_input.get(key)
            if entity_id:
                # 1. Check Registry (Best Practice for existence, works even if unavailable)
                entry = registry.async_get(entity_id)
                # 2. Check State (Fallback for virtual/legacy entities)
                state = self.hass.states.get(entity_id)
                
                if not entry and not state:
                     errors[key] = "entity_not_found"
        
        return errors

    def _build_entity_schema(self, include_name: bool = False, include_profile: bool = False, include_climate: bool = True, defaults: dict | None = None) -> vol.Schema:
        """Build reusable entity selection schema."""
        defaults = defaults or {}
        schema_dict = {}
        
        if include_name:
            schema_dict[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "Intelligent Preheat"))] = str
        
        # Core Entities 
        schema_dict.update({
            vol.Required(CONF_OCCUPANCY, default=defaults.get(CONF_OCCUPANCY, vol.UNDEFINED)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            )
        })

        if include_climate:
            schema_dict[vol.Required(CONF_CLIMATE, default=defaults.get(CONF_CLIMATE, vol.UNDEFINED))] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            )
        
        # Optional: Use UNDEFINED default, rely on suggested_values or user input
        schema_dict.update({
            vol.Optional(CONF_TEMPERATURE, default=vol.UNDEFINED): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "input_number"])
            ),
            vol.Optional(CONF_WEATHER_ENTITY, default=vol.UNDEFINED): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
        })
        
        # Profile Selection (Setup only)
        if include_profile:
             # Use centralized definition for consistency
             settings = OPTION_SETTINGS[CONF_HEATING_PROFILE]
             schema_dict[vol.Required(CONF_HEATING_PROFILE, default=defaults.get(CONF_HEATING_PROFILE, settings["default"]))] = settings["selector"]
        
        return vol.Schema(schema_dict)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
             # Validate
             errors = self._validate_entity_ids(user_input)
             
             if not errors:
                 # Set Unique ID (Stability Preferred: Registry ID > Entity ID)
                 climate_id = user_input[CONF_CLIMATE]
                 registry = er.async_get(self.hass)
                 reg_entry = registry.async_get(climate_id)
                 
                 unique_id = climate_id
                 if reg_entry and reg_entry.id:
                     unique_id = reg_entry.id # Stable UUID
                 
                 await self.async_set_unique_id(unique_id)
                 self._abort_if_unique_id_configured()

                 # Build Data (Clean Storage: Only save what is set)
                 data = {
                     CONF_OCCUPANCY: user_input[CONF_OCCUPANCY],
                     CONF_CLIMATE: climate_id,
                 }
                 if user_input.get(CONF_TEMPERATURE):
                     data[CONF_TEMPERATURE] = user_input[CONF_TEMPERATURE]
                 if user_input.get(CONF_WEATHER_ENTITY):
                      data[CONF_WEATHER_ENTITY] = user_input[CONF_WEATHER_ENTITY]

                 # Build Options (Explicit Defaults with Profile Logic)
                 selected_profile = user_input.get(CONF_HEATING_PROFILE, PROFILE_RADIATOR_NEW)
                 profile_data = HEATING_PROFILES.get(selected_profile, HEATING_PROFILES[PROFILE_RADIATOR_NEW])
                 
                 options = {
                     CONF_HEATING_PROFILE: selected_profile,
                     CONF_BUFFER_MIN: profile_data.get("buffer", DEFAULT_BUFFER_MIN), 
                     CONF_ARRIVAL_WINDOW_START: DEFAULT_ARRIVAL_WINDOW_START,
                     CONF_ARRIVAL_WINDOW_END: DEFAULT_ARRIVAL_WINDOW_END,
                 }

                 return self.async_create_entry(
                    title=user_input.get(CONF_NAME, climate_id), # Fallback title to Entity ID text usually fine
                    data=data,
                    options=options
                )

        # Use Suggested Values for Defaults logic
        defaults = user_input or {}
        schema = self._build_entity_schema(include_name=True, include_profile=True, include_climate=True, defaults=defaults)
        
        # Add suggestions for optional fields if present in input
        suggestions = {k: v for k, v in defaults.items() if v is not None}
        
        return self.async_show_form(
            step_id="user", 
            data_schema=self.add_suggested_values_to_schema(schema, suggestions), 
            errors=errors
        )


    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle re-configuration."""
        errors = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
             errors = self._validate_entity_ids(user_input)
             
             if not errors:
                # Update Data (Preserve Climate!)
                update_data = {
                    CONF_CLIMATE: entry.data[CONF_CLIMATE], # Reserved
                    CONF_OCCUPANCY: user_input[CONF_OCCUPANCY],
                }
                if user_input.get(CONF_TEMPERATURE):
                     update_data[CONF_TEMPERATURE] = user_input[CONF_TEMPERATURE]
                if user_input.get(CONF_WEATHER_ENTITY):
                     update_data[CONF_WEATHER_ENTITY] = user_input[CONF_WEATHER_ENTITY]
                
                return self.async_update_reload_and_abort(entry, data=update_data)

        # Config + Options (for suggestions)
        data = {**entry.data, **entry.options}
        
        # Reconfigure Schema: Explicitly EXCLUDE Climate via flag (Locking strategy)
        schema = self._build_entity_schema(include_name=False, include_profile=False, include_climate=False, defaults=data)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(schema, data),
            description_placeholders={"climate_name": entry.data.get(CONF_CLIMATE, "unknown")},
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
        """Manage options."""
        errors = {}
        
        if user_input is not None:
            # Defensive check (User feedback: > 60)
            if user_input.get(CONF_BUFFER_MIN, 0) > 60:
                 errors[CONF_BUFFER_MIN] = "buffer_too_high"
            
            if not errors:
                # SAFE MERGE STRATEGY
                # 1. Start with copy of existing options
                new_options = dict(self._config_entry.options)
                
                # 2. Iterate keys presented in this form (SCHEMA is source of truth for what can change)
                all_keys = list(OPTION_SETTINGS.keys())
                
                for key in all_keys:
                    if key in user_input:
                        val = user_input[key]
                        # Clean "Empty" values (None, "", [], UNDEFINED)
                        if val in (None, "", [], vol.UNDEFINED):
                             # Remove key if present (Clean Storage)
                             new_options.pop(key, None)
                        else:
                             # Update value
                             new_options[key] = val
                    else:
                        # Key expected but missing from input?
                        # In HA Options Flow, if key is missing but was in schema, it might mean "cleared" depending on frontend.
                        # However, user suggested blocking updates for missing keys to be safe ("Safe Bet").
                        # We do NOT touch new_options[key] here.
                        pass
                
                return self.async_create_entry(title="", data=new_options)
        
        # Build Schema dynamically
        schema_dict = {}
        suggestions = {}
        
        # Profile Logic for default buffer suggestion
        current_profile = self._get_val(CONF_HEATING_PROFILE, PROFILE_RADIATOR_NEW)
        profile_data = HEATING_PROFILES.get(current_profile, HEATING_PROFILES[PROFILE_RADIATOR_NEW])
        
        for key, settings in OPTION_SETTINGS.items():
            schema_dict[vol.Optional(key)] = settings["selector"]
            
            # Smart Default handling for suggestions
            default_val = settings["default"]
            if key == CONF_BUFFER_MIN:
                default_val = profile_data.get("buffer", default_val)
            elif key == CONF_MAX_PREHEAT_HOURS:
                default_val = profile_data.get("max_duration", default_val)
            
            # Load current value or fallback
            suggestions[key] = self._get_val(key, default_val)

        return self.async_show_form(
             step_id="init", 
             data_schema=self.add_suggested_values_to_schema(vol.Schema(schema_dict), suggestions), 
             errors=errors
        )