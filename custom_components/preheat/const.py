"""Constants for the Preheat integration."""
from typing import Final

DOMAIN: Final = "preheat"
VERSION = "2.8.0-rc1"

# --- Heating Profiles (V3) ---
CONF_HEATING_PROFILE: Final = "heating_profile"

PROFILE_IR: Final = "infrared_air"
PROFILE_RADIATOR_NEW: Final = "radiator_new"
PROFILE_RADIATOR_OLD: Final = "radiator_old"
PROFILE_FLOOR_DRY: Final = "floor_dry"
PROFILE_FLOOR_CONCRETE: Final = "floor_concrete"

HEATING_PROFILES: Final = {
    PROFILE_IR: {
        "name": "Infrared / Air",
        "deadtime": 5,          # Minutes
        "mass_factor_min": 5,   # min/K
        "mass_factor_max": 20,  # min/K
        "default_mass": 10,
        "max_duration": 1.5,    # Hours
        "buffer": 5             # Minutes
    },
    PROFILE_RADIATOR_NEW: {
        "name": "Radiators (Modern)",
        "deadtime": 15,
        "mass_factor_min": 10,
        "mass_factor_max": 40,
        "default_mass": 20,
        "max_duration": 2.5,
        "buffer": 10
    },
    PROFILE_RADIATOR_OLD: {
        "name": "Radiators (Old/Cast Iron)",
        "deadtime": 30,
        "mass_factor_min": 20,
        "mass_factor_max": 60,
        "default_mass": 30,
        "max_duration": 3.0,
        "buffer": 15
    },
    PROFILE_FLOOR_DRY: {
        "name": "Floor Heating (Dry/Light)",
        "deadtime": 45,
        "mass_factor_min": 30,
        "mass_factor_max": 90,
        "default_mass": 50,
        "max_duration": 4.0,
        "buffer": 20
    },
    PROFILE_FLOOR_CONCRETE: {
        "name": "Floor Heating (Concrete/Screed)",
        "deadtime": 120,
        "mass_factor_min": 60,
        "mass_factor_max": 240, 
        "default_mass": 100,
        "max_duration": 8.0,
        "buffer": 30
    }
}

# Technical Constants
INVALID_TEMP: Final = -273.15

# Config keys
CONF_OCCUPANCY: Final = "occupancy_sensor"
CONF_TEMPERATURE: Final = "temperature_sensor"
CONF_CLIMATE: Final = "climate_entity"
CONF_SETPOINT: Final = "setpoint_sensor"
CONF_OUTDOOR_TEMP: Final = "outdoor_temp_sensor"
CONF_WEATHER_ENTITY: Final = "weather_entity"
CONF_WORKDAY: Final = "workday_sensor"
CONF_CALENDAR_ENTITY: Final = "holiday_calendar_entity"
CONF_LOCK: Final = "preheat_lock"

# Mode keys
CONF_PRESET_MODE: Final = "preset_mode"
CONF_EXPERT_MODE: Final = "expert_mode"

# Internal Technical Keys
CONF_EMA_ALPHA: Final = "ema_alpha"
CONF_BUFFER_MIN: Final = "buffer_minutes"
CONF_INITIAL_GAIN: Final = "initial_gain"
CONF_DONT_START_IF_WARM: Final = "dont_start_if_warm"

# Presets Definitions
PRESET_AGGRESSIVE: Final = "aggressive"
PRESET_BALANCED: Final = "balanced"
PRESET_CONSERVATIVE: Final = "conservative"

PRESETS: Final = {
    PRESET_AGGRESSIVE: {
        CONF_BUFFER_MIN: 20,
        CONF_INITIAL_GAIN: 15.0,
        CONF_EMA_ALPHA: 0.5,
        CONF_DONT_START_IF_WARM: False,
    },
    PRESET_BALANCED: {
        CONF_BUFFER_MIN: 15,
        CONF_INITIAL_GAIN: 10.0,
        CONF_EMA_ALPHA: 0.3,
        CONF_DONT_START_IF_WARM: True,
    },
    PRESET_CONSERVATIVE: {
        CONF_BUFFER_MIN: 10,
        CONF_INITIAL_GAIN: 5.0,
        CONF_EMA_ALPHA: 0.15,
        CONF_DONT_START_IF_WARM: True,
    },
}

# Advanced Expert Keys
CONF_COMFORT_MIN: Final = "comfort_min_temp"
CONF_COMFORT_MAX: Final = "comfort_max_temp"
CONF_COMFORT_FALLBACK: Final = "comfort_fallback_temp"
CONF_AIR_TO_OPER_BIAS: Final = "air_to_oper_bias_k"
CONF_MAX_PREHEAT_HOURS: Final = "max_preheat_hours"
CONF_OFF_ONLY_WHEN_WARM: Final = "off_only_when_warm"
CONF_ARRIVAL_WINDOW_START: Final = "arrival_window_start"
CONF_ARRIVAL_WINDOW_END: Final = "arrival_window_end"
CONF_EARLIEST_START: Final = "earliest_start_minutes"
CONF_ONLY_ON_WORKDAYS: Final = "only_on_workdays"
# V2.8
CONF_DEBOUNCE_MIN: Final = "occupancy_debounce_minutes"

