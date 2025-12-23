"""Providers for Session End interactions."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ENABLE_OPTIMAL_STOP,
    CONF_STOP_TOLERANCE,
    CONF_MAX_COAST_HOURS,
    CONF_SCHEDULE_ENTITY,
    DEFAULT_STOP_TOLERANCE,
    DEFAULT_MAX_COAST_HOURS,
    
    GATE_MIN_SAVINGS_MIN,
    GATE_MIN_TAU_CONF,
    GATE_MIN_PATTERN_CONF,
    
    REASON_UNAVAILABLE,
    REASON_OFF,
    REASON_NO_NEXT_EVENT,
    REASON_PARSE_ERROR,
    REASON_LOW_CONFIDENCE,
    REASON_BLOCKED_BY_GATES,
    REASON_INSUFFICIENT_SESSIONS,
    
    GATE_FAIL_SAVINGS,
    GATE_FAIL_TAU,
    GATE_FAIL_PATTERN,
    GATE_FAIL_LATCH,
)

from .optimal_stop import OptimalStopManager, SessionResolver
from .planner import PreheatPlanner
from .math_preheat import calculate_risk_metric  # Helper for forecast

_LOGGER = logging.getLogger(__name__)

@dataclass
class ProviderDecision:
    """Standardized output from a SessionEndProvider."""
    should_stop: bool
    session_end: datetime | None
    is_valid: bool
    is_shadow: bool
    
    # Metadata
    confidence: float | None = None
    predicted_savings: float | None = None
    invalid_reason: str | None = None
    gates_failed: list[str] = field(default_factory=list)
    gate_inputs: dict[str, Any] = field(default_factory=dict)
    
class SessionEndProvider(ABC):
    """Abstract Base Class for Session End Providers."""
    
    @abstractmethod
    def get_decision(self, context: dict[str, Any]) -> ProviderDecision:
        """Calculate and return the session end decision."""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return provider name."""
        pass

class ScheduleProvider(SessionEndProvider):
    """
    Wraps the legacy Schedule Entity + Optimal Stop logic.
    Ensures strict adherence to existing behavior (Hard Override).
    """
    
    def __init__(self, hass: HomeAssistant, config_entry: Any, optimal_stop_manager: OptimalStopManager):
        self.hass = hass
        self.entry = config_entry
        self.manager = optimal_stop_manager
        self.session_resolver = None # Lazy init

    @property
    def name(self) -> str:
        return "schedule"

    def _get_conf(self, key: str, default: Any = None) -> Any:
        # Helper to access options/config
        if key in self.entry.options: return self.entry.options[key]
        if key in self.entry.data: return self.entry.data[key]
        return default

    def _update_manager_passive(self, context: dict[str, Any]) -> None:
        """Update manager with 'No Session' to trigger resets."""
        if not self._get_conf(CONF_ENABLE_OPTIMAL_STOP, False):
            return
            
        # Minimal config for reset
        opt_config = {
             CONF_STOP_TOLERANCE: self._get_conf(CONF_STOP_TOLERANCE, DEFAULT_STOP_TOLERANCE),
             CONF_MAX_COAST_HOURS: self._get_conf(CONF_MAX_COAST_HOURS, DEFAULT_MAX_COAST_HOURS),
             "system_inertia": 0.0
        }
        
        # Dummy forecast provider
        def _dummy_cb(s, e): return 10.0

        self.manager.update(
            current_temp=context["operative_temp"],
            target_temp=context["target_setpoint"],
            schedule_end=None, # Explicitly NONE to trigger reset
            forecast_provider=_dummy_cb,
            tau_hours=context["tau_hours"],
            config=opt_config
        )

    def get_decision(self, context: dict[str, Any]) -> ProviderDecision:
        """
        Context must contain:
        - now: datetime
        - operative_temp: float
        - target_setpoint: float
        - forecasts: list | None
        - tau_hours: float
        - physics_deadtime: float
        """
        now = context["now"]
        sched_entity = self._get_conf(CONF_SCHEDULE_ENTITY)
        
        # 1. Validity Checks (Legacy Match)
        if not sched_entity:
            return ProviderDecision(False, None, False, False, invalid_reason=REASON_UNAVAILABLE)
            
        state = self.hass.states.get(sched_entity)
        if not state or state.state == "unavailable":
            self._update_manager_passive(context)
            return ProviderDecision(False, None, False, False, invalid_reason=REASON_UNAVAILABLE)
        
        if state.state != "on":
             # Legacy: If schedule is OFF, we are not in a session.
             # Ensure Optimal Stop Manager sees the "OFF" state to reset latches
             self._update_manager_passive(context)
             return ProviderDecision(False, None, False, False, invalid_reason=REASON_OFF)

        # 2. Resolve Session End
        if not self.session_resolver or self.session_resolver._entity_id != sched_entity:
            self.session_resolver = SessionResolver(self.hass, sched_entity)
            
        session_end = self.session_resolver.get_current_session_end()
        
        if not session_end:
             return ProviderDecision(False, None, False, False, invalid_reason=REASON_NO_NEXT_EVENT)
             
        # 3. Optimal Stop Logic (Should we stop early?)
        should_stop = False
        savings = 0.0
        reason = None
        
        if self._get_conf(CONF_ENABLE_OPTIMAL_STOP, False):
            # Prepare config for manager
            opt_config = {
                 CONF_STOP_TOLERANCE: self._get_conf(CONF_STOP_TOLERANCE, DEFAULT_STOP_TOLERANCE),
                 CONF_MAX_COAST_HOURS: self._get_conf(CONF_MAX_COAST_HOURS, DEFAULT_MAX_COAST_HOURS),
                 "system_inertia": context.get("physics_deadtime", 0.0)
            }
            
            # Helper for forecast callback
            forecasts = context.get("forecasts")
            def _forecast_cb(s, e):
                if forecasts:
                    # Risk mode assumed balanced or passed in context
                    return calculate_risk_metric(forecasts, s, e, "balanced")
                return context.get("outdoor_temp", 10.0)

            self.manager.update(
                current_temp=context["operative_temp"],
                target_temp=context["target_setpoint"],
                schedule_end=session_end,
                forecast_provider=_forecast_cb,
                tau_hours=context["tau_hours"],
                config=opt_config
            )
            
            should_stop = self.manager.is_active
            savings = self.manager._savings_remaining # Remaining potential
            if should_stop:
                reason = "optimal_stop"
        
        # Construct decision
        return ProviderDecision(
            should_stop=should_stop,
            session_end=session_end,
            is_valid=True,
            is_shadow=False, # Schedule is never shadow
            predicted_savings=savings,
            invalid_reason=reason # Optional info
        )


