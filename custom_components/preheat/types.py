"""Type definitions for the Preheating Coordinator."""
from __future__ import annotations

from typing import TypedDict, Literal
from datetime import datetime, date

class Context(TypedDict):
    """Snapshot of the current system state."""
    # System Time
    now: datetime
    
    # Sensor Data
    operative_temp: float
    outdoor_temp: float
    valve_position: float | None
    is_occupied: bool
    is_window_open: bool
    
    # Configuration / Calendar
    target_setpoint: float
    next_event: datetime | None
    blocked_dates: set[date]
    
    # Internal Flags
    is_sensor_ready: bool
    preheat_active: bool
    
    # Optional Weather Data (None if unavailable)
    forecasts: list | None

class Prediction(TypedDict):
    """Results of the physics simulation."""
    predicted_duration: float      # Final used duration (minutes)
    uncapped_duration: float       # Theoretical duration (minutes)
    
    delta_in: float  # Target - Internal Temp
    delta_out: float # Target - External Temp (effective)
    
    prognosis: Literal["ok", "limited", "extrapolated", "fallback"]
    weather_available: bool
    limit_exceeded: bool

class Decision(TypedDict):
    """The result of the start/stop decision logic."""
    should_start: bool
    start_time: datetime | None
    effective_departure: datetime | None
    
    reason: str
    blocked_by: list[str]
    frost_override: bool
