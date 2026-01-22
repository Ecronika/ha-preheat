"""Diagnostics Manager for Preheat."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, TYPE_CHECKING, Coroutine

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.const import STATE_ON
from homeassistant.helpers.issue_registry import async_create_issue, async_delete_issue, IssueSeverity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from .coordinator import PreheatingCoordinator
    from .types import Context, Prediction
    from .physics import ThermalPhysics
    from .weather_service import WeatherService

from .const import (
    DOMAIN,
    CONF_OCCUPANCY,
    CONF_TEMPERATURE,
    CONF_CLIMATE,
    CONF_OUTDOOR_TEMP,
    CONF_WEATHER_ENTITY,
    CONF_LOCK,
    CONF_PHYSICS_MODE,
    PHYSICS_ADVANCED,
    CONF_STOP_TOLERANCE,
    CONF_MAX_COAST_HOURS,
    CONF_SCHEDULE_ENTITY,
    DIAG_STALE_SENSOR_SEC,
    DIAG_MAX_VALVE_POS
)

_LOGGER = logging.getLogger(__name__)

class DiagnosticsManager:
    """Manages diagnostic checks and issue creation."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: PreheatingCoordinator):
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        
        # Diagnostics Persistence
        self.data: dict[str, Any] = {
            "last_sample_count": 0,
            "last_sample_change": 0.0,
            "hold_started_ts": None,
            "inhibit_started_ts": None,
            "occupancy_last_change_ts": 0.0,
            "capped_events": [], # Rolling list of bools
            "last_check_ts": 0.0,
            "stale_sensor_counter": 0, # Added initialization
        }

    def load_data(self, data: dict[str, Any]) -> None:
        """Load persistent diagnostics data."""
        if data:
            self.data.update(data)

    def _create_issue(self, issue_id: str, is_persistent: bool = False, **kwargs) -> None:
        """Helper to create HA repair issues."""
        # Default severity to warning if not specified
        severity = kwargs.pop("severity", IssueSeverity.WARNING)
        is_fixable = kwargs.pop("is_fixable", False)
        translation_key = kwargs.pop("translation_key", issue_id)
        
        # Append entry_id to make issue unique per device
        issue_uid = f"{issue_id}_{self.entry.entry_id}"
        
        async_create_issue(
            self.hass,
            DOMAIN,
            issue_uid,
            is_fixable=is_fixable,
            severity=severity,
            translation_key=translation_key,
            is_persistent=is_persistent,
            **kwargs
        )

    def _delete_issue(self, issue_id: str) -> None:
        """Helper to delete HA repair issues."""
        issue_uid = f"{issue_id}_{self.entry.entry_id}"
        async_delete_issue(self.hass, DOMAIN, issue_uid)

    def _get_conf(self, key: str, default: Any = None) -> Any:
        # Proxy to coordinator for config access
        return self.coordinator._get_conf(key, default)

    async def check_all(self, ctx: Context, physics: ThermalPhysics, weather_service: WeatherService | None, pred: Prediction) -> None:
        """Run all diagnostic checks."""
        await self._diag_physics(ctx, physics, weather_service, pred)
        await self._diag_sensors(ctx, physics, weather_service, pred)
        await self._diag_config(ctx, physics, weather_service, pred)
        await self._diag_weather(ctx, physics, weather_service, pred)

    async def _diag_physics(self, ctx: Context, physics: ThermalPhysics, weather_service: WeatherService | None, pred: Prediction) -> None:
        """Check physics sanity."""
        # 1. Railing Check
        mass = physics.mass_factor
        loss = physics.loss_factor
        if mass <= 5.0 or mass >= 240.0:
             self._create_issue("physics_railing_mass", translation_key="physics_railing", translation_placeholders={"metric": "Mass Factor"})
        else:
             self._delete_issue("physics_railing_mass")
             
        if loss <= 1.0 or loss >= 20.0:
             self._create_issue("physics_railing_loss", translation_key="physics_railing", translation_placeholders={"metric": "Loss Factor"})
        else:
             self._delete_issue("physics_railing_loss")
             
        # Cleanup legacy shared issue
        self._delete_issue("physics_railing")

        # 2. Duration Limit (Restored)
        if pred["limit_exceeded"]:
             self._create_issue("duration_limit_exceeded")
        else:
             self._delete_issue("duration_limit_exceeded")
             
        # 3. Learning Stalled
        curr_samp = physics.sample_count
        last_samp = self.data.get("last_sample_count", 0)
        last_samp_ts = self.data.get("last_sample_change", dt_util.utcnow().timestamp())
        now = dt_util.utcnow().timestamp()
        
        if curr_samp != last_samp:
            self.data["last_sample_count"] = curr_samp
            self.data["last_sample_change"] = now
            self._delete_issue("learning_stalled")
        else:
            # If changed > 7 days ago and we have some samples (bootstrap done)
            if (now - last_samp_ts) > 604800 and curr_samp > 0:
                self._create_issue("learning_stalled")

    async def _diag_weather(self, ctx: Context, physics: ThermalPhysics, weather_service: WeatherService | None, pred: Prediction) -> None:
         # 4. Weather / Forecast Checks
        now = dt_util.utcnow()
        if weather_service and ctx["forecasts"]:
            try:
                # Forecast Stale (Start > 4h ago)
                start_dt = datetime.fromisoformat(ctx["forecasts"][0]["datetime"])
                age_hours = (now - start_dt).total_seconds() / 3600.0
                if age_hours > 4.0:
                     self._create_issue("forecast_stale", translation_placeholders={"detail": f"Age {age_hours:.1f}h"})

                # Forecast Short (End < Now + 4h)
                end_dt = datetime.fromisoformat(ctx["forecasts"][-1]["datetime"])
                horizon = (end_dt - now).total_seconds() / 3600.0
                if horizon < 4.0: # Minimum safe horizon
                     self._create_issue("forecast_short", translation_placeholders={"horizon": f"{horizon:.1f}h"})
            except (ValueError, IndexError, TypeError):
                 pass

            # Forecast Quality
            if weather_service.forecast_type_used != "hourly" and weather_service.forecast_type_used != "none":
                 self._create_issue("weather_quality", translation_placeholders={"type": weather_service.forecast_type_used})
            else:
                 self._delete_issue("weather_quality")
        
        # 5. Advanced / Missing Weather
        is_adv = (self._get_conf(CONF_PHYSICS_MODE) == PHYSICS_ADVANCED)
        w_ent = self._get_conf(CONF_WEATHER_ENTITY)
        
        if is_adv and not w_ent:
             self._create_issue("adv_no_weather")
        
        if w_ent and not ctx["forecasts"] and weather_service:
             # Weather entity configured but no forecasts returned
             self._create_issue("weather_no_forecast", translation_placeholders={"entity": w_ent})

    async def _diag_sensors(self, ctx: Context, physics: ThermalPhysics, weather_service: WeatherService | None, pred: Prediction) -> None:
        """Check sensor health."""
        now = dt_util.utcnow()
        # 1. Stale Temperature Sensor (>6h)
        temp_entity = self._get_conf(CONF_TEMPERATURE)
        sensor_found = False
        
        if temp_entity:
            s_state = self.hass.states.get(temp_entity)
            if s_state:
                sensor_found = True
                if s_state.last_updated:
                    age = (now - s_state.last_updated).total_seconds()
                    if age > DIAG_STALE_SENSOR_SEC: # 6 hours
                         self.data.setdefault("stale_sensor_counter", 0)
                         self.data["stale_sensor_counter"] += 1
                         if self.data["stale_sensor_counter"] > 1:
                             self._create_issue("stale_sensor", translation_placeholders={"entity": temp_entity}, is_persistent=True)

        if not sensor_found:
             # Check Fallback (Climate)
             clim_entity = self._get_conf(CONF_CLIMATE)
             if clim_entity:
                 c_state = self.hass.states.get(clim_entity)
                 if c_state:
                      if c_state.last_updated:
                          age = (now - c_state.last_updated).total_seconds()
                          if age > DIAG_STALE_SENSOR_SEC:
                               self.data.setdefault("stale_sensor_counter", 0)
                               self.data["stale_sensor_counter"] += 1
                               if self.data["stale_sensor_counter"] > 1:
                                  self._create_issue("stale_sensor", translation_placeholders={"entity": clim_entity}, is_persistent=True)

        # 2. Valve Saturation
        # Access coordinator state directly
        if ctx["preheat_active"]:
             valve = ctx["valve_position"]
             op_temp = ctx["operative_temp"]
             target = ctx["target_setpoint"]
             if op_temp and target:
                 delta = target - op_temp
                 if valve is not None and valve > DIAG_MAX_VALVE_POS and delta > 2.0:
                      self._create_issue("valve_saturation")
                      
        # 3. Occupancy Stale (> 3 days)
        occ_entity = self._get_conf(CONF_OCCUPANCY)
        if occ_entity:
             s = self.hass.states.get(occ_entity)
             if s and s.last_updated:
                 age_d = (now - s.last_updated).total_seconds() / 86400
                 if age_d > 3.0:
                      self._create_issue("occupancy_stale", translation_placeholders={"entity": occ_entity})
                      
        # 4b. Inhibit Stuck (> 24h)
        is_inhib = self.coordinator._external_inhibit or self.coordinator._window_open_detected
        if is_inhib:
            if not self.data.get("inhibit_started_ts"):
                self.data["inhibit_started_ts"] = now.timestamp()
            elif (now.timestamp() - self.data["inhibit_started_ts"]) > 86400:
                 self._create_issue("inhibit_stuck")
        else:
             self.data["inhibit_started_ts"] = None
             self._delete_issue("inhibit_stuck") 
             
        # Check external window sensors
        ws_ent = self._get_conf("window_sensor") # Not a standard conf yet, but maybe inhibit?
        
        # 1b. Sanity Temp (Sensor Value)
        temp_val = ctx["operative_temp"]
        if temp_val is not None:
             if temp_val < -10.0 or temp_val > 45.0:
                  # Implausible Indoor Temp
                  self._create_issue("sanity_temp", translation_placeholders={"detail": f"{temp_val}°C Implausible"})
             else:
                  # Check Swap: Indoor < 10 AND Outdoor > 20 (Strong indication of swap)
                  out_val = ctx["outdoor_temp"]
                  if out_val and temp_val < 10.0 and out_val > 20.0:
                       self._create_issue("sanity_temp", translation_placeholders={"detail": "Indoor/Outdoor Swapped?"})

    async def _diag_config(self, ctx: Context, physics: ThermalPhysics, weather_service: WeatherService | None, pred: Prediction) -> None:
        """Check configuration sanity."""
        now = dt_util.utcnow()
        
        # 1. Zombie Schedule
        sched_entity = self._get_conf(CONF_SCHEDULE_ENTITY)
        if sched_entity:
             state = self.hass.states.get(sched_entity)
             if state and state.state == "on":
                  next_ev = state.attributes.get("next_event")
                  if not next_ev:
                       self._create_issue("zombie_schedule", translation_placeholders={"entity": sched_entity})
                       
        # 2. Sanity Check
        target = ctx["target_setpoint"]
        if target and (target > 35.0 or target < 5.0):
             self._create_issue("config_sanity", translation_placeholders={"detail": f"Target {target}C unplausible"})
             
        # 3. Sensor Unit Mismatch
        t_ent = self._get_conf(CONF_TEMPERATURE)
        if t_ent:
             s = self.hass.states.get(t_ent)
             if s and s.attributes.get("unit_of_measurement") not in ("°C", "C", None):
                  self._create_issue("sensor_unit_mismatch", translation_placeholders={"entity": t_ent})
        
        # 4. Hold Stuck (> 24h)
        # Check External Inhibit (CONF_LOCK)
        lock_ent = self._get_conf(CONF_LOCK)
        if lock_ent:
             s = self.hass.states.get(lock_ent)
             if s and s.state == STATE_ON:
                  if s.last_changed:
                       age_h = (now - s.last_changed).total_seconds() / 3600.0
                       if age_h > 24.0:
                            self._create_issue("hold_stuck", translation_placeholders={"entity": lock_ent})
                            
        # 5. No Outdoor Source
        if not self._get_conf(CONF_WEATHER_ENTITY) and not self._get_conf(CONF_OUTDOOR_TEMP):
             self._create_issue("no_outdoor_source")
        else:
             self._delete_issue("no_outdoor_source")

        # 6. Coast Capped (Optimal Stop)
        # Check if we are hitting the max coast buffer frequently?
        # (Requires capping event history)
        capped_count = sum(1 for x in self.data.get("capped_events", []) if x)
        total_events = len(self.data.get("capped_events", []))
        if total_events > 5 and (capped_count / total_events) > 0.5:
             # > 50% of stops capped
             self._create_issue("coast_capped")
             
        # 7. Tolerance Sanity
        tol = self._get_conf(CONF_STOP_TOLERANCE, 0.5)
        if tol < 0.1 or tol > 2.0:
             self._create_issue("tolerance_sanity", translation_placeholders={"val": str(tol)})

        # 8. Max Coast High (TRV)
        max_c = self._get_conf(CONF_MAX_COAST_HOURS, 4.0)
        # Heuristik: Schnelles System (Masse < 30) mit langer Coasting-Dauer (>3h)
        # Access mass via physics which is passed to check_all? No, we need physics passed to diag_config or general context
        # Fixed: physics is in coordinator, but passed to check_all. 
        # Actually _diag_config signature didn't take physics. Let's fix that or access via coordinator (less clean but works)
        if max_c >= 3.0 and physics.mass_factor < 30.0:
             self._create_issue("max_coast_high")
        else:
             self._delete_issue("max_coast_high")

        # Clean up legacy warnings
        async_delete_issue(self.hass, "preheat", f"missing_schedule_{self.entry.entry_id}")
