"""Coordinator for Preheat integration."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, date, time, timezone
import logging
from typing import Any, TYPE_CHECKING
import math
import random

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
    REASON_EXTERNAL_INHIBIT
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

class OccupancyDebouncer:
    """
    Session State Machine (v2.8).
    Filters short 'flapping' (OFF->ON) to determine true session end.
    """
    def __init__(self, debounce_min: float, parent_coordinator: "PreheatingCoordinator"):
        self._debounce_limit_sec = debounce_min * 60.0
        self._coordinator = parent_coordinator
        
        # State
        self._off_start_time: datetime | None = None
        self._is_debouncing = False
        self._last_committed_time: datetime | None = None
        
    def handle_change(self, new_state_on: bool, now: datetime) -> None:
        """Called when occupancy sensor changes state."""
        if not new_state_on:
            # ON -> OFF (Potential Session End)
            if not self._is_debouncing:
                _LOGGER.debug("[Debounce] Session End Candidate? Starting timer (%.1f min). Off at: %s", 
                              self._debounce_limit_sec/60, now)
                self._off_start_time = now
                self._is_debouncing = True
        else:
            # OFF -> ON (Flapping / Return)
            if self._is_debouncing and self._off_start_time:
                # RACE CONDITION CHECK:
                # If OFF duration > Limit, but check() missed it (jitter), we MUST commit now before resetting!
                elapsed = (now - self._off_start_time).total_seconds()
                if elapsed >= self._debounce_limit_sec:
                    _LOGGER.info("[Debounce] Race Condition Caught! Session actually ended before return. Committing.")
                    self._commit_departure(self._off_start_time)
                else:
                    _LOGGER.debug("[Debounce] False Alarm (Flapping). Session continues. (Off duration: %.1fs)", elapsed)
                
                # Reset
                self._is_debouncing = False
                self._off_start_time = None

    def _commit_departure(self, departure_time: datetime) -> None:
        """Helper to commit and save."""
        # Double-Commit Guard
        if self._last_committed_time == departure_time:
            _LOGGER.debug("[Debounce] Skipped duplicate commit for %s", departure_time)
            return

        self._coordinator.planner.record_departure(departure_time)
        self._last_committed_time = departure_time
        
        # Throttled Save (Write Coalescing) - 10s delay to protect SD cards
        if hasattr(self._coordinator._store, "async_delay_save"):
             self._coordinator._store.async_delay_save(self._coordinator._get_data_for_storage, 10.0)
        else:
             # Fallback (should not happen on modern HA)
             self._coordinator.hass.async_create_task(self._coordinator._async_save_data())
                
    async def check(self, now: datetime) -> None:
        """Called periodically to check if debounce timer expired."""
        if not self._is_debouncing or self._off_start_time is None:
            return

        elapsed = (now - self._off_start_time).total_seconds()
        if elapsed >= self._debounce_limit_sec:
            # TIMEOUT! It's a real departure.
            final_departure_time = self._off_start_time
            _LOGGER.info("[Debounce] Session End CONFIRMED. Departed at: %s (Latency: %.1fs)", 
                         final_departure_time, elapsed)
            
            # Commit
            self._commit_departure(final_departure_time)
            
            # Reset
            self._is_debouncing = False
            self._off_start_time = None

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
        self.occupancy_debouncer = OccupancyDebouncer(debounce_min, self)
        
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
        self._occupancy_on_since: datetime | None = None
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
        
        # Caching
        self._cached_outdoor_temp: float = 10.0
        self._last_weather_check: datetime | None = None
        self.weather_service: WeatherService | None = None
        
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
        self.diagnostics_data: dict[str, Any] = {
            "last_sample_count": 0,
            "last_sample_change": 0.0,
            "hold_started_ts": None,
            "inhibit_started_ts": None,
            "occupancy_last_change_ts": 0.0,
            "capped_events": [], # Rolling list of bools
            "last_check_ts": 0.0,
        }
        
        self.bootstrap_done = False

        
        # v2.9.0-beta19: Anti-Flapping State
        self._last_occupancy_off_time: datetime | None = None

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
                if not history and "learned_arrivals" in data:
                    _LOGGER.info("Migrating legacy arrival data with variance injection...")
                    
                    # Create Repair Issue
                    async_create_issue(
                        self.hass,
                        DOMAIN,
                        f"migration_v2_{self.entry.entry_id}",
                        is_fixable=False,
                        severity=IssueSeverity.WARNING,
                        translation_key="data_migrated",
                        translation_placeholders={"name": self.device_name}
                    )
                    
                    # Legacy data format {weekday: average_min} provides insufficient granularity for clustering.
                    # We inject simulated variance to seed the new history model.
                    legacy = data["learned_arrivals"]
                    history = {}
                    for k, v in legacy.items():
                        # v is the average arrival minute (e.g. 420 for 07:00)
                        # Create 5 fake events with Gaussian-like spread (+- 15 mins)
                        # to allow clustering to pick it up as a valid cluster.
                        fake_events = []
                        base_time = int(v)
                        for _ in range(5):
                            # Random +/- 15 mins
                            offset = random.randint(-15, 15)
                            simulated = max(0, min(1439, base_time + offset))
                            fake_events.append(simulated)
                        history[int(k)] = fake_events
                
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
                loaded_diag = data.get("diagnostics", {})
                if loaded_diag:
                     # Merge to preserve defaults/types
                     self.diagnostics_data.update(loaded_diag)
                
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
                 # We do NOT run this immediately to avoid startup slam.
                 # We schedule it for 5 minutes later.
                 self.hass.loop.call_later(300, lambda: self.hass.async_create_task(self._check_bootstrap()))
                
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
            "diagnostics": self.diagnostics_data,
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

    async def _check_diagnostics(self) -> None:
        """Run periodic health checks and create repair issues."""
        # Rate Limit: Run max once per hour
        now = dt_util.utcnow().timestamp()
        last_check = self.diagnostics_data.get("last_check_ts", 0)
        
        # Debounce: If run recently (< 3600s) and not startup
        boot_time = self._startup_time.timestamp()
        uptime = now - boot_time
        
        # Guard: Grace Period on Startup (30 min)
        # Guard: Grace Period
        if uptime < 1800: # 30 min
             return
             

        _LOGGER.debug("Running Diagnostics Check (Uptime: %.1f min)", uptime/60)
        self.diagnostics_data["last_check_ts"] = now
        
        from homeassistant.helpers.issue_registry import async_create_issue, async_delete_issue, IssueSeverity
        
        # --- Helper for managing issues ---
        def raise_issue(issue_slug: str, msg_key: str, severity: IssueSeverity, params: dict | None = None):
             if params is None: params = {}
             # UX Polish: Always inject zone name
             if "name" not in params: params["name"] = self.device_name
             
             async_create_issue(
                self.hass, DOMAIN, f"{issue_slug}_{self.entry.entry_id}",
                is_fixable=False, is_persistent=True, severity=severity,
                translation_key=msg_key, translation_placeholders=params
             )

        def clear_issue(issue_slug: str):
             async_delete_issue(self.hass, DOMAIN, f"{issue_slug}_{self.entry.entry_id}")
        
        # --- 1. Physics Railing (Refined) ---
        # Logic: Early warning (>15 samples) if confidence is decent (>25) OR Error is huge (>10 min)
        # Prevents "Silent Failure" for months.
        p = self.physics
        s_count = p.sample_count
        conf = p.get_confidence()
        avg_err = p.avg_error
        
        is_railing = False
        msg_key = None
        current_val = 0.0
        
        # Threshold: 15 samples (approx 2 weeks)
        # Condition: High Error (>10min) OR (Confidence > 25 AND Limit Hit)
        if s_count > 15 and (avg_err > 10.0 or conf > 25):
             if p.mass_factor <= p.min_mass:
                 is_railing = True
                 msg_key = "physics_limit_mass_min"
                 current_val = p.mass_factor
             elif p.mass_factor >= p.max_mass:
                 is_railing = True
                 msg_key = "physics_limit_mass_max"
                 current_val = p.mass_factor
             elif p.loss_factor >= 50.0:
                 is_railing = True
                 msg_key = "physics_limit_loss_max"
                 current_val = p.loss_factor
        
        if is_railing:
            raise_issue("physics_limit", msg_key, IssueSeverity.WARNING, {"current": f"{current_val:.1f}"})
        else:
            clear_issue("physics_limit")

        # --- 2. Zombie Schedule ---
        # Logic: EnableOptStop=True AND Schedule has no events
        if self._get_conf(CONF_ENABLE_OPTIMAL_STOP, False):
            sched_ent = self._get_conf(CONF_SCHEDULE_ENTITY)
            if sched_ent and sched_ent.startswith("schedule."):
                state = self.hass.states.get(sched_ent)
                # Check for empty attributes
                if state and not state.attributes.get("next_event"):
                     raise_issue("zombie_schedule", "zombie_schedule", IssueSeverity.ERROR)
                else:
                     clear_issue("zombie_schedule")
            else:
                clear_issue("zombie_schedule")
        else:
            clear_issue("zombie_schedule")

        # --- 3. Stale Sensor ---
        # Logic: Unavailable OR > 6h no change. Requires 2 hits (Debounce).
        temp_ent = self._get_conf(CONF_TEMPERATURE)
        check_ent = temp_ent
        
        # Action 3.3b: Fallback to Climate Entity Check
        if not check_ent:
             check_ent = self._get_conf(CONF_CLIMATE)
             
        is_stale = False
        if check_ent:
            state = self.hass.states.get(check_ent)

            if not state or state.state in ("unavailable", "unknown"):
                is_stale = True
            elif state.last_updated:
                 age = (dt_util.utcnow() - state.last_updated).total_seconds()

                 if age > 21600: # 6h
                     is_stale = True
                     
            # Special Case: Climate entities might report state, but 'current_temperature' is None/null
            if not is_stale and not temp_ent and check_ent:
                 # We are relying on climate attributes
                 curr_temp = state.attributes.get("current_temperature") if state else None

                 if state and curr_temp is None:
                      is_stale = True
        
        print(f"DEBUG: is_stale={is_stale}, counter={self.diagnostics_data.get('stale_sensor_counter', 0)}") # DEBUG
        
        # Debounce Logic
        stale_counter = self.diagnostics_data.get("stale_sensor_counter", 0)
        if is_stale:
            stale_counter += 1
        else:
            stale_counter = 0
        self.diagnostics_data["stale_sensor_counter"] = stale_counter
        
        if stale_counter >= 2:
             raise_issue("stale_sensor", "stale_sensor", IssueSeverity.ERROR)
        else:
             clear_issue("stale_sensor")

        # --- 4. Weather No Forecast (Advanced) ---
        # Logic: Advanced Mode AND Cache Invalid
        if self._get_conf(CONF_PHYSICS_MODE) == PHYSICS_ADVANCED:
             # Check Service Cache
             has_data = False
             cache = self.weather_service.get_cached_forecast() if self.weather_service else None
             if cache:
                  has_data = True
                  
             _LOGGER.debug("Diagnostics [Weather]: Advanced Mode=True, HasData=%s, CacheSize=%s", has_data, len(cache) if cache else 0)
              
             if not has_data:
                  raise_issue("weather_no_forecast", "weather_no_forecast", IssueSeverity.WARNING)
             else:
                  clear_issue("weather_no_forecast")
             
             # Check 11: No Weather Entity Configured
             if not self._get_conf(CONF_WEATHER_ENTITY):
                  raise_issue("adv_no_weather", "adv_no_weather", IssueSeverity.ERROR)
             else:
                  clear_issue("adv_no_weather")

             # Check 8: Forecast Horizon Short
             # We need to know if forecast covers now + max_coast
             if has_data:
                 cache = self.weather_service.get_cached_forecast()
                 if cache:
                     last_pt = cache[-1]["datetime"]
                     max_coast = self._get_conf(CONF_MAX_COAST_HOURS, 4.0)
                     needed = dt_util.utcnow() + timedelta(hours=max_coast)
                     if last_pt < needed:
                         raise_issue("forecast_short", "forecast_short", IssueSeverity.WARNING)
                     else:
                         clear_issue("forecast_short")
                         
             # Check 8.1: Forecast Quality (Fallback Used)
             # Logic: If using interpolated data (daily/twice_daily), warn user about precision.
             if has_data and self.weather_service.forecast_type_used != "hourly":
                 f_type = self.weather_service.forecast_type_used
                 if f_type != "none":
                     raise_issue(
                         "weather_quality", 
                         "weather_quality", 
                         IssueSeverity.WARNING, 
                         {"type": f_type}
                     )
                 else:
                     clear_issue("weather_quality")
             else:
                 clear_issue("weather_quality")

        else:
             clear_issue("weather_no_forecast")
             clear_issue("adv_no_weather")
             clear_issue("forecast_short")
             clear_issue("weather_quality")

        # --- 5. Occupancy Zombie (Refined) ---
        # Logic: Adaptive Threshold. ON -> 7d (Homeoffice), OFF -> 3d (Suspicious)
        occ_ent = self._get_conf(CONF_OCCUPANCY)
        if occ_ent:
            state = self.hass.states.get(occ_ent)
            current_state_str = state.state if state else "unknown"
            
            # Update Timestamp if state changed
            saved_state = self.diagnostics_data.get("last_occ_state")
            if saved_state != current_state_str:
                self.diagnostics_data["last_occ_state"] = current_state_str
                self.diagnostics_data["occupancy_last_change_ts"] = now
            
            diff = now - self.diagnostics_data.get("occupancy_last_change_ts", now)
            
            # Adaptive Limit
            limit = 604800 # Default 7 days
            if current_state_str == STATE_OFF:
                 limit = 259200 # 3 days if OFF (sensor dead?)
            
            if diff > limit:
                # Differentiate message? Using generic for now.
                raise_issue("occupancy_stale", "occupancy_stale", IssueSeverity.WARNING)
            else:
                clear_issue("occupancy_stale")

        # --- 6. Hold/Inhibit Stuck ---
        # Logic: > 24h
        # Check Hold
        is_hold = self.hold_active
        if is_hold:
            if not self.diagnostics_data.get("hold_started_ts"):
                self.diagnostics_data["hold_started_ts"] = now
            elif (now - self.diagnostics_data["hold_started_ts"]) > 86400:
                raise_issue("hold_stuck", "hold_stuck", IssueSeverity.WARNING)
        else:
            self.diagnostics_data["hold_started_ts"] = None
            clear_issue("hold_stuck")
            
        # Check Inhibit
        is_inhib = self._external_inhibit or self._window_open_detected
        if is_inhib:
            if not self.diagnostics_data.get("inhibit_started_ts"):
                self.diagnostics_data["inhibit_started_ts"] = now
            elif (now - self.diagnostics_data["inhibit_started_ts"]) > 86400:
                 raise_issue("inhibit_stuck", "inhibit_stuck", IssueSeverity.WARNING)
        else:
             self.diagnostics_data["inhibit_started_ts"] = None
             clear_issue("inhibit_stuck")

        # --- 7. Learning Stalled ---
        # Logic: No samples > 7 days AND preheat was active
        # We need to know if preheat WAS active. Best proxy: sample_count increased?
        # If preheat runs, sample count increases. 
        # So "Learning Stalled" = "Sample Count Static"
        # User condition: "AND preheat_active occurred". We can't easily track that in history.
        # Simplified: If sample count static > 7 days AND sample_count > 0 (it worked once).
        curr_samp = p.sample_count
        last_samp = self.diagnostics_data.get("last_sample_count", 0)
        last_samp_ts = self.diagnostics_data.get("last_sample_change", now)
        
        if curr_samp != last_samp:
            self.diagnostics_data["last_sample_count"] = curr_samp
            self.diagnostics_data["last_sample_change"] = now
            clear_issue("learning_stalled")
        else:
            if (now - last_samp_ts) > 604800 and curr_samp > 0:
                raise_issue("learning_stalled", "learning_stalled", IssueSeverity.WARNING)
            else:
                clear_issue("learning_stalled")

        # --- 9. Unit Mismatch ---
        if temp_ent:
            st = self.hass.states.get(temp_ent)
            if st:
                uorn = st.attributes.get("unit_of_measurement")
                dc = st.attributes.get("device_class")
                if uorn not in ("°C", "C", "c", "C°"):
                    raise_issue("sensor_unit", "sensor_unit_mismatch", IssueSeverity.ERROR)
                elif dc and dc != "temperature":
                     raise_issue("sensor_unit", "sensor_unit_mismatch", IssueSeverity.ERROR)
                else:
                    clear_issue("sensor_unit")

        # --- 10. Unrealistic Temps / Swapped (Refined) ---
        # Check 1: Extreme values
        # Check 2: Identical values (Swapped) - ONLY if Heating is OFF (otherwise divergence is expected)
        outdoor_ent = self._get_conf(CONF_OUTDOOR_TEMP)
        sanity_fail = False
        msg_sanity = None
        
        if temp_ent:
             ts = self.hass.states.get(temp_ent)
             if ts and ts.state not in ("unavailable", "unknown"):
                 try:
                     val = float(ts.state)
                     if val < -10 or val > 45:
                         sanity_fail = True
                         msg_sanity = "sanity_temp_extreme"
                 except ValueError:
                     pass # handled by stale check
        
        # Only start correlation check if heating is NOT active (prevent false positive)
        # Note: We check _preheat_active and heat_demand
        if not sanity_fail and outdoor_ent and temp_ent and not self._preheat_active:
             ts_in = self.hass.states.get(temp_ent)
             ts_out = self.hass.states.get(outdoor_ent)
             if ts_in and ts_out:
                  try:
                      v_in = float(ts_in.state)
                      v_out = float(ts_out.state)
                      if abs(v_in - v_out) < 0.5: # Tighter threshold, 0.5K
                          # Potential Swap. Requires persistence to be sure (12h).
                          # We check 'sanity_swap_counter'
                          ctr = self.diagnostics_data.get("sanity_swap_counter", 0)
                          ctr += 1
                          self.diagnostics_data["sanity_swap_counter"] = ctr
                          if ctr > 12: # 12 checks = 12 hours
                              sanity_fail = True
                              msg_sanity = "sanity_temp_swap"
                      else:
                          self.diagnostics_data["sanity_swap_counter"] = 0
                  except ValueError:
                      pass
        else:
             # Reset counter if heating runs or diff is healthy
             self.diagnostics_data["sanity_swap_counter"] = 0

        if sanity_fail:
             raise_issue("sanity_temp", msg_sanity, IssueSeverity.WARNING)
        else:
             clear_issue("sanity_temp")

        # --- 12. No Outdoor Source ---
        # If no weather and no outdoor sensor -> Error
        if not self._get_conf(CONF_WEATHER_ENTITY) and not self._get_conf(CONF_OUTDOOR_TEMP):
             raise_issue("no_outdoor_source", "no_outdoor_source", IssueSeverity.ERROR)
        else:
             clear_issue("no_outdoor_source")

        # --- 13. Max Coast Capping ---
        # Check rolling list
        capped_evts = self.diagnostics_data.get("capped_events", [])
        # Count True in last 10
        if capped_evts and sum(1 for x in capped_evts if x) > 3:
             # TODO: Differentiate reason if possible. For now generic.
             raise_issue("coast_capped", "coast_capped", IssueSeverity.WARNING)
        else:
             clear_issue("coast_capped")

        # --- 14. Forecast Data Stale (NEW) ---
        # Logic: Forecast cache > 2 hours old?
        if self.weather_service and self.weather_service._cache_ts:
             age = now - self.weather_service._cache_ts.timestamp()
             if age > 7200: # 2 hours
                 raise_issue("forecast_stale", "forecast_stale", IssueSeverity.WARNING)
             else:
                 clear_issue("forecast_stale")
        
        # --- 15. Valve Saturation (NEW) ---
        # Logic: Valve > 95% for > 3 hours
        # Detects: Undersized heater or open window
        valve_pos = self._get_valve_position()
        is_saturated = False
        if valve_pos is not None and valve_pos > 95:
             ts_sat = self.diagnostics_data.get("valve_saturation_ts")
             if not ts_sat:
                 self.diagnostics_data["valve_saturation_ts"] = now
             elif (now - ts_sat) > 10800: # 3h
                 is_saturated = True
        else:
             self.diagnostics_data["valve_saturation_ts"] = None
        
        if is_saturated:
             raise_issue("valve_saturation", "valve_saturation", IssueSeverity.WARNING)
        else:
             clear_issue("valve_saturation")

        # --- 16. Max Coast High (TRV) ---
        max_c = self._get_conf(CONF_MAX_COAST_HOURS, 4.0)
        # Heuristic: Fast response system (Mass < 30) with long coast (>3h)
        if max_c >= 3.0 and p.mass_factor < 30.0:
             raise_issue("max_coast_high", "max_coast_high", IssueSeverity.WARNING)
        else:
             clear_issue("max_coast_high")

        # --- 17. Tolerance Sanity ---
        tol = self._get_conf(CONF_STOP_TOLERANCE, 0.5)
        if tol < 0.1 or tol > 1.5:
             raise_issue("tolerance_sanity", "tolerance_sanity", IssueSeverity.WARNING)
        else:
             clear_issue("tolerance_sanity")


    async def _check_bootstrap(self) -> None:
        """Run retroactive history scan if needed (bootstrap)."""
        # v2.9.0 Fix: Force check for missing departures even if bootstrap was done before
        # This ensures users upgrading from v2.8 (or broken v2.9) get the retroactive scan.
        has_departures = any(len(entries) >= MIN_CLUSTER_POINTS for entries in self.planner.history_departure.values())
        if self.bootstrap_done and has_departures:
            return
            
        _LOGGER.debug("Checking Retroactive Bootstrap status...")
        
        # 1. Migration Safety Check
        # If we have ANY existing data, we assume the user has been running the system
        # and doesn't need a full history rescan (which takes time).
        # We just mark it as done.
        has_v2 = len(self.planner.history_v2) > 0
        has_v3 = len(self.planner.history) > 0
        
        if has_v2 or has_v3:
             # v2.9.0 Fix: If we have Arrivals but NO Departures, force a scan anyway.
             # This populates the new "Learned Departures" feature for existing users.
             has_departures = any(len(entries) >= MIN_CLUSTER_POINTS for entries in self.planner.history_departure.values())
             if not has_departures:
                 _LOGGER.info("Existing Arrivals found, but sparse/missing Departures. Forcing Retroactive Scan...")
                 # Detect if we should proceed (Fallthrough to scan)
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
            
            # v2.9 Anti-Flapping: Check if we were gone long enough
            # Logic: If off_duration < debounce_min, it's just a short break (e.g. Toilet).
            debounce_min = self._get_conf(CONF_DEBOUNCE_MIN, DEFAULT_DEBOUNCE_MIN)
            is_valid_new_session = True
            
            if self._last_occupancy_off_time:
                off_duration = (now - self._last_occupancy_off_time).total_seconds() / 60.0
                if off_duration < debounce_min:
                    is_valid_new_session = False
                    _LOGGER.debug("[Anti-Flapping] Ignored Arrival (Gap %.1f min < %.1f min). Maintaining previous session.", 
                                  off_duration, debounce_min)
            
            self._occupancy_on_since = now
            
            if is_valid_new_session:
                 # Feed planner (Learns this as a Start Time)
                 self.hass.async_create_task(self._learn_arrival_event())
            
            # Always notify debouncer (Cancel departure timer)
            self.occupancy_debouncer.handle_change(True, now)
        
        if old_state.state == STATE_ON and new_state.state != STATE_ON:
            # DEPARTURE (OFF)
            self._occupancy_on_since = None
            self._last_occupancy_off_time = now # Track valid OFF time
            self.occupancy_debouncer.handle_change(False, now)

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
        if dt < 4.5: return # Need at least 5 mins roughly, or keep accumulating? 
        # Update every 5 mins approx if loop is 1 min?
        
        delta = current_temp - self._prev_temp
        
        # Check Gradient
        # Heuristic: Drop > 0.5K in 5 mins
        newly_detected = False
        if delta < -0.4: # Slightly sensitive
             _LOGGER.info("[%s] Window Open Detected! Gradient: %.2fK in %.1f min", self.device_name, delta, dt)
             self._window_open_detected = True
             self._window_cooldown_counter = 30 # Paused for 30 mins
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

    async def _async_update_data(self) -> PreheatData:
        """Main Loop."""
        try:
            await self._check_entity_availability(self._get_conf(CONF_TEMPERATURE), "temperature")
            
            now = dt_util.now()
            
            # Feed History Buffer (V3)
            op_temp_raw = await self._get_operative_temperature()
            valve_pos_raw = self._get_valve_position()
            
            # V2.8: Check Session End (Debounce)
            # Use UTC to match internal debouncer logic
            await self.occupancy_debouncer.check(dt_util.utcnow())
            
            if op_temp_raw > INVALID_TEMP:
                 v_val = valve_pos_raw if valve_pos_raw is not None else (100.0 if self._preheat_active else 0.0)
                 self.history_buffer.append(HistoryPoint(
                     timestamp=now.timestamp(), 
                     temp=op_temp_raw, 
                     valve=v_val, 
                     is_active=self._preheat_active
                 ))

            # 1. Get Next Arrival
            blocked_dates = await self._get_blocked_dates_from_calendar(now)

            allowed_weekdays = None
            if self._get_conf(CONF_ONLY_ON_WORKDAYS, False):
                 workday_sensor = self._get_effective_workday_sensor()
                 if workday_sensor:
                     state = self.hass.states.get(workday_sensor)
                     # Check if sensor provides 'workdays' attribute (list of allowed days)
                     if state and state.state != "unavailable":
                         w_attr = state.attributes.get("workdays")
                         if isinstance(w_attr, list):
                             # Map ['mon', 'tue'] -> [0, 1]
                             week_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
                             allowed_weekdays = []
                             for day_str in w_attr:
                                 if str(day_str).lower() in week_map:
                                     allowed_weekdays.append(week_map[str(day_str).lower()])
                         else:
                             # Fallback: Default to Mon-Fri if attribute missing but sensor exists
                             _LOGGER.warning("Workday sensor %s missing 'workdays' attribute. Fallback to Mon-Fri.", workday_sensor)
                             allowed_weekdays = [0, 1, 2, 3, 4]
                     else:
                          # Sensor unavailable/missing -> Fallback Mon-Fri
                          # Reduce log level to INFO to avoid startup noise
                          _LOGGER.info("Workday sensor %s not ready yet (state: %s). Fallback to Mon-Fri.", 
                                       workday_sensor, state.state if state else "None")
                          allowed_weekdays = [0, 1, 2, 3, 4]
                 else:
                     # Helper enabled but no sensor configured?! Fallback Mon-Fri
                     allowed_weekdays = [0, 1, 2, 3, 4]

            # Holiday Detection: If today is a holiday (Sensor OFF), start searching from TOMORROW
            search_start_date = now
            if allowed_weekdays is not None:
                 # Re-fetch state (safe, cached)
                 ws_conf = self._get_effective_workday_sensor()
                 if ws_conf:
                     ws_state = self.hass.states.get(ws_conf)
                     if ws_state and ws_state.state == "off":
                         _LOGGER.debug("Workday Sensor is OFF (Holiday). Skipping today for Next Arrival search.")
                         search_start_date = now + timedelta(days=1)

            next_event = self.planner.get_next_scheduled_event(search_start_date, allowed_weekdays=allowed_weekdays, blocked_dates=blocked_dates)
            
            # v2.6 Pattern Meta Extraction
            p_res = self.planner.last_pattern_result
            pattern_type = p_res.pattern_type if p_res else "none"
            pattern_conf = p_res.confidence if p_res else 0.0
            pattern_stab = p_res.stability if p_res else 0.0
            detected_modes = p_res.modes_found if p_res else None
            fallback_used = p_res.fallback_used if p_res else False
            
            # 2. Calculate Physics
            operative_temp = op_temp_raw # Reuse
            
            # Update Gradient / Window Detection (approx every 5 min)
            if operative_temp > INVALID_TEMP:
                # We call it every minute logic, but internal it waits for elapsed time
                self._track_temperature_gradient(operative_temp, now)

            target_setpoint = await self._get_target_setpoint()
            outdoor_temp = await self._get_outdoor_temp_current()
            
            if operative_temp <= INVALID_TEMP:
                # Sensor error, bail out safe
                return PreheatData(False, None, None, target_setpoint, next_event, 0, 0, 0, False)

            # Delta Calculation
            delta_in = target_setpoint - operative_temp
            # delta_out = target_setpoint - outdoor_temp # Logic moved below
            
            # --- Forecast Integration (V2.4) ---
            predicted_duration = 0.0
            use_forecast = self._get_conf(CONF_USE_FORECAST, False)
            weather_entity = self._get_conf(CONF_WEATHER_ENTITY)
            forecasts = None
            
            if use_forecast and weather_entity:
                if not self.weather_service or self.weather_service.entity_id != weather_entity:
                    self.weather_service = WeatherService(self.hass, weather_entity)
                
                # Fetch Weather Data
                forecasts = await self.weather_service.get_forecasts()
                
                # Diagnostic: Check for persistent weather failure
                if forecasts is None:
                    # If we are up for > 5 minutes and still fail:
                    if (dt_util.utcnow() - self._startup_time).total_seconds() > 300:
                         async_create_issue(
                            self.hass,
                            DOMAIN,
                            f"weather_setup_failed_{self.entry.entry_id}",
                            is_fixable=False,
                            is_persistent=False,
                            severity=IssueSeverity.WARNING,
                            translation_key="weather_setup_failed",
                            translation_placeholders={
                                "weather_entity": self.weather_service.entity_id,
                                "zone_name": self.device_name
                            }
                        )
                else:
                    # Success -> Clear issue
                    async_delete_issue(
                        self.hass, DOMAIN, f"weather_setup_failed_{self.entry.entry_id}"
                    )
            
            if forecasts:
                # ROOT FINDING LOGIC
                risk_mode = self._get_conf(CONF_RISK_MODE, RISK_BALANCED)
                
                def _duration_eval(test_dur_min: float) -> float:
                    # g(d) = calculated - d
                    # If d=0, calc > 0. g(0) > 0.
                    # We look for g(d) <= 0.
                    if test_dur_min < 0: return 100.0
                    
                    # Window: Now -> Now + d
                    win_end = now + timedelta(minutes=test_dur_min)
                    
                    # Effective Outdoor Temp
                    t_out = math_preheat.calculate_risk_metric(forecasts, now, win_end, risk_mode)
                    
                    d_out = target_setpoint - t_out
                    req = self.physics.calculate_duration(delta_in, d_out)
                    return req - test_dur_min

                # Fix v2.9.0-beta6: Use wider horizon to detect if limit is exceeded
                # We search up to 12 hours. If result > max_preheat_hours, we warn the user.
                uncapped_duration = math_preheat.root_find_duration(_duration_eval, 720)
                
                # Extrapolation Warning (Check based on what we would need)
                if forecasts and (now + timedelta(minutes=uncapped_duration)) > forecasts[-1]["datetime"]:
                     if uncapped_duration > 15: # Ignore trivial
                        _LOGGER.warning("Forecast extrapolation active (> 50% window). Prediction may be inaccurate.")
                
                # Assign explicitly for logic usage (Capped by User Limit)
                max_dur_minutes = self._get_conf(CONF_MAX_PREHEAT_HOURS, 3.0) * 60
                predicted_duration = min(uncapped_duration, max_dur_minutes)
            
            else:
                # Classic Logic
                delta_out = target_setpoint - outdoor_temp 
                raw_duration = self.physics.calculate_duration(delta_in, delta_out)
                
                max_dur_minutes = self._get_conf(CONF_MAX_PREHEAT_HOURS, 3.0) * 60
                uncapped_duration = raw_duration
                predicted_duration = min(raw_duration, max_dur_minutes)
            
            # -----------------------------------
            
            # Smart Diagnostic: Check if duration exceeds limit
            # We compare the UNCAPPED requirement vs the limit.
            # Only warn if we actually have a target event scheduled.
            if next_event and uncapped_duration > (max_dur_minutes + 30):
                # We need more time than allowed!
                async_create_issue(
                    self.hass, DOMAIN, f"limit_exceeded_{self.entry.entry_id}",
                    is_fixable=False, 
                    severity=IssueSeverity.WARNING,
                    translation_key="duration_limit_exceeded",
                    translation_placeholders={
                        "predicted": f"{uncapped_duration/60:.1f}",
                        "limit": f"{max_dur_minutes/60:.1f}",
                        "name": self.device_name
                    },
                )
            else:
                 # Clear if resolved
                 async_delete_issue(self.hass, DOMAIN, f"limit_exceeded_{self.entry.entry_id}")
            
            # 3. Decision Logic
            start_time = None
            should_start = None # None=Idle/Evaluating, True=Start, False=Blocked
            
            if next_event:
                # Add Buffer
                buffer = self._get_conf(CONF_BUFFER_MIN, 10)
                start_time = next_event - timedelta(minutes=predicted_duration + buffer)
                
                # Earliest Start Check
                earliest_min = self._get_conf(CONF_EARLIEST_START, 180) # e.g. 03:00
                earliest_dt = next_event.replace(hour=0, minute=0, second=0) + timedelta(minutes=earliest_min)
                
                if start_time < earliest_dt:
                    start_time = earliest_dt
                
                # Check Triggers
                # Trigger preheat if within the active window (Start Time <= Now < Arrival).
                if start_time <= now < next_event:
                     should_start = True
            
            # 4. Decison Logic (Should we start?)
            # -----------------------------------
            blocked_reasons = [] # Collect all blocking reasons
            # should_start decision flows from Step 3. Do NOT reset it here.

            # Master Switch
            if not self.enable_active:
                # ACTION 3.3 A: FROST PROTECTION Override
                # If disabled, but temp < 5.0 °C, force ON for safety.
                is_frost_danger = operative_temp < 5.0 and operative_temp > INVALID_TEMP
                
                if is_frost_danger:
                    if not self._frost_active:
                         _LOGGER.warning("FROST PROTECTION ACTIVATED! Temp %.1f < 5.0. Forcing Preheat.", operative_temp)
                         self._frost_active = True
                    
                    # Force decision to start/continue
                    should_start = True
                    blocked_reasons = [] # Clear blocks
                    print(f"DEBUG: Frost Protection Active! should_start=True") # DEBUG
                    
                else:
                    self._frost_active = False
                    blocked_reasons.append("disabled")
                    should_start = False
            else:
                 self._frost_active = False # Reset if manually enabled
            
            # Occupancy (User is Home)
            occ_sensor = self._get_conf(CONF_OCCUPANCY)
            is_occupied = False
            if occ_sensor and self.hass.states.is_state(occ_sensor, STATE_ON):
                is_occupied = True
                should_start = False
                print(f"DEBUG: Occupancy Block! should_start=False") # DEBUG
            
            # Window Open
            if self._window_open_detected:
                blocked_reasons.append("window_open")
                should_start = False
                print(f"DEBUG: Window Block! should_start=False") # DEBUG

            # Don't start if warm (Comfort reached)
            # This is "Control Logic", not "Blocking". 
            if self._get_conf(CONF_DONT_START_IF_WARM, True):
                if delta_in < 0.2: should_start = False
                
            # Internal Hold Switch
            if self.hold_active:
                 blocked_reasons.append("hold")
                 should_start = False

            # External Inhibit / Lock
            lock = self._get_conf(CONF_LOCK)
            if lock:
                 if self.hass.states.is_state(lock, STATE_ON):
                      blocked_reasons.append(REASON_EXTERNAL_INHIBIT)
                      should_start = False
                 
            # Calendar / Holiday (Already checked in Step 1?)
            # blocked_dates was fetched earlier.
            if now.date() in blocked_dates:
                 blocked_reasons.append("holiday")
                 should_start = False

            # Workday Sensor Override (Fix for Issue: Starting on Holidays)
            if self._get_conf(CONF_ONLY_ON_WORKDAYS, False):
                 wd_ent = self._get_conf(CONF_WORKDAY)
                 if wd_ent:
                      wd_state = self.hass.states.get(wd_ent)
                      # If Workday Sensor is explicitly 'off', it is a holiday/weekend -> BLOCK.
                      if wd_state and wd_state.state == "off":
                           if should_start: # Log only if it WOULD have started
                                _LOGGER.debug("Preheat BLOCKED by Workday Sensor (State: Off)")
                           blocked_reasons.append("workday_sensor")
                           should_start = False

            # Missing Schedule (Logic Gap)
            if next_event is None and not blocked_reasons and should_start is None:
                # If we don't know when to start, and nothing else blocked us.
                # Technically not "blocked", just "idle".
                pass



            # 5. Actuate
            if should_start and not self._preheat_active:
                await self._start_preheat(operative_temp)
            
            elif self._preheat_active:
                # Stop conditions
                # 1. Target reached
                if delta_in <= 0.2: # Comfortable
                    await self._stop_preheat(operative_temp, target_setpoint, outdoor_temp)
                # 2. User came home
                elif is_occupied:
                    # User came home. Stop preheat, but ALLOW learning (aborted=False).
                    # If we generated some heat (DeltaT > 0.2), we want to account for it.
                    # This fixes the "Preheat starts too late -> User arrives -> Data discarded -> Loop" issue.
                    _LOGGER.info("User arrived during preheat. Stopping and attempting to learn from partial run.")
                    await self._stop_preheat(operative_temp, target_setpoint, outdoor_temp, aborted=False)
                # 3. Timeout
                elif self._preheat_started_at:
                    max_hours = self._get_conf(CONF_MAX_PREHEAT_HOURS, 3.0)
                    runtime = (dt_util.utcnow() - self._preheat_started_at).total_seconds() / 3600
                    if runtime > max_hours:
                        _LOGGER.info("Preheat timed out (>%.1fh). Stopping (with learning).", max_hours)
                        # We allow learning here! If we ran for Max Hours and got some rise, 
                        # we want the model to know it was too slow (it will learn a higher Mass Factor).
                        await self._stop_preheat(operative_temp, target_setpoint, outdoor_temp, aborted=False)
                # 4. Window Open
                elif self._window_open_detected:
                     await self._stop_preheat(operative_temp, target_setpoint, outdoor_temp, aborted=True)

            # V2.9.1 Diagnostics Check (Debounced inside)
            await self._check_diagnostics()

            # Comfort Learning (Update Setpoint preference)
            await self._update_comfort_learning(target_setpoint, is_occupied)

            # --- V2.5 Optimal Stop Logic ---
            opt_active = False
            opt_time = None
            opt_reason = "disabled"
            savings_total = 0.0
            savings_remaining = 0.0
            
            # Helper to get HVAC Action
            is_heating_now = False
            climate_ent = self._get_conf(CONF_CLIMATE)
            if climate_ent:
                 c_state = self.hass.states.get(climate_ent)
                 if c_state and c_state.attributes.get("hvac_action") == "heating":
                      is_heating_now = True
            v_pos = self._get_valve_position()
            if v_pos is not None and v_pos > 0: is_heating_now = True
            if self._preheat_active: is_heating_now = True

            # --- V3.0 Provider Arbitration & Optimal Stop ---
            
            # 1. Update Cooling Analyzer (Always needed for logic/gates)
            # Legacy: Was only inside Optimal Stop block. Safe to run always (passive).
            session_end_legacy = None
            if self.session_resolver:
                 session_end_legacy = self.session_resolver.get_current_session_end()

            self.cooling_analyzer.add_data_point(
                now, operative_temp, outdoor_temp, is_heating_now,
                window_open=self._window_open_detected
            )
            if now.minute % 30 == 0:
                 self.cooling_analyzer.analyze()

            # 2. Prepare Context
            context = {
                "now": now,
                "operative_temp": operative_temp,
                "target_setpoint": target_setpoint,
                "forecasts": forecasts, # Scope from above
                "tau_hours": self.cooling_analyzer.learned_tau,
                "physics_deadtime": self.physics.deadtime,
                "outdoor_temp": outdoor_temp,
                # Shadow Inputs
                 "tau_confidence": self.cooling_analyzer.confidence,
                 "pattern_confidence": pattern_conf
            }

            # 3. Provider Query
            # 3. Provider Query (Schedule / Static Timestamp)
            sched_ent = self._get_conf(CONF_SCHEDULE_ENTITY)
            sched_decision = None
            scheduled_end = None
            
            # Case A: Schedule Entity (Standard)
            if sched_ent and sched_ent.startswith("schedule."):
                sched_decision = self.schedule_provider.get_decision(context)
                scheduled_end = sched_decision.session_end
            
            # Case B: Timestamp Entity (input_datetime or sensor)
            elif sched_ent:
                # We replicate a "Virtual Schedule" decision
                state = self.hass.states.get(sched_ent)
                if state and state.state not in ("unavailable", "unknown"):
                    ts = None
                    # Is it a timestamp?
                    try:
                        # input_datetime usually has timestamp attribute if full date, or we interpret time
                        if "timestamp" in state.attributes and state.attributes["timestamp"]:
                             ts = dt_util.utc_from_timestamp(state.attributes["timestamp"])
                        else:
                             ts = dt_util.parse_datetime(state.state)
                        
                        if ts:
                            # If it's just time, assume today/tomorrow?
                            # input_datetime with only time returns 1970-01-01 usually?
                            # For simplicity, assume user provides full datetime or we handle naive time later.
                            # Actually, parse_datetime handles ISO.
                            
                            # Valid Timestamp found. Check if it's in the future.
                            if ts > now:
                                 scheduled_end = ts
                                 # Fake a decision
                                 from .providers import ProviderDecision
                                 sched_decision = ProviderDecision(
                                     should_stop=False,
                                     session_end=ts,
                                     is_valid=True,
                                     is_shadow=False,
                                     confidence=1.0
                                 )
                    except Exception as e:
                        _LOGGER.warning("Failed to parse timestamp from %s: %s", sched_ent, e)

            # Case C: No Schedule (Fallback to None)
            if not sched_decision:
                 # Default empty decision using ProviderDecision directly if needed, or rely on defaults
                 # Actually, calling schedule_provider.get_decision with empty context returns a safe default?
                 # Better: Use the provider properly.
                 sched_decision = self.schedule_provider.get_decision(context)
            
            scheduled_end = sched_decision.session_end
            
            
            # Forward Schedule Data to Shadow (Proxy for v2.7)
            # Pass None if 0.0 to allow LearnedProvider to skip 'savings gate'
            s_savings = sched_decision.predicted_savings
            context["potential_savings"] = s_savings if s_savings and s_savings > 0 else None
            context["scheduled_end"] = sched_decision.session_end
            learned_decision = self.learned_provider.get_decision(context)
            
            # 4. Arbitration & Effective Departure
            selected_provider = PROVIDER_NONE
            valid_providers = []
            invalid_reasons = {}
            gates_failed = learned_decision.gates_failed
            
            if sched_decision.is_valid: valid_providers.append(PROVIDER_SCHEDULE)
            else: invalid_reasons[PROVIDER_SCHEDULE] = sched_decision.invalid_reason
            
            if learned_decision.is_valid: valid_providers.append(PROVIDER_LEARNED)
            else: invalid_reasons[PROVIDER_LEARNED] = learned_decision.invalid_reason
            
            # --- Effective Departure Logic ---
            effective_departure = None
            effective_departure_source = "none"
            
            scheduled_end = sched_decision.session_end
            ai_end = learned_decision.session_end
            
            if learned_decision.is_valid and not learned_decision.is_shadow:
                 effective_departure = ai_end
                 effective_departure_source = "ai"
            elif scheduled_end is not None:
                 effective_departure = scheduled_end
                 effective_departure_source = "schedule"
            elif learned_decision.session_end is not None:
                 # Fallback to AI if no schedule is present (Observer Mode -> Active)
                 # Guard: If AI prediction is in the Past (e.g. today 17:00, now 18:00), ignore it to prevent instant logic firing.
                 if learned_decision.session_end > now:
                      effective_departure = learned_decision.session_end
                      effective_departure_source = "ai_fallback"
                 else:
                      effective_departure = None
                      effective_departure_source = "ai_expired"
            else:
                 effective_departure = None
                 effective_departure_source = "none"

            # --- Provider Selection ---
            if self.hold_active:
                selected_provider = PROVIDER_MANUAL
                # Create copy before mutating
                gates_failed = list(learned_decision.gates_failed or [])
                gates_failed.append(GATE_FAIL_MANUAL)
            elif sched_decision.is_valid:
                selected_provider = PROVIDER_SCHEDULE
            elif learned_decision.is_valid and not learned_decision.is_shadow:
                selected_provider = PROVIDER_LEARNED
            
            # -----------------------------------
            # Update Active Decision (Optimal Stop)
            # -----------------------------------
            
            # v2.9 Schedule-Free Logic: Pass predicted departure (multi-modal) as fallback
            predicted_departure = self.planner.get_next_predicted_departure(now)
            
            # Note: next_event might already be set from prediction if planner fallback used,
            # but usually next_event here comes from Schedule Entity if present.
            # We explicitly pass the prediction to let OptimalStopManager decide.
            
            # Helper for forecast callback
            def _forecast_cb(s, e):
                if forecasts:
                    return math_preheat.calculate_risk_metric(forecasts, s, e, "balanced")
                return context.get("outdoor_temp", 10.0)
            forecast_temp_at = _forecast_cb

            self.optimal_stop_manager.update(
                current_temp=operative_temp,
                target_temp=target_setpoint,
                schedule_end=next_event,
                predicted_end=predicted_departure, # v2.9 Multi-Modal Prediction
                forecast_provider=forecast_temp_at,
                tau_hours=self.cooling_analyzer.learned_tau,
                config={
                    CONF_STOP_TOLERANCE: self._get_conf(CONF_STOP_TOLERANCE, DEFAULT_STOP_TOLERANCE),
                    CONF_MAX_COAST_HOURS: self._get_conf(CONF_MAX_COAST_HOURS, DEFAULT_MAX_COAST_HOURS),
                    CONF_PHYSICS_MODE: self._get_conf(CONF_PHYSICS_MODE, PHYSICS_STANDARD),
                    "system_inertia": self.physics.deadtime, # Dynamic Inertia
                    "forecasts": forecasts
                }
            )

            # Determine Target Departure for Manager
            # Only use real departure if:
            # 1. Feature is enabled
            # 2. Manual Hold is NOT active (Kill Switch)
            # Otherwise None force-resets logic.
            target_departure_for_manager = effective_departure
            # 0. Master Enable Check
            if not self.enable_active:
                 return PreheatData(
                    preheat_active=False,
                    next_start_time=None,
                    operative_temp=operative_temp,
                    target_setpoint=target_setpoint,
                    next_arrival=None,
                    predicted_duration=0,
                    mass_factor=self.physics.mass_factor,
                    loss_factor=self.physics.loss_factor,
                    learning_active=False,
                    decision_trace={"blocked": True, "reason": "disabled"}
                 )

            # 0.1 Check for Hold
            if self.hold_active or not self._get_conf(CONF_ENABLE_OPTIMAL_STOP, False):
                target_departure_for_manager = None
            

            
            # Feature Migration/Warning UX (Preserved)
            # v2.9.0-beta2: Schedule is optional, so we always remove the "missing_schedule" warning if it exists.
            async_delete_issue(self.hass, DOMAIN, f"missing_schedule_{self.entry.entry_id}")
            
            # Read detailed state from manager (Always, to catch active/savings state)
            opt_active = self.optimal_stop_manager.is_active
            opt_time = self.optimal_stop_manager.stop_time
            opt_reason = self.optimal_stop_manager.debug_info["reason"]
            savings_total = self.optimal_stop_manager._savings_total
            savings_remaining = self.optimal_stop_manager._savings_remaining
            
            # 6. Trace Building
            # Polish: Only show global gates_failed if AI was the intended target or candidate.
            # If we selected Schedule, the global "failed gates" might be confusing.
            trace_gates_failed = gates_failed
            if effective_departure_source == "schedule":
                 trace_gates_failed = []

            decision_trace = {
                "schema_version": SCHEMA_VERSION,
                KEY_EVALUATED_AT: now.isoformat(),
                KEY_PROVIDER_SELECTED: selected_provider,
                KEY_PROVIDER_CANDIDATES: valid_providers,
                KEY_PROVIDERS_INVALID: invalid_reasons,
                KEY_GATES_FAILED: trace_gates_failed,
                KEY_GATE_INPUTS: learned_decision.gate_inputs or {},
                "timeline": {
                    "scheduled_departure": scheduled_end.isoformat() if scheduled_end else None,
                    "ai_departure": ai_end.isoformat() if ai_end else None,
                    "effective_departure": effective_departure.isoformat() if effective_departure else None,
                    "effective_departure_source": effective_departure_source
                },
                "providers": {
                    PROVIDER_SCHEDULE: {
                        "should_stop": sched_decision.should_stop,
                        "savings": sched_decision.predicted_savings,
                        "session_end": sched_decision.session_end.isoformat() if sched_decision.session_end else None
                    },
                    PROVIDER_LEARNED: {
                         "gates_failed": gates_failed, # Explicitly visible here
                         "confidence": learned_decision.confidence,
                         "savings": learned_decision.predicted_savings,
                         "session_end": learned_decision.session_end.isoformat() if learned_decision.session_end else None,
                         "should_stop": learned_decision.should_stop,
                         "is_shadow": learned_decision.is_shadow
                    }
                },
                "blocked": len(blocked_reasons) > 0,
                "reason": blocked_reasons[0] if blocked_reasons else "none",
                "blocked_reasons": blocked_reasons,
                "is_active": self._preheat_active,
                "is_occupied": is_occupied
            }
            
            # 7. Shadow Logging & Metrics
            # A. Check for Simulated Safety Violation
            # If Learned Provider wanted to stop (is_shadow=True, should_stop=True)
            # BUT we are currently ACTIVE (Schedule is ON)
            # AND Temp drops below Safe Threshold (Target - Tolerance - Buffer)
            # THEN -> Safety Violation
            
            # We need to know if the Learned Provider is *persistently* asking to stop, 
            # or if this is just a transient frame.
            # Assuming 'shadow_active' concept:
            # If (Legacy=ON) AND (Learned=STOP), we are efficiently "In Shadow Coast".
            
            is_shadow_coasting = False
            if selected_provider == PROVIDER_SCHEDULE and not learned_decision.is_shadow: 
                 # If Learned was not "Shadow", it would have participated in arbitration.
                 pass
            
            # Shadow Logic:
            # We are in "Shadow Mocking" if the legacy system (Schedule) wants to HEAT,
            # but the new AI (Learned) says STOP. This delta represents potential savings.
            
            in_shadow_zone = (
                sched_decision.is_valid and not sched_decision.should_stop and
                learned_decision.is_valid and learned_decision.should_stop
            )
            
            if in_shadow_zone:
                 # Check Safety
                 # Allow 0.2 buffer (same as optimal stop)
                 tol = self._get_conf(CONF_STOP_TOLERANCE, DEFAULT_STOP_TOLERANCE)
                 safe_floor = target_setpoint - tol - 0.2
                 
                 if operative_temp < safe_floor:
                      self._shadow_metrics["safety_violations"] += 1
                      _LOGGER.warning("Shadow Mode Safety Violation! Temp %.1f < %.1f", operative_temp, safe_floor)
            
            # For now, just debug log if meaningful difference (Edge Triggered)
            # We use 'in_shadow_zone' (Schedule=RUN, Learned=STOP) as the exact condition.
            should_shadow_log = in_shadow_zone
            
            if should_shadow_log and not self._last_shadow_log_state:
                 _LOGGER.debug("Shadow Mode: Learned Provider would STOP now. (Confidence: %.2f)", learned_decision.confidence if learned_decision.confidence else 0.0)
            
            self._last_shadow_log_state = should_shadow_log

            # Add metrics to trace
            decision_trace["metrics"] = self._shadow_metrics
            
            # Update output
            # Fire Optimal Stop Start Event (Edge Trigger)
            if opt_active and not self._last_opt_active:
                 self.hass.bus.async_fire(f"{DOMAIN}_optimal_stop_start", {
                    "zone": self.device_name,
                    "reason": opt_reason,
                    "savings_min": round(savings_total, 1),
                    "session_end": effective_departure.isoformat() if effective_departure else None
                })
            self._last_opt_active = opt_active
            
            # V2.9: Fetch HVAC State for Heat Demand Sensor
            hvac_action = None
            hvac_mode = None
            climate_key = self._get_conf(CONF_CLIMATE)
            if climate_key:
                 state = self.hass.states.get(climate_key)
                 if state:
                      hvac_mode = state.state
                      hvac_action = state.attributes.get("hvac_action")

            data = PreheatData(
                preheat_active=self._preheat_active,
                next_start_time=start_time,
                operative_temp=operative_temp,
                target_setpoint=target_setpoint,
                next_arrival=next_event,
                predicted_duration=predicted_duration,
                mass_factor=self.physics.mass_factor,
                loss_factor=self.physics.loss_factor,
                learning_active=self._preheat_active and not self._window_open_detected,
                schedule_summary=self.planner.get_schedule_summary(),
                departure_summary=self.planner.get_departure_schedule_summary(),
                valve_signal=self._get_valve_position(),
                window_open=self._window_open_detected,
                outdoor_temp=outdoor_temp,
                last_comfort_setpoint=self._last_comfort_setpoint,
                deadtime=self.physics.deadtime,
                is_occupied=is_occupied, # V2.9
                # V2.5
                optimal_stop_active=opt_active,
                optimal_stop_time=opt_time,
                stop_reason=opt_reason,
                savings_total=savings_total,
                savings_remaining=savings_remaining,
                coast_tau=self.cooling_analyzer.learned_tau,
                tau_confidence=self.cooling_analyzer.confidence,
                # V2.6
                pattern_type=pattern_type,
                pattern_confidence=pattern_conf,
                pattern_stability=pattern_stab,
                detected_modes=detected_modes,
                fallback_used=fallback_used,
                # v3.0
                decision_trace=decision_trace,
                next_departure=effective_departure,
                # V2.9
                hvac_action=hvac_action,
                hvac_mode=hvac_mode
            )
            
            # Action 3.2: Adaptive Polling
            self._update_polling_interval(data)
            
            return data

        except Exception as err:
            raise UpdateFailed(f"Update failed: {err}") from err

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
                     valve_pos_avg = self._get_valve_position()
                
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
             state = self.hass.states.get(sensor)
             try:
                 self._cached_outdoor_temp = float(state.state)
                 self._last_weather_check = now
                 return self._cached_outdoor_temp
             except: pass
        
        return 10.0

    async def _update_comfort_learning(self, current_setpoint: float, is_occupied: bool) -> None:
        if not is_occupied or not self._occupancy_on_since: return
        duration = (dt_util.utcnow() - self._occupancy_on_since).total_seconds() / 60
        if duration < 15: return # Wait for settling
        
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

    def _update_polling_interval(self, data: PreheatData) -> None:
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
        if data.preheat_active or data.is_occupied or data.window_open:
            new_interval = timedelta(minutes=1)
        
        # 4. Approaching Start (< 2 hours)
        elif data.next_start_time:
            # Check time delta
            now = dt_util.utcnow()
            diff = (data.next_start_time - now).total_seconds()
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