# Forecast Integration (V2.4)
CONF_USE_FORECAST: Final = "use_forecast"
CONF_RISK_MODE: Final = "risk_mode"
CONF_FORECAST_CACHE_MIN: Final = "forecast_cache_ttl_min"

RISK_BALANCED: Final = "balanced"
RISK_PESSIMISTIC: Final = "pessimistic"
RISK_OPTIMISTIC: Final = "optimistic"

# Optimal Stop (V2.5)
CONF_ENABLE_OPTIMAL_STOP: Final = "enable_optimal_stop"
CONF_STOP_TOLERANCE: Final = "stop_tolerance"
CONF_MAX_COAST_HOURS: Final = "max_coast_hours"
CONF_SCHEDULE_ENTITY: Final = "schedule_entity"
CONF_PHYSICS_MODE: Final = "physics_mode"
PHYSICS_STANDARD: Final = "standard"
PHYSICS_ADVANCED: Final = "advanced"

# Defaults
DEFAULT_EMA_ALPHA: Final = 0.3
DEFAULT_ARRIVAL_MIN: Final = 300
DEFAULT_EARLIEST_START: Final = 180
DEFAULT_BUFFER_MIN: Final = 10
DEFAULT_DEBOUNCE_MIN: Final = 15
DEFAULT_COMFORT_MIN: Final = 19.0
DEFAULT_COMFORT_MAX: Final = 23.5
DEFAULT_COMFORT_FALLBACK: Final = 21.0
DEFAULT_AIR_TO_OPER_BIAS: Final = 0.0 
DEFAULT_INITIAL_GAIN: Final = 10.0
DEFAULT_MAX_HOURS: Final = 3.0
DEFAULT_ARRIVAL_WINDOW_START: Final = "04:00:00"
DEFAULT_ARRIVAL_WINDOW_END: Final = "20:00:00"
DEFAULT_USE_FORECAST: Final = False
DEFAULT_RISK_MODE: Final = RISK_BALANCED
DEFAULT_CACHE_TTL: Final = 30
DEFAULT_STOP_TOLERANCE: Final = 0.5
DEFAULT_MAX_COAST_HOURS: Final = 4.0

# Storage Attributes
ATTR_LAST_COMFORT_SETPOINT: Final = "last_comfort_setpoint"
ATTR_PREHEAT_STARTED_AT: Final = "preheat_started_at"

# New Storage Keys (v2)
ATTR_MODEL_MASS: Final = "model_mass_factor"
ATTR_MODEL_LOSS: Final = "model_loss_factor"
ATTR_ARRIVAL_HISTORY: Final = "arrival_history_v2" # Stores raw timestamps for clustering

# New Config Keys
CONF_VALVE_POSITION: Final = "valve_position_sensor"

# Physics Defaults
DEFAULT_MASS_FACTOR: Final = 10.0 # Minutes to raise 1°C (Perfect insulation)
DEFAULT_LOSS_FACTOR: Final = 5.0  # Additional minutes per 1°C of outdoor delta
DEFAULT_LEARNING_RATE: Final = 0.1

# --- V3.0 Autonomous Features (Shadow Mode) ---
CONF_PREHEAT_HOLD: Final = "preheat_hold" # Internal switch key

# Gate Thresholds
GATE_MIN_SAVINGS_MIN: Final = 15.0
GATE_MIN_TAU_CONF: Final = 0.6
GATE_MIN_PATTERN_CONF: Final = 0.7
GATE_MAX_FALSE_COASTS: Final = 0.05

# Decision Trace Keys (Contract)
ATTR_DECISION_TRACE: Final = "decision_trace"
SCHEMA_VERSION: Final = 1

KEY_EVALUATED_AT: Final = "evaluated_at"
KEY_PROVIDER_SELECTED: Final = "provider_selected"
KEY_PROVIDER_CANDIDATES: Final = "provider_candidates"
KEY_PROVIDERS_INVALID: Final = "providers_invalid"
KEY_GATES_FAILED: Final = "gates_failed"
KEY_GATE_INPUTS: Final = "gate_inputs"

# Provider IDs
PROVIDER_SCHEDULE: Final = "schedule"
PROVIDER_LEARNED: Final = "learned"
PROVIDER_MANUAL: Final = "manual"
PROVIDER_NONE: Final = "none"

# Invalid/Block Reasons (Taxonomy)
REASON_UNAVAILABLE: Final = "unavailable"
REASON_UNKNOWN: Final = "unknown"
REASON_OFF: Final = "off" # Switch is off
REASON_NO_NEXT_EVENT: Final = "no_next_event"
REASON_PARSE_ERROR: Final = "parse_error"
REASON_END_TOO_SOON: Final = "end_too_soon"
REASON_LOW_CONFIDENCE: Final = "low_confidence"
REASON_BLOCKED_BY_GATES: Final = "blocked_by_gates"
REASON_INSUFFICIENT_DATA: Final = "insufficient_data"

# Gate Failure Keys
GATE_FAIL_SAVINGS: Final = "low_savings"
GATE_FAIL_TAU: Final = "low_tau_conf"
GATE_FAIL_PATTERN: Final = "low_pattern_conf"
GATE_FAIL_LATCH: Final = "setpoint_latch"
GATE_FAIL_MANUAL: Final = "manual_hold"