"""Optimal Stop logic (Coast-to-Stop) for Preheat."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

from .math_preheat import calculate_coast_duration, calc_forecast_mean_or_p90_placeholder
from .const import CONF_MAX_COAST_HOURS, CONF_STOP_TOLERANCE

_LOGGER = logging.getLogger(__name__)

# Constants
LATCH_RESET_DEBOUNCE_SEC = 120 # 2 minutes
MIN_SAVINGS_THRESHOLD_MIN = 10 # Don't stop for < 10 min savings
RECALC_THRESHOLD_MIN = 15      # Hysteresis for update

class SessionResolver:
    """Helper to determine the end of the current occupancy session."""
    
    def __init__(self, hass: HomeAssistant, schedule_entity: str | None):
        self._hass = hass
        self._entity_id = schedule_entity
    
    def get_current_session_end(self) -> datetime | None:
        """
        Get the end time of the current active session.
        Rely on 'schedule' entity 'next_event' attribute.
        """
        if not self._entity_id: return None
        
        state = self._hass.states.get(self._entity_id)
        if not state or state.state != "on":
            return None
            
        # Get next_event
        next_event_iso = state.attributes.get("next_event")
        if not next_event_iso:
            return None
            
        try:
            # next_event is usually ISO string
            end_dt = dt_util.parse_datetime(str(next_event_iso))
            return end_dt
        except Exception as e:
            _LOGGER.warning("Failed to parse next_event '%s': %s", next_event_iso, e)
            return None

class OptimalStopManager:
    """State Machine for Optimal Stop decision."""
    
    def __init__(self, hass: HomeAssistant):
        self._hass = hass
        
        # State
        self._active = False
        self._reason = "init"
        self._stop_time: datetime | None = None
        self._savings_total = 0.0
        self._savings_remaining = 0.0
        
        # Latch / Debounce state
        self._schedule_off_since: datetime | None = None
        self._last_target_temp: float | None = None
        
        # Helpers
        self.session_end: datetime | None = None
        self.target_floor: float | None = None
        self.forecast_used: float | None = None
        
    @property
    def is_active(self) -> bool:
        return self._active
        
    @property
    def stop_time(self) -> datetime | None:
        return self._stop_time
        
    @property
    def debug_info(self) -> dict:
        return {
            "active": self._active,
            "reason": self._reason,
            "session_end": self.session_end.isoformat() if self.session_end else None,
            "savings_total_min": round(self._savings_total, 1),
            "savings_remaining_min": round(self._savings_remaining, 1),
            "target_floor": round(self.target_floor, 1) if self.target_floor else None,
            "forecast_used": round(self.forecast_used, 1) if self.forecast_used else None
        }

    def update(
        self,
        current_temp: float,
        target_temp: float,
        schedule_end: datetime | None,
        forecast_provider, # Callable or Module to get forecast temp
        tau_hours: float,
        config: dict
    ) -> None:
        """
        Main logic loop. Called periodically by Coordinator.
        """
        now = dt_util.utcnow()
        tolerance = config.get(CONF_STOP_TOLERANCE, 0.5)
        max_coast = config.get(CONF_MAX_COAST_HOURS, 4.0) * 60.0 # minutes
        
        # 1. Reset Checks (Latch Breakers)
        
        # A. Setpoint Change
        if self._last_target_temp is not None and abs(target_temp - self._last_target_temp) > 0.1:
            if self._active:
                _LOGGER.info("Optimal Stop RESET: Target temp changed.")
                self._active = False
                self._reason = "setpoint_change"
        self._last_target_temp = target_temp
        
        # B. Session End or Schedule OFF
        if schedule_end is None:
            # Schedule is OFF or unavailable
            if self._active:
                # Debounce Logic
                if self._schedule_off_since is None:
                    self._schedule_off_since = now
                
                if (now - self._schedule_off_since).total_seconds() > LATCH_RESET_DEBOUNCE_SEC:
                    _LOGGER.info("Optimal Stop RESET: Schedule OFF for > %ds", LATCH_RESET_DEBOUNCE_SEC)
                    self._active = False
                    self._reason = "no_session"
                    self._schedule_off_since = None
            else:
                 self._reason = "no_session"
                 self._schedule_off_since = None
            
            # Stop processing if no session
            if not self._active: return

        else:
            # Schedule is ON
            self._schedule_off_since = None # Reset debounce
            self.session_end = schedule_end

        # C. Safety Break (Too Cold)
        floor = target_temp - tolerance
        self.target_floor = floor
        # Safety buffer 0.2C
        if current_temp < (floor - 0.2):
             if self._active:
                 _LOGGER.warning("Optimal Stop SAFETY BREAK: Too cold (%.1f < %.1f)", current_temp, floor-0.2)
                 self._active = False
                 self._reason = "too_cold_safety"
             else:
                 self._reason = "too_cold"
             return

        # 2. Solver Logic (If we have a valid session)
        if schedule_end:
             # Calculate T_out_eff
             # We need a window from NOW to SCHEDULE_END
             # Logic: Prediction phase uses Forecast Mean or P90 (hardcoded or config?)
             # For now, let's assume we pass a resolved t_out value or a provider
             # To keep it simple, we ask the provider for the 'coast_temp'
             
             t_out = forecast_provider(now, schedule_end)
             self.forecast_used = t_out
             
             # Calculate Duration
             duration_min = calculate_coast_duration(
                 t_start=current_temp,
                 t_floor=floor,
                 t_out_eff=t_out,
                 tau_hours=tau_hours,
                 max_minutes=max_coast
             )
             
             # Computed Stop Time
             computed_stop = schedule_end - timedelta(minutes=duration_min)
             
             # 3. Decision Logic
             
             # Calculate Savings
             # Theoretical savings
             savings = duration_min
             self._savings_total = savings
             
             # Remaining savings (from now)
             remaining = (schedule_end - now).total_seconds() / 60.0
             # Clamped by duration (can't save more than the coast duration)
             actual_remaining = min(remaining, duration_min) if remaining > 0 else 0
             self._savings_remaining = actual_remaining
             
             # Latch ON Condition
             if not self._active:
                 # Only activate if we passed the stop time? 
                 # Wait, Optimal Stop means "Turn Off NOW".
                 # So if Now >= computed_stop, we activate.
                 
                 # Also check Minimum Savings threshold
                 if duration_min < MIN_SAVINGS_THRESHOLD_MIN:
                     self._reason = "savings_too_small"
                     return
                 
                 if now >= computed_stop:
                     _LOGGER.info("Optimal Stop ACTIVATED. Saving %.1f min. Stop Time: %s", duration_min, computed_stop)
                     self._active = True
                     self._reason = "coasting"
                     self._stop_time = computed_stop
                 else:
                     self._reason = "waiting"
                     self._stop_time = computed_stop # Informational
            
             else:
                 # Already Active (Latched)
                 # Update savings info, but generally stay active unless Safety Break hits
                 self._reason = "coasting"
                 # Optional: Update stop time if it drifts significantly?
                 # Spec says: "Only recalculate if result changes > X min".
                 # For now, we update internal state for dashboard, but decision is sticky.
                 pass

