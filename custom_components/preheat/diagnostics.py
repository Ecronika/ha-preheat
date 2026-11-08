"""Diagnostics Manager for Preheat."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, TYPE_CHECKING

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
    DIAG_MAX_VALVE_POS,
    CONF_MAX_PREHEAT_HOURS,
    DEFAULT_MAX_HOURS,
    LEARNING_STALL_EXPIRY_SEC,
    MASS_BOUND_STREAK_LIMIT
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
            "last_learning_attempt_ts": 0.0,
            "mass_bound_streak": 0,  # consecutive learning runs pushing past a profile bound
            "mass_bound_side": None,  # "lower" / "upper"
        }

    def load_data(self, data: dict[str, Any]) -> None:
        """Load persistent diagnostics data."""
        if data:
            self.data.update(data)
        # Consecutive-check counter is only meaningful within a run; older versions never
        # reset it, so a persisted value would raise stale_sensor on the first stale check.
        self.data["stale_sensor_counter"] = 0

    def _create_issue(self, issue_id: str, is_persistent: bool = False, **kwargs) -> None:
        """Helper to create HA repair issues."""
        # Default severity to warning if not specified
        severity = kwargs.pop("severity", IssueSeverity.WARNING)
        is_fixable = kwargs.pop("is_fixable", False)
        translation_key = kwargs.pop("translation_key", issue_id)
        
        placeholders = dict(kwargs.pop("translation_placeholders", {}) or {})
        # Zonenname IMMER bereitstellen
        placeholders.setdefault("name", self.entry.title or self.entry.data.get("name") or "Preheat")

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
            translation_placeholders=placeholders,
            **kwargs
        )

    def _delete_issue(self, issue_id: str) -> None:
        """Helper to delete HA repair issues."""
        issue_uid = f"{issue_id}_{self.entry.entry_id}"
        async_delete_issue(self.hass, DOMAIN, issue_uid)

    # Issue IDs raised by earlier versions whose checks no longer exist (or were renamed).
    # Persistent issues survive restarts, so they must be removed explicitly.
    LEGACY_ISSUE_IDS = (
        "physics_limit",          # old absolute mass/loss limits (physics_limit_mass_min/max, ...)
        "physics_railing",        # shared railing issue (split, then replaced by mass_at_bound)
        "physics_railing_mass",   # replaced by mass_at_bound (v2.12.0)
        "limit_exceeded",         # renamed to duration_limit_exceeded
        "sensor_unit",            # renamed to sensor_unit_mismatch
        "missing_schedule",
        "weather_setup_failed",
    )

    def cleanup_legacy_issues(self) -> None:
        """Remove repair issues of checks that no longer exist. Called once on setup."""
        for issue_id in self.LEGACY_ISSUE_IDS:
            self._delete_issue(issue_id)

    @staticmethod
    def _last_seen(state) -> datetime | None:
        """Last time the entity reported, even with an unchanged value.

        `last_updated` only moves when the state or attributes change; `last_reported`
        (HA >= 2024.3) also moves when the same value is written again (e.g. KNX cyclic
        sending, a stable room temperature).
        """
        stamps = [t for t in (getattr(state, "last_reported", None), state.last_updated)
                  if isinstance(t, datetime)]
        return max(stamps) if stamps else None

    def note_model_update(self, physics: ThermalPhysics) -> None:
        """Called after each successful model update: count consecutive updates that
        tried to push the mass factor past the same profile bound."""
        side = physics.last_mass_clamped
        if side and side == self.data.get("mass_bound_side"):
            self.data["mass_bound_streak"] = self.data.get("mass_bound_streak", 0) + 1
        elif side:
            self.data["mass_bound_side"] = side
            self.data["mass_bound_streak"] = 1
        else:
            self.data["mass_bound_side"] = None
            self.data["mass_bound_streak"] = 0

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
        loss = physics.loss_factor
        # Mass: warn when learning keeps pushing past the heating profile's bound (the value
        # is clamped there, so the profile likely does not match the room or learning is off).
        # Replaces the old absolute 5/240 check, which could never fire inside profile bounds.
        side = self.data.get("mass_bound_side")
        streak = self.data.get("mass_bound_streak", 0)
        if side and streak >= MASS_BOUND_STREAK_LIMIT:
            value = f"{physics.mass_factor:.1f}"
            if side == "upper":
                self._create_issue("mass_at_bound", translation_key="mass_at_upper_bound",
                                   translation_placeholders={"value": value, "count": str(streak)})
            else:
                self._create_issue("mass_at_bound", translation_key="mass_at_lower_bound",
                                   translation_placeholders={"value": value, "count": str(streak)})
        else:
            self._delete_issue("mass_at_bound")
             
        if loss <= 1.0 or loss >= 20.0:
             self._create_issue("physics_railing_loss", translation_key="physics_railing", translation_placeholders={"metric": "Loss Factor"})
        else:
             self._delete_issue("physics_railing_loss")
             

        # 2. Duration Limit (Restored)
        if pred["limit_exceeded"]:
             self._create_issue(
                 "duration_limit_exceeded",
                 translation_placeholders={
                     "predicted": f"{pred['uncapped_duration']/60:.1f}",
                     "limit": f"{self._get_conf(CONF_MAX_PREHEAT_HOURS, DEFAULT_MAX_HOURS):.1f}",
                 }
             )
        else:
             self._delete_issue("duration_limit_exceeded")
             
        # 3. Learning Stalled
        curr_samp = physics.sample_count
        last_samp = self.data.get("last_sample_count", 0)
        last_samp_ts = self.data.get("last_sample_change", 0.0)
        now = dt_util.utcnow().timestamp()
        
        # If last_sample_change is 0.0, we initialize it to now to avoid immediate false alarm on first boot
        if last_samp_ts == 0.0:
            last_samp_ts = now
            self.data["last_sample_change"] = now
            self.data["last_sample_count"] = curr_samp

        last_attempt_ts = self.data.get("last_learning_attempt_ts", 0.0)
        
        if curr_samp != last_samp:
            self.data["last_sample_count"] = curr_samp
            self.data["last_sample_change"] = now
            self._delete_issue("learning_stalled")
        else:
            stalled = (
                (now - last_samp_ts) > 604800            # > 7 days no new sample
                and curr_samp > 0
                and last_attempt_ts > last_samp_ts        # Attempt after last sample (no sample generated)
                and (now - last_attempt_ts) < LEARNING_STALL_EXPIRY_SEC   # ...and this attempt is still recent
            )
            if stalled:
                self._create_issue("learning_stalled")
            else:
                # Self-healing: no current stall (e.g. heating pause) -> remove issue
                self._delete_issue("learning_stalled")

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
                else:
                     self._delete_issue("forecast_stale")

                # Forecast Short (End < Now + 4h)
                end_dt = datetime.fromisoformat(ctx["forecasts"][-1]["datetime"])
                horizon = (end_dt - now).total_seconds() / 3600.0
                if horizon < 4.0: # Minimum safe horizon
                     self._create_issue("forecast_short", translation_placeholders={"horizon": f"{horizon:.1f}h"})
                else:
                     self._delete_issue("forecast_short")
            except (ValueError, IndexError, TypeError):
                 pass

            # Forecast Quality
            if weather_service.forecast_type_used != "hourly" and weather_service.forecast_type_used != "none":
                 self._create_issue("weather_quality", translation_placeholders={"type": weather_service.forecast_type_used})
            else:
                 self._delete_issue("weather_quality")
        else:
            # No forecast data to judge (missing forecasts are reported by weather_no_forecast)
            self._delete_issue("forecast_stale")
            self._delete_issue("forecast_short")
            self._delete_issue("weather_quality")
        
        # 5. Advanced / Missing Weather
        is_adv = (self._get_conf(CONF_PHYSICS_MODE) == PHYSICS_ADVANCED)
        w_ent = self._get_conf(CONF_WEATHER_ENTITY)
        
        if is_adv and not w_ent:
             self._create_issue("adv_no_weather")
        else:
             self._delete_issue("adv_no_weather")
        
        if w_ent and not ctx["forecasts"] and weather_service:
             # Weather entity configured but no forecasts returned
             self._create_issue("weather_no_forecast", translation_placeholders={"entity": w_ent})
        else:
             self._delete_issue("weather_no_forecast")

    async def _diag_sensors(self, ctx: Context, physics: ThermalPhysics, weather_service: WeatherService | None, pred: Prediction) -> None:
        """Check sensor health."""
        now = dt_util.utcnow()
        # 1. Stale Temperature Sensor (no report for > 6h)
        # Judge the entity that currently delivers the temperature: the dedicated sensor,
        # or the climate entity as fallback. unavailable/unknown is not "stale" (that is
        # covered by the no_temperature issue).
        source = None
        for entity_id in (self._get_conf(CONF_TEMPERATURE), self._get_conf(CONF_CLIMATE)):
            if not entity_id:
                continue
            st = self.hass.states.get(entity_id)
            if st and st.state not in ("unavailable", "unknown"):
                source = (entity_id, st)
                break

        last_seen = self._last_seen(source[1]) if source else None
        if last_seen is not None and (now - last_seen).total_seconds() > DIAG_STALE_SENSOR_SEC:
            self.data["stale_sensor_counter"] = self.data.get("stale_sensor_counter", 0) + 1
            if self.data["stale_sensor_counter"] > 1:  # confirmed on a second check
                self._create_issue("stale_sensor", translation_placeholders={"entity": source[0]})
        else:
            # Fresh report (or nothing to judge): reset and clear
            self.data["stale_sensor_counter"] = 0
            self._delete_issue("stale_sensor")

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
                 else:
                      self._delete_issue("valve_saturation")
                      
        # 3. Occupancy Stale (> 3 days)
        occ_entity = self._get_conf(CONF_OCCUPANCY)
        if occ_entity:
             s = self.hass.states.get(occ_entity)
             if s and s.last_updated:
                 age_d = (now - s.last_updated).total_seconds() / 86400
                 if age_d > 3.0:
                      self._create_issue("occupancy_stale", translation_placeholders={"entity": occ_entity})
                 else:
                      self._delete_issue("occupancy_stale")
                      
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
             

        
        # 1b. Sanity Temp (Sensor Value)
        temp_val = ctx["operative_temp"]
        if temp_val is not None:
             out_val = ctx["outdoor_temp"]
             if temp_val < -10.0 or temp_val > 45.0:
                  # Implausible Indoor Temp
                  self._create_issue("sanity_temp", translation_placeholders={"detail": f"{temp_val}°C Implausible"})
             elif out_val is not None and temp_val < 10.0 and out_val > 20.0:
                  # Check Swap: Indoor < 10 AND Outdoor > 20 (Strong indication of swap)
                  self._create_issue("sanity_temp", translation_placeholders={"detail": "Indoor/Outdoor Swapped?"})
             else:
                  self._delete_issue("sanity_temp")

    async def _diag_config(self, ctx: Context, physics: ThermalPhysics, weather_service: WeatherService | None, pred: Prediction) -> None:
        """Check configuration sanity."""
        now = dt_util.utcnow()
        
        # 1. Zombie Schedule
        sched_entity = self._get_conf(CONF_SCHEDULE_ENTITY)
        sched_state = self.hass.states.get(sched_entity) if sched_entity else None
        if sched_state and sched_state.state == "on" and not sched_state.attributes.get("next_event"):
             self._create_issue("zombie_schedule", translation_placeholders={"entity": sched_entity})
        else:
             self._delete_issue("zombie_schedule")
                       
        # 2. Sanity Check
        target = ctx["target_setpoint"]
        if target and (target > 35.0 or target < 5.0):
             self._create_issue("config_sanity", translation_placeholders={"detail": f"Target {target}C unplausible"})
        else:
             self._delete_issue("config_sanity")
             
        # 3. Sensor Unit Mismatch
        t_ent = self._get_conf(CONF_TEMPERATURE)
        t_state = self.hass.states.get(t_ent) if t_ent else None
        if t_state and t_state.attributes.get("unit_of_measurement") not in ("°C", "C", None):
             self._create_issue("sensor_unit_mismatch", translation_placeholders={"entity": t_ent})
        else:
             self._delete_issue("sensor_unit_mismatch")
        
        # 4. Hold Stuck (> 24h)
        # Check External Inhibit (CONF_LOCK)
        lock_ent = self._get_conf(CONF_LOCK)
        lock_state = self.hass.states.get(lock_ent) if lock_ent else None
        if (lock_state and lock_state.state == STATE_ON and lock_state.last_changed
                and (now - lock_state.last_changed).total_seconds() / 3600.0 > 24.0):
             self._create_issue("hold_stuck", translation_placeholders={"entity": lock_ent})
        else:
             self._delete_issue("hold_stuck")
                            
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
        else:
             self._delete_issue("coast_capped")
             
        # 7. Tolerance Sanity
        tol = self._get_conf(CONF_STOP_TOLERANCE, 0.5)
        if tol < 0.1 or tol > 2.0:
             self._create_issue("tolerance_sanity", translation_placeholders={"val": str(tol)})
        else:
             self._delete_issue("tolerance_sanity")

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

