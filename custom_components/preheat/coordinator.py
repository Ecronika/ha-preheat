"""Coordinator for Preheat integration."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, date, time, timezone
import logging
from typing import Any, TYPE_CHECKING
import math


from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import storage
from homeassistant.core import HomeAssistant, callback

from homeassistant.helpers.issue_registry import async_create_issue, async_delete_issue, IssueSeverity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.const import STATE_ON, STATE_OFF

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

from .math_preheat import root_find_duration
from .weather_service import WeatherService
from .planner import PreheatPlanner
from .physics import ThermalPhysics
from .optimal_stop import OptimalStopManager
from .types import Context, Prediction, Decision

from .const import (
    DOMAIN,
    INVALID_TEMP,
    CONF_OCCUPANCY,
    CONF_TEMPERATURE,
    CONF_CLIMATE,
    CONF_SETPOINT,
    CONF_OUTDOOR_TEMP,
    CONF_WEATHER_ENTITY,
    CONF_WORKDAY,
    CONF_CALENDAR_ENTITY,
    CONF_ONLY_ON_WORKDAYS,
    CONF_LOCK,
    CONF_PRESET_MODE,
    CONF_EXPERT_MODE,
    CONF_INITIAL_GAIN,
    CONF_EMA_ALPHA,
    CONF_BUFFER_MIN,
    CONF_DONT_START_IF_WARM,
    CONF_EARLIEST_START,
    # CONF_START_GRACE, # Unused

    CONF_AIR_TO_OPER_BIAS,
    CONF_MAX_PREHEAT_HOURS,
    CONF_OFF_ONLY_WHEN_WARM,
    CONF_ARRIVAL_WINDOW_START,
    CONF_ARRIVAL_WINDOW_END,
    CONF_VALVE_POSITION,
    CONF_DEBOUNCE_MIN,
    CONF_PHYSICS_MODE,
    PHYSICS_STANDARD,
    PHYSICS_ADVANCED,
    CONF_COMFORT_MIN,
    CONF_COMFORT_FALLBACK,
    DEFAULT_COMFORT_MIN,
    DEFAULT_COMFORT_FALLBACK,
    # PRESETS, # Replaced by Profiles logic in _get_conf
    DEFAULT_ARRIVAL_WINDOW_START,
    DEFAULT_STOP_TOLERANCE,
    DEFAULT_MAX_COAST_HOURS,
    DEFAULT_ARRIVAL_WINDOW_END,
    DEFAULT_DEBOUNCE_MIN,
    DEFAULT_MAX_HOURS,

    ATTR_MODEL_MASS,
    ATTR_MODEL_LOSS,
    ATTR_ARRIVAL_HISTORY,
    # V3
    CONF_HEATING_PROFILE,
    HEATING_PROFILES,
    PROFILE_RADIATOR_NEW,
    # Forecast V2.4
    CONF_USE_FORECAST,
    CONF_RISK_MODE,
    RISK_BALANCED,
    # Optimal Stop
    CONF_ENABLE_OPTIMAL_STOP,
    CONF_STOP_TOLERANCE,
    CONF_MAX_COAST_HOURS,
    CONF_SCHEDULE_ENTITY,
    # V3 Provider Constants
    PROVIDER_SCHEDULE,
    PROVIDER_LEARNED,
    PROVIDER_MANUAL,
    PROVIDER_NONE,
    ATTR_DECISION_TRACE,
    SCHEMA_VERSION,
    KEY_EVALUATED_AT,
    KEY_PROVIDER_SELECTED,
    KEY_PROVIDER_CANDIDATES,
    KEY_PROVIDERS_INVALID,
    KEY_GATES_FAILED,
    KEY_GATE_INPUTS,
    GATE_FAIL_MANUAL,
    GATE_MIN_SAVINGS_MIN,
    GATE_MIN_TAU_CONF,
    GATE_MIN_PATTERN_CONF,
    REASON_UNAVAILABLE,
    REASON_UNKNOWN,
    REASON_OFF,
    REASON_NO_NEXT_EVENT,
    REASON_PARSE_ERROR,
    REASON_END_TOO_SOON,
    REASON_LOW_CONFIDENCE,
    REASON_BLOCKED_BY_GATES,
    REASON_INSUFFICIENT_DATA,
    REASON_BLOCKED_BY_GATES,
    REASON_INSUFFICIENT_DATA,
    REASON_EXTERNAL_INHIBIT,
    # Architecture Constants
    DIAG_STALE_SENSOR_SEC,
    FROST_PROTECTION_TEMP,
    FROST_HYSTERESIS,
    STARTUP_GRACE_SEC,
    WINDOW_OPEN_GRADIENT,
    WINDOW_OPEN_TIME,
    WINDOW_COOLDOWN_MIN
)

from .planner import PreheatPlanner
from .patterns import MIN_CLUSTER_POINTS
from .physics import ThermalPhysics, ThermalModelData
from .history_buffer import RingBuffer, DeadtimeAnalyzer, HistoryPoint
from .weather_service import WeatherService
from .optimal_stop import OptimalStopManager, SessionResolver
from .cooling_analyzer import CoolingAnalyzer
from . import math_preheat
from .providers import (
    ScheduleProvider,
    LearnedDepartureProvider,
    ProviderDecision
)
from .diagnostics import DiagnosticsManager
from .session_manager import SessionManager


_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 4 
STORAGE_KEY_TEMPLATE = "preheat.{}"

@dataclass(frozen=True)
class PreheatData:
    """Class to hold coordinator data."""
    preheat_active: bool
    next_start_time: datetime | None
    operative_temp: float | None
    target_setpoint: float
    next_arrival: datetime | None
    
    # Debug / Sensor Attributes
    predicted_duration: float
    mass_factor: float
    loss_factor: float
    learning_active: bool
    schedule_summary: dict[str, str] | None = None
    departure_summary: dict[str, str] | None = None
    valve_signal: float | None = None
    window_open: bool = False
    outdoor_temp: float | None = None
    last_comfort_setpoint: float | None = None
    deadtime: float = 0.0 # V3
    is_occupied: bool = False # V2.9
    
    # Scheduled Stop
    next_departure: datetime | None = None
    
    # Optimal Stop V2.5
    optimal_stop_active: bool = False
    optimal_stop_time: datetime | None = None
    stop_reason: str | None = None
    savings_total: float = 0.0
    savings_remaining: float = 0.0
    coast_tau: float = 0.0
    tau_confidence: float = 0.0

    # v2.6 Multi-Modal Pattern Data
    pattern_type: str | None = None
    pattern_confidence: float = 0.0
    pattern_stability: float = 0.0
    detected_modes: dict[str, int] | None = None
    fallback_used: bool = False
    
    # v3.0 Trace
    decision_trace: dict[str, Any] | None = None
    
    # v2.9 Logic
    hvac_action: str | None = None
    hvac_mode: str | None = None

class PreheatingCoordinator(DataUpdateCoordinator[PreheatData]):
    """Coordinator to manage preheating logic."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(minutes=1),
            config_entry=entry,
        )
        
        # Calendar Cache
        self._calendar_cache: dict[str, Any] = {
            "last_update": datetime.min.replace(tzinfo=timezone.utc),
            "blocked_dates": set()
        }

        self.entry = entry
        self.device_name = entry.title
        
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY_TEMPLATE.format(entry.entry_id))
        
        # Core Modules
        self.planner = PreheatPlanner()
        # V3: Init Buffer and Analyzer
        self.history_buffer = RingBuffer(capacity=360) # 6 hours
        self.deadtime_analyzer = DeadtimeAnalyzer()
        
        # V2.5: Optimal Stop
        self.optimal_stop_manager = OptimalStopManager(hass)
        self.cooling_analyzer = CoolingAnalyzer()
        self.session_resolver = None
        
        # V3.0: Providers & Arbitration
        self.hold_active = False
        
        # V2.8: Session State Machine
        debounce_min = self._get_conf(CONF_DEBOUNCE_MIN, DEFAULT_DEBOUNCE_MIN)
        self.session_manager = SessionManager(debounce_min, self)
        
        self.schedule_provider = ScheduleProvider(hass, entry, self.optimal_stop_manager)
        
        gate_thresholds = {
            "savings_min": GATE_MIN_SAVINGS_MIN,
            "tau_conf_min": GATE_MIN_TAU_CONF,
            "pattern_conf_min": GATE_MIN_PATTERN_CONF
        }
        self.learned_provider = LearnedDepartureProvider(self.planner, gate_thresholds)
        

        
        # Init Physics with minimal default until loaded
        self.physics = ThermalPhysics()
        
        # Internal store for non-physics meta-data (like migration versions)
        self.extra_store_data = {}
        
        # State
        self._preheat_started_at: datetime | None = None
        self._start_temp: float | None = None
        # self._occupancy_on_since: datetime | None = None # Moved to SessionManager
        self._preheat_active: bool = False
        self._frost_active: bool = False # Safety override (v2.9.1)
        self._last_opt_active: bool = False # Track edge for events
        self.enable_active: bool = True # Master Switch
        self._last_comfort_setpoint: float | None = None
        
        # Window Detection State
        self._prev_temp: float | None = None
        self._prev_temp_time: datetime | None = None
        self._window_open_detected: bool = False
        self._external_inhibit: bool = False # Init to prevent AttributeError
        self._window_cooldown_counter: int = 0
        
        # V2.9.1: Fix Zero Duration Glitch
        self._last_predicted_duration: float = 0.0
        
        # Caching
        self._cached_outdoor_temp: float = 10.0
        self._last_weather_check: datetime | None = None
        self._last_weather_check: datetime | None = None
        self.weather_service: WeatherService | None = None
        weather_entity = self._get_conf(CONF_WEATHER_ENTITY)
        if weather_entity:
            from .weather_service import WeatherService
            # Get Risk Mode for Forecast
            # risk_mode = self._get_conf(CONF_RISK_MODE, RISK_BALANCED)
            # WeatherService does not accept risk_mode currently.
            self.weather_service = WeatherService(hass, weather_entity)
        
        # Shadow Metrics (In-Memory)
        self._shadow_metrics = {
            "safety_violations": 0,
            "cumulative_shadow_savings": 0.0,
            "simulated_error_count": 0
        }
        
        # Logging state
        self._last_shadow_log_state: bool = False
        
        self._startup_time = dt_util.utcnow()
        
        # Diagnostics Persistence (v2.9.1)
        # Moved to DiagnosticsManager, but we need to load it.
        # Temp store for migration if needed, but Manager handles it.
        self.diagnostics = DiagnosticsManager(hass, entry, self)
        
        self.decision_trace = {}
        self._consecutive_failures = 0
        
        self.bootstrap_done = False

        


        self._setup_listeners()
        


    @property
    def window_open_detected(self) -> bool:
        return self._window_open_detected

    def _get_conf(self, key: str, default: Any = None) -> Any:
        """Get config value from options, falling back to Profile > defaults."""
        options = self.entry.options
        
        # 1. Direct Options (Expert Overrides or Configured values)
        if key in options:
             return options[key]
        if key in self.entry.data:
             return self.entry.data[key]
             
        # 2. Dynamic Defaults from Profile (V3) / Context (Action 2.3)
        profile_key = options.get(CONF_HEATING_PROFILE, self.entry.data.get(CONF_HEATING_PROFILE, PROFILE_RADIATOR_NEW))
        profile = HEATING_PROFILES.get(profile_key, HEATING_PROFILES[PROFILE_RADIATOR_NEW])
        
        # Action 2.3: Config Cleanup - Map Legacy Keys to Profile/Context
        
        # Physics / Weather
        if key == CONF_PHYSICS_MODE or key == CONF_USE_FORECAST:
            # Auto-enable Advanced Physics if Weather Entity is configured
            if self.entry.data.get(CONF_WEATHER_ENTITY) or self.entry.options.get(CONF_WEATHER_ENTITY):
                 return PHYSICS_ADVANCED if key == CONF_PHYSICS_MODE else True
            return PHYSICS_STANDARD if key == CONF_PHYSICS_MODE else False
            
        # Tuning Parameters (From Profile)
        if key == CONF_BUFFER_MIN and "buffer" in profile:
             return profile["buffer"]
        if key == CONF_MAX_PREHEAT_HOURS and "max_duration" in profile:
             return profile["max_duration"]
        if key == CONF_INITIAL_GAIN and "default_mass" in profile:
             return profile["default_mass"]
        if key == CONF_MAX_COAST_HOURS and "default_coast" in profile:
             return profile.get("default_coast", DEFAULT_MAX_COAST_HOURS)

        # Hardcoded Best Practices (Removal of Expert Tweaks)
        if key == CONF_RISK_MODE: return RISK_BALANCED
        if key == CONF_EMA_ALPHA: return 0.3
        if key == CONF_STOP_TOLERANCE: return 0.5
        if key == CONF_DONT_START_IF_WARM: return True
        if key == CONF_AIR_TO_OPER_BIAS: return 0.0
             
        # 3. Fallback to code defaults
        return default


    async def async_load_data(self) -> None:
        """Load learned data from storage."""
        try:
            data = await self._store.async_load()
            if not data: data = {}
            
            if data:
                # Load History
                history = data.get(ATTR_ARRIVAL_HISTORY, {})
                # Migration from v1 keys if v2 missing?
                # Legacy v1 warning removed (Architecture Professionalization)

                
                # v2.9.0 Fix: Include departure data (key "888") in planner initialization
                # The planner's _load_history() expects "888" key in the passed dict.
                if "888" in data:
                    history["888"] = data["888"]
                
                self.planner = PreheatPlanner(history)
                
                # Fix: Update Provider's reference to the new planner object
                self.learned_provider.planner = self.planner
                
                # Load Physics
                mass_factor = None
                # Legacy 'learned_gain' [min/K] maps directly to v2 'mass_factor' [min/K].
                if "learned_gain" in data:
                    try:
                        lg = float(data["learned_gain"])
                        mass_factor = max(1.0, min(120.0, lg))
                        _LOGGER.info("Migrated legacy gain %.2f to mass_factor.", lg)
                    except ValueError: pass

                mass = data.get(ATTR_MODEL_MASS, mass_factor if mass_factor is not None else data.get("learned_gain")) # Fallback
                # If we fallback to Gain, mass roughly equals Gain. Loss depends on defaults.
                
                # Get Configured Parameters
                profile_key = self._get_conf(CONF_HEATING_PROFILE, PROFILE_RADIATOR_NEW)
                profile_data = HEATING_PROFILES.get(profile_key, HEATING_PROFILES[PROFILE_RADIATOR_NEW])
                mass = data.get(ATTR_MODEL_MASS, mass_factor if mass_factor is not None else profile_data["default_mass"])

                p_data = ThermalModelData(
                    mass_factor=mass,
                    loss_factor=data.get(ATTR_MODEL_LOSS, 5.0), # Default
                    sample_count=data.get("sample_count", 0),
                    avg_error=data.get("avg_error", 0.0),
                    deadtime=data.get("deadtime", 0.0)
                ) if mass is not None or ATTR_MODEL_LOSS in data else None
                
                learning_rate = self._get_conf(CONF_EMA_ALPHA, 0.1)
                
                self.physics = ThermalPhysics(
                    data=p_data,
                    profile_data=profile_data,
                    learning_rate=learning_rate
                )
                
                # V2.5 Load Cooling Data
                self.cooling_analyzer.learned_tau = data.get("model_cooling_tau", 4.0)
                self.cooling_analyzer.confidence = data.get("cooling_confidence", 0.0)
                
                # V2.9.1 Load Diagnostics Data
                # V2.9.1 Load Diagnostics Data
                loaded_diag = data.get("diagnostics", {})
                if loaded_diag:
                     # Merge to preserve defaults/types
                     self.diagnostics.load_data(loaded_diag)
                
                self._last_comfort_setpoint = data.get("last_comfort_setpoint")
                
                # --- Smart Migration v2.7.1 ---
                # Check Physics Version
                physics_version = data.get("physics_version", 1)
                
                if physics_version < 2:
                    _LOGGER.warning("Migrating Thermal Model to Physics v2 (removing scaler artifact)")
                    
                    # 1. Preserve Mass Factor (It was valid/independent)
                    # 2. Reset Loss Factor (It was calibrated to dt_in/2 scaler, now invalid)
                    profile_key = self._get_conf(CONF_HEATING_PROFILE, PROFILE_RADIATOR_NEW)
                    profile_data = HEATING_PROFILES.get(profile_key, HEATING_PROFILES[PROFILE_RADIATOR_NEW])
                    default_loss = profile_data.get("default_loss", 5.0)
                    
                    old_loss = self.physics.loss_factor
                    self.physics.loss_factor = default_loss
                    # Slight penalty to reduce confidence, but preserve learning progress
                    # (User had X samples, now X-2 but mass_factor stays valid)
                    self.physics.sample_count = max(0, self.physics.sample_count - 2)
                    
                    _LOGGER.info(f"Migration: Mass {self.physics.mass_factor:.2f} kept. Loss {old_loss:.2f} -> {default_loss:.2f} reset.")
                    
                    # Create Repair Issue (Informational)
                    async_create_issue(
                        self.hass,
                        DOMAIN,
                        f"physics_partial_reset_{self.entry.entry_id}",
                        is_fixable=False,
                        is_persistent=True,
                        severity=IssueSeverity.WARNING,
                        translation_key="physics_partial_reset",
                        translation_placeholders={
                            "samples": str(self.physics.sample_count),
                            "learn_more_url": "https://github.com/Ecronika/ha-preheat/releases/tag/v2.7.1"
                        },
                        learn_more_url="https://github.com/Ecronika/ha-preheat/releases/tag/v2.7.1"
                    )
                    
                    # Mark as Migrated
                    self.extra_store_data["physics_version"] = 2
                    # IMPORTANT: Save immediately to prevent re-running migration (and double penalty) on crash/restart
                    await self._async_save_data()
                else:
                    self.extra_store_data["physics_version"] = physics_version
            
            # Load Enable State (Default True)
            self.enable_active = data.get("enable_active", True)
            
            # Load Bootstrap State FIRST (before scheduling timer)
            self.bootstrap_done = data.get("bootstrap_done", False)

            # v2.9.0 Fix: If bootstrap claimed done, but departures missing (e.g. key counting bug), reset it.
            if self.bootstrap_done:
                 # v2.9.2: Require at least MIN_CLUSTER_POINTS points (Cluster Minimum). 
                 # If we have < MIN_CLUSTER_POINTS points, the Summary shows "-", so we should scan for more.
                 has_departures = any(len(entries) >= MIN_CLUSTER_POINTS for entries in self.planner.history_departure.values())
                 if not has_departures:
                      _LOGGER.info("Bootstrap claimed done, but data sparse (< 3 points). Resetting flag to force retry.")
                      self.bootstrap_done = False

            # v2.9.2: Retroactive Bootstrap (Auto-Scan)
            # Schedule scan ONLY if bootstrap is not done (after loading from storage)
            if not self.bootstrap_done:
                 # Short delay to let HA fully initialize before querying recorder
                 _LOGGER.info("[%s] History scan will start in 30 seconds...", self.device_name)
                 self.hass.loop.call_later(30, lambda: self.hass.async_create_task(self._check_bootstrap()))
                
        except Exception:
            _LOGGER.exception("Failed loading data")
            await self._async_save_data()

    def _get_data_for_storage(self) -> dict:
        """Prepare data for storage (sync helper)."""
        data_physics = self.physics.to_dict()
        data_planner = self.planner.to_dict()
        
        return {
            "schema_version": 1,
            "physics_version": self.extra_store_data.get("physics_version", 2),
            ATTR_ARRIVAL_HISTORY: data_planner,
            ATTR_MODEL_MASS: data_physics["mass_factor"],
            ATTR_MODEL_LOSS: data_physics["loss_factor"],
            "sample_count": data_physics["sample_count"],
            "avg_error": data_physics.get("avg_error", 0.0),
            "last_comfort_setpoint": self._last_comfort_setpoint,
            # V2.5
            "model_cooling_tau": self.cooling_analyzer.learned_tau,
            "cooling_confidence": self.cooling_analyzer.confidence,
            "enable_active": self.enable_active,
            # V2.9.1
            "diagnostics": self.diagnostics.data,
            # V2.9.2
            "bootstrap_done": self.bootstrap_done,
        }

    async def _async_save_data(self) -> None:
        """Save learned data to storage."""
        try:
            data = self._get_data_for_storage()
            await self._store.async_save(data)
        except Exception as err:
            _LOGGER.error("Failed to save preheat data: %s", err)

    # Diagnostics moved to bottom to be near post_update_tasks




    async def _check_bootstrap(self) -> None:
        """Run retroactive history scan if needed (bootstrap)."""
        # v2.9.0 Fix: Force check for missing departures even if bootstrap was done before
        # This ensures users upgrading from v2.8 (or broken v2.9) get the retroactive scan.
        has_departures = any(len(entries) >= MIN_CLUSTER_POINTS for entries in self.planner.history_departure.values())
        if self.bootstrap_done and has_departures:
            return
            
        _LOGGER.debug("Checking Retroactive Bootstrap status...")
        
        # 1. Migration Safety Check (Legacy V1/V2 Logic Removed)
        # If we have ANY existing data, we assume the user has been running the system
        # and doesn't need a full history rescan (which takes time).
        has_v3 = len(self.planner.history) > 0
        
        if has_v3:
             # v2.9.0 Fix: If we have Arrivals but NO Departures, force a scan anyway.
             has_departures = any(len(entries) >= MIN_CLUSTER_POINTS for entries in self.planner.history_departure.values())
             if not has_departures:
                 _LOGGER.info("Existing Arrivals found, but sparse/missing Departures. Forcing Retroactive Scan...")
             else:
                 _LOGGER.info("Existing learning data detected. Marking Bootstrap as DONE (Skipping scan).")
                 self.bootstrap_done = True
                 await self._async_save_data()
                 return

        # 2. Fresh Install - Run Scan
        _LOGGER.info("First Run Detected (No History). Starting automatic history scan...")
        try:
             await self.scan_history_from_recorder()
             self.bootstrap_done = True
             await self._async_save_data()
             _LOGGER.info("Bootstrap Complete.")
        except Exception as e:
             _LOGGER.error("Bootstrap Scan failed (will retry next reboot): %s", e)
             return


    def _parse_time_to_minutes(self, time_str: str, default_str: str) -> int:
        try:
            t = datetime.strptime(str(time_str), "%H:%M:%S").time()
            return t.hour * 60 + t.minute
        except ValueError:
            t = datetime.strptime(default_str, "%H:%M:%S").time()
            return t.hour * 60 + t.minute

    async def scan_history_from_recorder(self) -> None:
        """Analyze past 28 days of occupancy (Silent)."""
        occupancy_entity = self._get_conf(CONF_OCCUPANCY)
        if not occupancy_entity: return

        _LOGGER.info("Starting historical analysis for %s...", occupancy_entity)
        _LOGGER.debug("DEBUG: Analyzing past 90 days for %s", occupancy_entity)
        try:
            from homeassistant.components.recorder import history, get_instance
            # Analyze up to 90 days (approx 3 months) to capture long-term parity patterns
            # Note: HA default is 10 days, but advanced users often have more.
            start_date = dt_util.utcnow() - timedelta(days=90)
            
            history_data = await get_instance(self.hass).async_add_executor_job(
                history.get_significant_states,
                self.hass,
                start_date,
                None,
                [occupancy_entity]
            )
            
            if not history_data or occupancy_entity not in history_data:
                return

            states = history_data[occupancy_entity]
            win_start_str = self._get_conf(CONF_ARRIVAL_WINDOW_START, DEFAULT_ARRIVAL_WINDOW_START)
            win_end_str = self._get_conf(CONF_ARRIVAL_WINDOW_END, DEFAULT_ARRIVAL_WINDOW_END)
            win_start_min = self._parse_time_to_minutes(win_start_str, DEFAULT_ARRIVAL_WINDOW_START)
            win_end_min = self._parse_time_to_minutes(win_end_str, DEFAULT_ARRIVAL_WINDOW_END)

            count_arrival = 0
            count_departure = 0
            _LOGGER.debug("DEBUG: Found %d raw states. Processing...", len(states))
            for state in states:
                local_dt = dt_util.as_local(state.last_changed)
                current_minutes = local_dt.hour * 60 + local_dt.minute
                
                if state.state == STATE_ON:
                    # Basic window filter for arrivals
                    if win_start_min <= current_minutes <= win_end_min:
                        self.planner.record_arrival(local_dt)
                        count_arrival += 1
                elif state.state != STATE_ON: # OFF, UNAVAILABLE (End of session)
                    # Departures don't need window filtering (or maybe minimal?)
                    # record_departure handles deduplication logic internally
                    self.planner.record_departure(local_dt)
                    count_departure += 1
            
            if count_arrival > 0 or count_departure > 0:
                _LOGGER.info("Identified %d arrival and %d departure events from history.", count_arrival, count_departure)
                await self._async_save_data()
            else:
                 _LOGGER.warning("DEBUG: Scan complete but found 0 events (Arrivals: %d, Departures: %d)", count_arrival, count_departure)
                
        except Exception as e:
            _LOGGER.error("Error analyzing history: %s", e)

    def _setup_listeners(self) -> None:
        """Setup event listeners for state changes."""
        # 1. Occupancy (Instant reaction to Arrival)
        occupancy_sensor = self._get_conf(CONF_OCCUPANCY)
        if occupancy_sensor:
            self.entry.async_on_unload(
                async_track_state_change_event(
                    self.hass, [occupancy_sensor], self._handle_occupancy_change
                )
            )

        # 2. Climate & Temperature (Reactive Setpoints / Frost Protection - Action 3.3)
        # We want to react immediately if the user changes the setpoint manually on the TRV
        # or if the room temperature drops (Frost Protection).
        # Otherwise, with Adaptive Polling (5 min), we might be too slow.
        reactive_entities = []
        
        climate_entity = self._get_conf(CONF_CLIMATE)
        if climate_entity: reactive_entities.append(climate_entity)
        
        temp_entity = self._get_conf(CONF_TEMPERATURE)
        if temp_entity: reactive_entities.append(temp_entity)
        
        if reactive_entities:
            self.entry.async_on_unload(
                async_track_state_change_event(
                    self.hass, reactive_entities, self._handle_reactive_change
                )
            )

    @callback
    def _handle_reactive_change(self, event) -> None:
        """Handle change in climate or temp sensor (Reactive Mode)."""
        # We don't need complex logic, just trigger an update check.
        # The Debouncer in _async_update_data handles rate limiting if needed,
        # but here we want to ensure we catch the edge.
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _handle_occupancy_change(self, event) -> None:
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if not new_state or not old_state: return
        
        now = dt_util.utcnow()
        
        if old_state.state != STATE_ON and new_state.state == STATE_ON:
            # ARRIVAL (ON)
            is_new_session = self.session_manager.update(True, now)
            if is_new_session:
                 # Feed planner (Learns this as a Start Time)
                 self.hass.async_create_task(self._learn_arrival_event())
        
        if old_state.state == STATE_ON and new_state.state != STATE_ON:
            # DEPARTURE (OFF)
            self.session_manager.update(False, now)

    async def _learn_arrival_event(self) -> None:
        now = dt_util.now()
        
        # Filter availability to the configured arrival window.
        # Storage constraints and clustering are handled by the Planner.
        win_start_str = self._get_conf(CONF_ARRIVAL_WINDOW_START, DEFAULT_ARRIVAL_WINDOW_START)
        win_end_str = self._get_conf(CONF_ARRIVAL_WINDOW_END, DEFAULT_ARRIVAL_WINDOW_END)
        win_start = self._parse_time_to_minutes(win_start_str, DEFAULT_ARRIVAL_WINDOW_START)
        win_end = self._parse_time_to_minutes(win_end_str, DEFAULT_ARRIVAL_WINDOW_END)
        
        current_minutes = now.hour * 60 + now.minute
        if win_start <= current_minutes <= win_end:
            _LOGGER.debug("Recording arrival at %s", now)
            self.planner.record_arrival(now)
            await self._async_save_data()

    async def _check_entity_availability(self, entity_id: str, issue_id: str) -> None:
        if not entity_id: return
        state = self.hass.states.get(entity_id)
        if state is None or state.state == "unavailable":
            async_create_issue(
                self.hass, DOMAIN, f"missing_{issue_id}_{self.entry.entry_id}",
                is_fixable=False, severity=IssueSeverity.WARNING,
                translation_key="missing_entity",
                translation_placeholders={"entity": entity_id, "name": self.device_name},
            )
        else:
            async_delete_issue(self.hass, DOMAIN, f"missing_{issue_id}_{self.entry.entry_id}")

    async def _get_operative_temperature(self) -> float:
        # 1. Primary: Dedicated Sensor (if configured)
        temp_sensor = self._get_conf(CONF_TEMPERATURE)
        if temp_sensor:
            state = self.hass.states.get(temp_sensor)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    raw = float(state.state)
                    if -40 < raw < 80:
                        bias = self._get_conf(CONF_AIR_TO_OPER_BIAS, 0.0)
                        return raw - float(bias)
                except (ValueError, TypeError):
                    pass

        # 2. Secondary: Climate Entity current_temperature
        climate = self._get_conf(CONF_CLIMATE)
        if climate:
             state = self.hass.states.get(climate)
             if state and state.attributes.get("current_temperature") is not None:
                 try:
                     raw = float(state.attributes["current_temperature"])
                     if -40 < raw < 80:
                         # Climate entities typically report Air Temperature. 
                         # No additional bias is applied for now, assuming sensor calibration.
                         return raw
                 except (ValueError, TypeError):
                     pass
                     
        return INVALID_TEMP

    async def _get_target_setpoint(self) -> float:
        # Determine Target Temperature Hierarchy:
        # 1. Climate Entity Current Setpoint (if valid and >= comfort min)
        # 2. Last Learned Comfort Setpoint (from previous sessions)
        # 3. Configured Fallback Temperature
        
        # Check Climate
        climate = self._get_conf(CONF_CLIMATE)
        climate_temp = None
        if climate:
             state = self.hass.states.get(climate)
             if state and state.attributes.get("temperature"):
                 try: 
                     climate_temp = float(state.attributes["temperature"])
                 except ValueError: pass

        comfort_min = self._get_conf(CONF_COMFORT_MIN, DEFAULT_COMFORT_MIN)
        
        if climate_temp and climate_temp > comfort_min:
             # v2.9.2: Learned Comfort Persistence
             # If room is Occupied (and temp is valid comfort), save it.
             if self.session_manager.is_occupied:
                 if self._last_comfort_setpoint != climate_temp:
                      self._last_comfort_setpoint = climate_temp
                      # Ideally trigger save on change, but lazy save is fine or triggered elsewhere.
                      # We won't force save here to avoid I/O spam on every adjustment, 
                      # rely on next major event or periodic save. 
                      # Actually, to be safe across restarts, let's allow the next save cycle to pick it up.
                 return climate_temp
            
             # If Unoccupied (Eco Mode?), allow using the stored Comfort Setpoint if it's higher.
             # This prevents the "Predicted Duration" from dropping to 0 when the thermostat setback kicks in.
             if self._last_comfort_setpoint is not None:
                 return max(climate_temp, self._last_comfort_setpoint)
                 
             return climate_temp

        if self._last_comfort_setpoint is not None:
             return self._last_comfort_setpoint
             
        fallback = self._get_conf(CONF_COMFORT_FALLBACK, DEFAULT_COMFORT_FALLBACK)
        return fallback

    def _track_temperature_gradient(self, current_temp: float, now: datetime) -> None:
        """Track gradient and detect open windows."""
        if self._prev_temp is None or self._prev_temp_time is None:
            self._prev_temp = current_temp
            self._prev_temp_time = now
            return

        dt = (now - self._prev_temp_time).total_seconds() / 60.0
        if dt < WINDOW_OPEN_TIME: return # Need at least X mins roughly, or keep accumulating? 
        # Update every 5 mins approx if loop is 1 min?
        
        delta = current_temp - self._prev_temp
        
        # Check Gradient
        # Heuristic: Drop > 0.5K in 5 mins
        newly_detected = False
        if delta < WINDOW_OPEN_GRADIENT: # Slightly sensitive
             _LOGGER.info("[%s] Window Open Detected! Gradient: %.2fK in %.1f min", self.device_name, delta, dt)
             self._window_open_detected = True
             self._window_cooldown_counter = WINDOW_COOLDOWN_MIN # Paused for 30 mins
             newly_detected = True
        
        # Reset if counter active
        if self._window_open_detected and not newly_detected:
            self._window_cooldown_counter -= int(dt)
            if self._window_cooldown_counter <= 0:
                _LOGGER.info("Window Open Cooldown finished. Resuming.")
                self._window_open_detected = False
        
        # Reset tracker
        self._prev_temp = current_temp
        self._prev_temp_time = now

    async def _get_blocked_dates_from_calendar(self, start_date: datetime) -> set[date]:
        """Fetch future holidays from calendar."""
        cal_entity = self._get_conf(CONF_CALENDAR_ENTITY)
        if not cal_entity: return set()
        
        try:
            # Cache Check
            now = dt_util.utcnow()
            last_upd = self._calendar_cache["last_update"]
            
            # If cache valid (< 15 min), return it
            if (now - last_upd) < timedelta(minutes=15):
                return self._calendar_cache["blocked_dates"]

            # Lookahead 8 days (cover +7 days fully)
            start_local = start_date # Assuming start_date matches entity timezone logic
            end_local = start_local + timedelta(days=8)
            
            # Service Call with Response
            response = await self.hass.services.async_call(
                "calendar", "get_events",
                {
                    "entity_id": cal_entity, 
                    "start_date_time": start_local.isoformat(), 
                    "end_date_time": end_local.isoformat()
                },
                blocking=True,
                return_response=True
            )
            
            blocked = set()
            if response and cal_entity in response:
                events = response[cal_entity].get("events", [])
                for event in events:
                    # Assume ANY event in this specific calendar denotes a blocking condition (Holiday/Off)
                    start = event.get("start", {})
                    
                    # 1. All Day Event (Simple Date)
                    if "date" in start:
                        try:
                            d = datetime.strptime(start["date"], "%Y-%m-%d").date()
                            blocked.add(d)
                        except ValueError: pass
                    # 2. DateTime Event (Check overlap? For now simpler is better)
                    elif "dateTime" in start:
                        try:
                             dt_start = datetime.fromisoformat(start["dateTime"])
                             blocked.add(dt_start.date())
                        except ValueError: pass
                        
            # Update Cache
            self._calendar_cache["last_update"] = now
            self._calendar_cache["blocked_dates"] = blocked
            
            return blocked
            
        except Exception as e:
            _LOGGER.debug("Calendar query failed: %s", e)
            return set()

    def _get_effective_workday_sensor(self) -> str | None:
        """Get configured sensor or auto-discover default."""
        configured = self._get_conf(CONF_WORKDAY)
        if configured:
            return configured
        
        # Auto-Discovery
        default_entity = "binary_sensor.workday_sensor"
        if self.hass.states.get(default_entity):
            return default_entity
        return None

    # --------------------------------------------------------------------------
    # Resilience & Error Handling
    # --------------------------------------------------------------------------
    def _build_error_state(self, reason: str) -> PreheatData:
        """Return safe fallback state."""
        _LOGGER.error("Update Cycle Error: %s", reason)
        return PreheatData(False, None, None, 20.0, None, self._last_predicted_duration, 0, 0, False)

    def _handle_update_error(self, err: Exception) -> PreheatData:
        """Handle exceptions."""
        _LOGGER.exception("Unexpected error in update: %s", err)
        return self._build_error_state(str(err))

    def _get_valve_position_with_fallback(self, fallback_mode: str = "active") -> float | None:
        """Get valve position with context-aware fallback."""
        pos = self._get_valve_position()
        if pos is not None: return pos
        if fallback_mode == "active" and self._preheat_active: return 100.0
        elif fallback_mode == "none": return None
        return 0.0

    # --------------------------------------------------------------------------
    # Refactored Main Loop & Helpers
    # --------------------------------------------------------------------------

    async def _async_update_data(self) -> PreheatData:
        """Main Loop (Refactored)."""
        try:

            ctx: Context = await self._collect_context()
            if not ctx["is_sensor_ready"]:
                 return self._build_error_state("Sensor Timeout / Unavailable")

            prediction: Prediction = await self._run_physics_simulation(ctx)
            decision: Decision = self._evaluate_start_decision(ctx, prediction)
            await self._execute_control_actions(ctx, decision)
            await self._post_update_tasks(ctx, decision, prediction)
            return self._build_preheat_data(ctx, prediction, decision)
        except Exception as err:
            return self._handle_update_error(err)

    async def _collect_context(self) -> Context:
        """Collect all necessary state for this cycle."""
        now = dt_util.now()
        op_temp = await self._get_operative_temperature()
        valve_pos = self._get_valve_position_with_fallback("active")
        
        await self.session_manager.check_debounce(dt_util.utcnow())
        
        if op_temp > INVALID_TEMP:
             # Window Detection (Re-enabled)
             self._track_temperature_gradient(op_temp, now)

             v_for_buffer = valve_pos if valve_pos is not None else 0.0
             self.history_buffer.append(HistoryPoint(
                 now.timestamp(), op_temp, v_for_buffer, self._preheat_active
             ))

        # Occupancy
        occ_sensor = self._get_conf(CONF_OCCUPANCY)
        is_occupied = False
        if occ_sensor and self.hass.states.is_state(occ_sensor, STATE_ON):
            is_occupied = True
            
        # Window (Attribute based or internal status)
        is_window = self._window_open_detected

        # Calendar / Workday / Next Event
        blocked_dates = await self._get_blocked_dates_from_calendar(now)
        search_start_date = now
        allowed_weekdays = self._get_allowed_weekdays()
        
        if allowed_weekdays is not None:
             ws_conf = self._get_effective_workday_sensor()
             if ws_conf:
                 ws_state = self.hass.states.get(ws_conf)
                 if ws_state and ws_state.state == "off":
                    # Move to tomorrow, but RESET to 00:00:00 to catch morning events
                    next_day = now + timedelta(days=1)
                    search_start_date = datetime.combine(next_day.date(), datetime.min.time(), tzinfo=now.tzinfo)

        next_event = self.planner.get_next_scheduled_event(search_start_date, allowed_weekdays=allowed_weekdays, blocked_dates=blocked_dates)
        
        outdoor_temp = await self._get_outdoor_temp_current()
        target_setpoint = await self._get_target_setpoint()
        is_ready = (op_temp > INVALID_TEMP)
        

        forecasts = None
        if self.weather_service:
            forecasts = await self.weather_service.get_forecasts()

        return {
            "now": now, "operative_temp": op_temp, "outdoor_temp": outdoor_temp,
            "valve_position": valve_pos, "is_occupied": is_occupied, "is_window_open": is_window,
            "target_setpoint": target_setpoint, "next_event": next_event, "blocked_dates": blocked_dates,
            "is_sensor_ready": is_ready, "forecasts": forecasts, "preheat_active": self._preheat_active
        }

    async def _run_physics_simulation(self, ctx: Context) -> Prediction:
        """Run thermal physics simulation."""
        if self._last_comfort_setpoint is None: self._last_comfort_setpoint = ctx["target_setpoint"]
        
        # Define early for closure access
        delta_in = ctx["target_setpoint"] - ctx["operative_temp"]
        
        outdoor_effective = ctx["outdoor_temp"] if ctx["outdoor_temp"] is not None else 10.0
        weather_avail = False
        
        # Forecast Integration (Restored Iterative Logic v3)
        if ctx["forecasts"] and self.weather_service:
            weather_avail = True
            
            # Helper for Root Finding: func(d) = calculated_duration(d) - d
            # We want func(d) <= 0.
            def _eval_duration(guess_minutes: float) -> float:
                hours = guess_minutes / 60.0
                t_out = self.physics.calculate_effective_outdoor_temp(ctx["forecasts"], hours)
                
                delta_out_g = ctx["target_setpoint"] - t_out
                calc_dur = self.physics.calculate_duration(delta_in, delta_out_g)
                return calc_dur - guess_minutes

            # Use Root Finding Algorithm
            # Horizon: max_preheat_hours (default 3h = 180m) + buffer
            max_h = self._get_conf(CONF_MAX_PREHEAT_HOURS, DEFAULT_MAX_HOURS)
            uncapped_duration = root_find_duration(_eval_duration, int(max_h * 60) + 60)
            
            # Recalculate finals for trace
            predicted_duration = uncapped_duration # It IS the converged duration
            outdoor_effective = self.physics.calculate_effective_outdoor_temp(ctx["forecasts"], uncapped_duration / 60.0)
            delta_out = ctx["target_setpoint"] - outdoor_effective

        else:
             # Standard Static Calc
             # delta_in calculated above
             delta_out = ctx["target_setpoint"] - outdoor_effective
             predicted_duration = self.physics.calculate_duration(
                 delta_in, delta_out, mode=self._get_conf(CONF_PHYSICS_MODE, PHYSICS_STANDARD)
             )
             uncapped_duration = predicted_duration

        # Limit Check (v3 Fix)
        max_preheat = self._get_conf(CONF_MAX_PREHEAT_HOURS, DEFAULT_MAX_HOURS) * 60.0
        capped_duration = min(predicted_duration, max_preheat)
        
        self._last_predicted_duration = capped_duration
        
        return {
            "predicted_duration": capped_duration, 
            "uncapped_duration": uncapped_duration,
            "delta_in": delta_in, "delta_out": delta_out, 
            "prognosis": "ok", "weather_available": weather_avail,
            "limit_exceeded": (uncapped_duration > max_preheat)
        }

    def _evaluate_start_decision(self, ctx: Context, pred: Prediction) -> Decision:
        """Arbitrate between providers and make a decision."""
        now = ctx["now"]
        
        # Prepare Provider Context
        provider_ctx = dict(ctx)
        provider_ctx.update({
            "tau_hours": self.cooling_analyzer.learned_tau,
            "physics_deadtime": self.physics.deadtime,
            # Placeholders for metrics (Calculated later or in dedicated step)
            "potential_savings": 0.0, 
            "tau_confidence": 100.0, 
            "pattern_confidence": 0.0, 
        })
        

        
        # 1. Schedule Provider
        sched_decision = self.schedule_provider.get_decision(provider_ctx)
        
        # 2. Learned Provider (Anchor Mode if Schedule valid)
        if sched_decision.session_end:
             provider_ctx["scheduled_end"] = sched_decision.session_end
             
        learned_decision = self.learned_provider.get_decision(provider_ctx)
        
        selected_provider = PROVIDER_NONE
        final_decision = None
        gates_failed = []
        is_shadow = False
        
        if self.hold_active:
             selected_provider = PROVIDER_MANUAL
             gates_failed.append(GATE_FAIL_MANUAL)
        elif sched_decision.is_valid:
             selected_provider = PROVIDER_SCHEDULE
             final_decision = sched_decision
        elif learned_decision.is_valid and not learned_decision.is_shadow:
             selected_provider = PROVIDER_LEARNED
             final_decision = learned_decision
        elif learned_decision.is_valid and learned_decision.is_shadow:
             # Shadow Mode
             selected_provider = PROVIDER_NONE 
             final_decision = learned_decision
             is_shadow = True
             gates_failed.append("shadow_mode")
        else:
             if not sched_decision.is_valid: gates_failed.append("schedule_invalid")
             if not learned_decision.is_valid: gates_failed.append("learned_invalid")
        
        should_start = False
        start_time = None
        effective_departure = None
        frost_override = False
        
        # Frost Protection
        # Standard: Frost > Hold > Schedule
        frost_temp = FROST_PROTECTION_TEMP 
        hysteresis = FROST_HYSTERESIS
        
        if ctx["operative_temp"] < frost_temp:
             self._frost_active = True
        elif self._frost_active and ctx["operative_temp"] > (frost_temp + hysteresis):
             self._frost_active = False
             
        if self._frost_active:
             frost_override = True
             should_start = True
             # Do not set start_time to preserve original schedule intention for analytics?
             # Or set it to now?
             start_time = now
        
        # Start Logic (Normal)
        if not frost_override and final_decision:
             evt = ctx["next_event"]
             dur = pred["predicted_duration"]
             
             if evt:
                 # Check Lead Time
                 minutes_to_start = (evt - now).total_seconds() / 60.0
                 if minutes_to_start <= dur:
                     should_start = True
                     start_time = now # Start immediately
                     
             if final_decision.session_end:
                 effective_departure = final_decision.session_end

        # Manual Override (Hold can inhibit standard start, but does it inhibit Frost?)
        # Standard: Frost > Hold > Schedule.
        if selected_provider == PROVIDER_MANUAL and not frost_override:
             should_start = False

        # Shadow Metrics Logic
        shadow_metrics = {"safety_violations": 0}
        if learned_decision.is_valid and learned_decision.is_shadow and learned_decision.should_stop:
             # Check Safety: If we STOPPED now, would it be uncomfortable?
             stop_tolerance = self._get_conf(CONF_STOP_TOLERANCE, 0.5)
             threshold = ctx["target_setpoint"] - stop_tolerance
             if ctx["operative_temp"] < threshold:
                 shadow_metrics["safety_violations"] = 1

        self.decision_trace = {
             "evaluated_at": now.isoformat(),
             "schema_version": 1,
             KEY_PROVIDER_SELECTED: selected_provider,
             KEY_PROVIDER_CANDIDATES: {
                 PROVIDER_SCHEDULE: asdict(sched_decision),
                 PROVIDER_LEARNED: asdict(learned_decision)
             },
             KEY_GATES_FAILED: gates_failed,
             "metrics": shadow_metrics
        }
        
        return {
             "should_start": should_start,
             "start_time": start_time,
             "reason": "arbitrated",
             "blocked_by": gates_failed,
             "frost_override": frost_override,
             "effective_departure": effective_departure
        }

    async def _execute_control_actions(self, ctx: Context, dec: Decision) -> None:
        """Execute the decision."""
        if dec["should_start"]:
             if dec["frost_override"]: _LOGGER.info("Frost Protection Active")
             await self._start_preheat(ctx["operative_temp"])
        else:
             # If currently active, we might need to stop
             if self._preheat_active and not self.hold_active:
                  t = ctx["target_setpoint"]
                  o = ctx["outdoor_temp"] if ctx["outdoor_temp"] else 10.0
                  await self._stop_preheat(ctx["operative_temp"], t, o)

    async def _post_update_tasks(self, ctx: Context, decision: Decision, pred: Prediction) -> None:
        """Run tasks after update."""
        # 1. Update Polling Interval
        self._update_polling_interval(decision["start_time"], ctx["is_occupied"])
        
        # 2. Diagnostics
        # 2. Diagnostics
        await self.diagnostics.check_all(ctx, self.physics, self.weather_service, pred)
        


    def _build_preheat_data(self, ctx: Context, pred: Prediction, dec: Decision) -> PreheatData:
        # Extra Metadata
        hvac_action = None
        hvac_mode = None
        climate_ent = self._get_conf(CONF_CLIMATE)
        if climate_ent:
            st = self.hass.states.get(climate_ent)
            if st:
                hvac_mode = st.state
                hvac_action = st.attributes.get("hvac_action")

        p_res = getattr(self.planner, 'last_pattern_result', None)

        return PreheatData(
            preheat_active=self._preheat_active,
            next_start_time=dec["start_time"],
            operative_temp=ctx["operative_temp"],
            target_setpoint=ctx["target_setpoint"],
            next_arrival=ctx["next_event"],
            predicted_duration=pred["predicted_duration"],
            mass_factor=self.physics.mass_factor,
            loss_factor=self.physics.loss_factor,
            learning_active=True,
            decision_trace=self.decision_trace,
            window_open=ctx["is_window_open"],
            outdoor_temp=ctx["outdoor_temp"],
            valve_signal=ctx["valve_position"],
            last_comfort_setpoint=self._last_comfort_setpoint,
            deadtime=self.physics.deadtime,
            
            # Review Fixes v2
            schedule_summary=self.planner.get_schedule_summary(),
            departure_summary=self.planner.get_departure_schedule_summary(),
            next_departure=dec["effective_departure"],
            hvac_action=hvac_action,
            hvac_mode=hvac_mode,
            optimal_stop_active=self.optimal_stop_manager.is_active,
            optimal_stop_time=self.optimal_stop_manager.stop_time,
            pattern_type=p_res.pattern_type if p_res else None,
            pattern_confidence=p_res.confidence if p_res else 0.0,
            pattern_stability=p_res.stability if p_res else 0.0,
            detected_modes=p_res.modes_found if p_res else None,
            fallback_used=p_res.fallback_used if p_res else False,
        )
    


    def _get_allowed_weekdays(self) -> list[int] | None:
         if self._get_conf(CONF_ONLY_ON_WORKDAYS, False):
             workday_sensor = self._get_effective_workday_sensor()
             if workday_sensor:
                 state = self.hass.states.get(workday_sensor)
                 if state and state.state != "unavailable":
                     w_attr = state.attributes.get("workdays")
                     if isinstance(w_attr, list):
                         week_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
                         return [week_map[str(d).lower()] for d in w_attr if str(d).lower() in week_map]
         return None


    async def _start_preheat(self, operative_temp: float) -> None:
        self._preheat_active = True
        self._preheat_started_at = dt_util.utcnow()
        self._start_temp = operative_temp
        self.hass.bus.async_fire(f"{DOMAIN}_started", {"name": self.device_name})
        _LOGGER.info("Preheat STARTED. Temp: %.1f", operative_temp)

    async def _stop_preheat(self, end_temp: float, target: float, outdoor: float, aborted: bool = False) -> None:
        if not self._preheat_active: return
        
        duration = 0
        if self._preheat_started_at:
            duration = (dt_util.utcnow() - self._preheat_started_at).total_seconds() / 60
        
        if not aborted and self._start_temp is not None:
            # LEARN
            
            # Don't learn if Window Open detected recently
            if self._window_open_detected:
                _LOGGER.info("Skipping learning due to Open Window detected.")
            else:
                delta_in = end_temp - self._start_temp
                delta_out = target - outdoor # Approx average delta
                
                # Valve Sensor Check (Average over the heating period)
                start_ts = self._preheat_started_at.timestamp()
                end_ts = dt_util.utcnow().timestamp()
                
                # Try average first
                valve_pos_avg = self.history_buffer.get_average_valve(start_ts, end_ts)
                
                # Fallback to current if buffer empty (unlikely)
                if valve_pos_avg is None:
                     valve_pos_avg = self._get_valve_position_with_fallback("passive")
                
                _LOGGER.debug("Learning Check: Valve Avg=%.1f (over %.1f min)", 
                              valve_pos_avg if valve_pos_avg else 0, duration)
                
                # V3: Analyze Deadtime
                new_deadtime = self.deadtime_analyzer.analyze(self.history_buffer.get_all())
                if new_deadtime:
                     self.physics.update_deadtime(new_deadtime)
                     _LOGGER.info("Deadtime Updated: %.1f min", self.physics.deadtime)
                
                success = self.physics.update_model(duration, delta_in, delta_out, valve_pos_avg)
                if success:
                    await self._async_save_data()
                    _LOGGER.info("Learning Success: Mass=%.1f, Loss=%.1f", self.physics.mass_factor, self.physics.loss_factor)
        
        self._preheat_active = False
        self._preheat_started_at = None
        self._start_temp = None
        self.hass.bus.async_fire(f"{DOMAIN}_stopped", {"name": self.device_name})

    async def _get_outdoor_temp_current(self) -> float:
        # Caching logic
        now = dt_util.utcnow()
        if self._last_weather_check and (now - self._last_weather_check).total_seconds() < 900:
            return self._cached_outdoor_temp
            
        # Try Weather Entity
        weather = self._get_conf(CONF_WEATHER_ENTITY)
        if weather:
             state = self.hass.states.get(weather)
             if state:
                 try:
                     self._cached_outdoor_temp = float(state.attributes.get("temperature", 10.0))
                     self._last_weather_check = now
                     return self._cached_outdoor_temp
                 except: pass
        
        # Try Sensor
        sensor = self._get_conf(CONF_OUTDOOR_TEMP)
        if sensor:
             if state and state.state not in ("unavailable", "unknown"):
                 try:
                     self._cached_outdoor_temp = float(state.state)
                     self._last_weather_check = now
                     return self._cached_outdoor_temp
                 except (ValueError, TypeError): pass
                     
        return 10.0

    async def _update_comfort_learning(self, current_setpoint: float, is_occupied: bool) -> None:
        if not is_occupied or not self.session_manager.is_occupied:
            return
        
        if not self.session_manager.session_start_time:
            return
            
        duration = (dt_util.utcnow() - self.session_manager.session_start_time).total_seconds() / 60
        if duration < 15: return
        
        if self._last_comfort_setpoint != current_setpoint:
            self._last_comfort_setpoint = current_setpoint
            await self._async_save_data()

    async def force_preheat_on(self) -> None:
        """Manually start preheat."""
        op_temp = await self._get_operative_temperature()
        await self._start_preheat(op_temp)
        self.async_update_listeners()

    async def stop_preheat_manual(self) -> None:
        """Manually stop preheat."""
        op_temp = await self._get_operative_temperature()
        target = await self._get_target_setpoint()
        outdoor = await self._get_outdoor_temp_current()
        # User request: Try to learn even if stopped manually, if data is valid.
        # Physics module filters out noise (small deltas).
        await self._stop_preheat(op_temp, target, outdoor, aborted=False)
        self.async_update_listeners()

    async def reset_gain(self) -> None:
        """Reset thermal model (Legacy Name)."""
        await self.reset_model()

    async def reset_model(self) -> None:
        """Reset thermal model parameters to profile defaults."""
        self.physics.reset()
        await self._async_save_data()
        _LOGGER.info("Physics Model RESET to defaults.")
        # Trigger update to reflect changes
        self.async_set_updated_data(self.data) 

    async def recompute(self) -> None:
        """Force immediate recomputation."""
        _LOGGER.debug("Forced Recompute requested.")
        await self.async_refresh()

    async def reset_arrivals(self) -> None:
        """Reset learned schedule history."""
        self.planner = PreheatPlanner() # Empty history
        await self._async_save_data()
        _LOGGER.info("Arrival History RESET.")
        self.async_update_listeners()

    def _get_valve_position(self) -> float | None:
        """Get current valve position from sensor or climate attribute."""
        # 1. Dedicated Sensor
        valve_entity = self._get_conf(CONF_VALVE_POSITION)
        if valve_entity:
            st = self.hass.states.get(valve_entity)
            if st and st.state not in ("unknown", "unavailable"):
                try: return float(st.state)
                except ValueError: pass
        
        # 2. Climate Attribute (KNX 'command_value', or generic 'valve_position')
        climate_entity = self._get_conf(CONF_CLIMATE)
        if climate_entity:
            st = self.hass.states.get(climate_entity)
            if st:
                # Common attribute names
                for attr in ["valve_position", "command_value", "pi_heating_demand", "output_val"]:
                    val = st.attributes.get(attr)
                    if val is not None:
                        try: return float(val)
                        except ValueError: pass
        return None

    async def _post_update_tasks(self, ctx: Context, decision: Decision, pred: Prediction) -> None:
        """Run tasks after main update loop (non-critical)."""
        # 1. Update Polling
        self._update_polling_interval(decision["start_time"], ctx["is_occupied"])
        
        # 2. Comfort Learning
        await self._update_comfort_learning(ctx["target_setpoint"], ctx["is_occupied"])
        
        # 3. Diagnostics
        # Grace period check to avoid falses during boot
        current_uptime = (dt_util.utcnow() - self._startup_time).total_seconds()
        if current_uptime >= STARTUP_GRACE_SEC:
             await self.diagnostics.check_all(ctx, self.physics, self.weather_service, pred)

    def _update_polling_interval(self, next_start: datetime | None, is_occupied: bool) -> None:
        """
        Adjust polling interval based on activity (Adaptive Polling).
        - Active (1 min): Preheat Active, Occupied, Window Open, or approaching Next Start.
        - Idle (5 min): Otherwise.
        """
        # Default: Idle
        new_interval = timedelta(minutes=5)
        
        # 1. Preheat Active (Highest Priority)
        # 2. Occupied (User might change setpoint manually -> fast reaction)
        # 3. Window Open (Fast recovery detection)
        if self._preheat_active or is_occupied or self._window_open_detected:
            new_interval = timedelta(minutes=1)
        
        # 4. Approaching Start (< 2 hours)
        elif next_start:
            # Check time delta
            now = dt_util.utcnow()
            diff = (next_start - now).total_seconds()
            if 0 < diff < 7200: # 2 hours
                 new_interval = timedelta(minutes=1)
                 
        # Update if changed
        if self.update_interval != new_interval:
            _LOGGER.debug("Adaptive Polling: Updating interval to %s (was %s)", new_interval, self.update_interval)
            self.update_interval = new_interval


    @property
    def preheat_active(self) -> bool:
        """Return True if preheat is active."""
        return self._preheat_active

    async def analyze_history(self) -> None:
        """Analyze history and report Data Maturity (Button Action)."""
        _LOGGER.debug("Manual History Analysis Requested")
        await self.scan_history_from_recorder()
        await self._generate_history_report()

    async def _generate_history_report(self) -> None:
        """Generate persistent notification with data stats."""
        
        # 1. Gather Stats from Departure History (Recorder)
        # {weekday: [sessions]}
        weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        report_lines = []
        
        total_sessions = 0
        
        for i, name in enumerate(weekdays):
            sessions = self.planner.history_departure.get(i, [])
            count = len(sessions)
            total_sessions += count
            
            # Detailed breakdown if data exists
            if count > 0:
                # Show last time
                last = sessions[-1]
                mins = last.get("minutes", 0)
                h = mins // 60
                m = mins % 60
                report_lines.append(f"{name}: {count} sessions (Last: {h:02d}:{m:02d})")
            else:
                report_lines.append(f"{name}: 0 sessions")
                
        # 2. Add v2/Legacy Stats if relevant
        v2_count = sum(len(v) for v in self.planner.history_v2.values())
        
        msg = (
            f"Total Recorder Sessions: {total_sessions}\n"
            f"Legacy (v2) Data Points: {v2_count}\n\n"
            "Breakdown by Weekday:\n" + 
            "\n".join(report_lines)
        )
        
        # 3. Create Persistent Notification
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Preheat Data Report",
                "message": msg,
                "notification_id": f"preheat_report_{self.entry.entry_id}"
            }
        )

    async def set_enabled(self, enabled: bool) -> None:
        """Enable/Disable the integration logic."""
        self.enable_active = enabled
        _LOGGER.debug("Master Enabled Changed to: %s", enabled)
        await self._async_save_data() # Persist immediately
        
        # Stop preheating immediately if disabled
        if not enabled and self._preheat_active:
            _LOGGER.info("Integration disabled while active. Stopping preheat immediately.")
            await self.stop_preheat_manual()

        await self.async_refresh()

    async def set_hold(self, hold: bool) -> None:
        """Enable/Disable Hold mode."""
        self.hold_active = hold
        _LOGGER.debug("Hold Active Changed to: %s", hold)
        
        # Stop preheating immediately if Hold enabled
        if hold and self._preheat_active:
            _LOGGER.info("Hold activated while active. Stopping preheat immediately.")
            await self.stop_preheat_manual()

        # Hold state is NOT persisted by design (Vacation mode prevents accidental lock-out on restart)
        # But we trigger an update.
        await self.async_refresh()