class LearnedDepartureProvider(SessionEndProvider):
    """
    Shadow Mode Provider.
    Predicts session end based on historical patterns.
    Checks Safety Gates.
    """
    def __init__(self, planner: PreheatPlanner, system_params: dict):
        self.planner = planner
        self.params = system_params # thresholds

    @property
    def name(self) -> str:
        return "learned"

    def get_decision(self, context: dict[str, Any]) -> ProviderDecision:
        # 1. Get Prediction
        # In v2.7 (Foundations), we do not yet predict departure times autonomously.
        # This phase focuses on metrics collection ("Shadow Mode") and safety gate validation.
        # Future (v3.0): Implement "Smart Departure" clustering to predict session length.
        
        # For now, we return a "Not Ready" decision but populate the trace with
        # gate results so the user can see what *would* happen if data were sufficient.
        
        gates_failed = []
        gate_inputs = {}
        
        # Extract Inputs
        savings = context.get("potential_savings", 0.0) # From Sim/Calc
        tau_conf = context.get("tau_confidence", 0.0)
        pattern_conf = context.get("pattern_confidence", 0.0)
        
        # Get Session Count (Arrivals as proxy for maturity)
        weekday = context["now"].weekday()
        # History is {weekday: [(date, min), ...]}
        sessions = self.planner.history.get(weekday, [])
        session_count = len(sessions)
        
        gate_inputs = {
            "savings": savings,
            "tau_conf": tau_conf,
            "pattern_conf": pattern_conf,
            "session_count": session_count
        }
        
        if savings < GATE_MIN_SAVINGS_MIN:
            gates_failed.append(GATE_FAIL_SAVINGS)
            
        if tau_conf < GATE_MIN_TAU_CONF:
            gates_failed.append(GATE_FAIL_TAU)
            
        if pattern_conf < GATE_MIN_PATTERN_CONF:
             gates_failed.append(GATE_FAIL_PATTERN)
             
        # If we had a prediction...
        predicted_end = None # TODO: Implement clustering query
        
        valid = (len(gates_failed) == 0) and (predicted_end is not None)
            
        return ProviderDecision(
            should_stop=False, # Always False for now as we have no prediction
            session_end=None,
            is_valid=valid,
            is_shadow=True,
            confidence=pattern_conf,
            predicted_savings=savings,
            gates_failed=gates_failed,
            gate_inputs=gate_inputs,
            invalid_reason=REASON_INSUFFICIENT_SESSIONS if not valid else None
        )
