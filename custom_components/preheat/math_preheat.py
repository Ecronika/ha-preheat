"""Math helper functions for forecast integration."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
import logging
from datetime import datetime, timedelta
# import numpy as np # Avoid heavy dependency
import math
from typing import Callable

from .const import RISK_BALANCED, RISK_PESSIMISTIC, RISK_OPTIMISTIC

_LOGGER = logging.getLogger(__name__)

def integrate_forecast(forecasts: list[dict], start_dt: datetime, end_dt: datetime) -> float:
    """
    Calculate time-weighted average temperature using Trapezoidal Rule.
    
    Args:
        forecasts: List of dicts {'datetime': dt (aware), 'temperature': float}
        start_dt, end_dt: Window boundaries (must be aware and same TZ as forecasts).
        
    Returns:
        float: Weighted average temperature.
    """
    if start_dt >= end_dt:
        return 0.0

    # 1. Filter and Pad Forecast Points
    sorted_fc = sorted(forecasts, key=lambda x: x["datetime"])
    
    # We need points surrounding the window
    relevant_points = []
    
    # Add Start Point (Linear Interpolation)
    start_temp = _interpolate(sorted_fc, start_dt)
    relevant_points.append({"datetime": start_dt, "temperature": start_temp})
    
    # Add points strictly inside window
    for pt in sorted_fc:
        if start_dt < pt["datetime"] < end_dt:
            relevant_points.append(pt)
            
    # Add End Point (Linear Interpolation)
    end_temp = _interpolate(sorted_fc, end_dt)
    relevant_points.append({"datetime": end_dt, "temperature": end_temp})
    
    # 2. Trapezoidal Integration
    total_area_kelvin_seconds = 0.0
    total_seconds = (end_dt - start_dt).total_seconds()
    
    if total_seconds <= 0: return start_temp # Fallback
    
    for i in range(len(relevant_points) - 1):
        p1 = relevant_points[i]
        p2 = relevant_points[i+1]
        
        dt_sec = (p2["datetime"] - p1["datetime"]).total_seconds()
        avg_temp = (p1["temperature"] + p2["temperature"]) / 2.0
        
        total_area_kelvin_seconds += avg_temp * dt_sec
        
    return total_area_kelvin_seconds / total_seconds

def _interpolate(forecasts: list[dict], target_dt: datetime) -> float:
    """Linearly interpolate temperature at exact timestamp."""
    # Handle empty/single
    if not forecasts: return 0.0
    if len(forecasts) == 1: return forecasts[0]["temperature"]
    
    # Check boundaries
    if target_dt <= forecasts[0]["datetime"]: return forecasts[0]["temperature"]
    if target_dt >= forecasts[-1]["datetime"]: return forecasts[-1]["temperature"]
    
    # Find bracket
    for i in range(len(forecasts) - 1):
        p1 = forecasts[i]
        p2 = forecasts[i+1]
        if p1["datetime"] <= target_dt <= p2["datetime"]:
            # Interpolate
            t1 = p1["datetime"].timestamp()
            t2 = p2["datetime"].timestamp()
            target_ts = target_dt.timestamp()
            
            fraction = (target_ts - t1) / (t2 - t1) if (t2-t1) > 0 else 0
            return p1["temperature"] + fraction * (p2["temperature"] - p1["temperature"])
            
    return forecasts[-1]["temperature"] # Should not happen

def resample_curve(forecasts: list[dict], start_dt: datetime, end_dt: datetime, step_seconds: int = 300) -> list[float]:
    """Resample forecast curve to uniform grid."""
    if start_dt >= end_dt: return []
    
    duration = (end_dt - start_dt).total_seconds()
    steps = int(duration / step_seconds)
    if steps < 1: steps = 1
    
    samples = []
    current_dt = start_dt
    
    for _ in range(steps):
        temp = _interpolate(forecasts, current_dt)
        samples.append(temp)
        current_dt += timedelta(seconds=step_seconds)
        
    return samples

def calculate_risk_metric(forecasts: list[dict], start_dt: datetime, end_dt: datetime, mode: str) -> float:
    """Calculate effective outdoor temp based on risk mode."""
    if mode == RISK_BALANCED:
        return integrate_forecast(forecasts, start_dt, end_dt)
    
    # Resampling for Percentiles
    samples = resample_curve(forecasts, start_dt, end_dt)
    if not samples: return integrate_forecast(forecasts, start_dt, end_dt) # Fallback
    
    if mode == RISK_PESSIMISTIC:
        # P10 (Coldest 10%) -> Prioritize comfort
        return _percentile(samples, 10)
        
    if mode == RISK_OPTIMISTIC:
        # P90 (Warmest 10%) -> Prioritize savings
        return _percentile(samples, 90)
        
    return integrate_forecast(forecasts, start_dt, end_dt)

def _percentile(data: list[float], percentile: float) -> float:
    """Calculate percentile (0-100) of list."""
    if not data: return 0.0
    data.sort()
    index = (percentile / 100) * (len(data) - 1)
    
    # Linear interpolation between closest ranks
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    
    if lower == upper: return data[lower]
    
    fraction = index - lower
    return data[lower] * (1 - fraction) + data[upper] * fraction

def solve_duration(
    calc_func: Callable[[float], float], 
    target_date: datetime,
    max_hours: float
) -> float:
    """
    Find preheat duration 'd' such that:
    Duration(AverageTemp(d)) - d = 0
    
    Args:
        calc_func: Lambda(avg_temp) -> calculates required duration based on physics model.
        target_date: DateTime of arrival.
        max_hours: Max search horizon in hours.
        
    Returns:
        float: Duration in minutes.
    """
    
    # Function to zero: g(d) = calculated_duration(d) - d
    forecast_provider = calc_func # Actually passed calc_func is partial logic, we need the full injection
    # Wait, simple design:
    # We pass a callback that accepts duration (minutes) and returns 'g(d)'.
    # This keeps math_preheat agnostic of physics/weather interactions.
    pass

# Redesign solve_duration signature to be cleaner
def root_find_duration(
    eval_func: Callable[[float], float], 
    max_minutes: int
) -> float:
    """
    Solve for d where eval_func(d) <= 0 using Grid Search + Bisection.
    
    Args:
        eval_func: Function accepting duration (min) and returning (CalculatedDuration - duration).
                   Positive means "Need more time". Negative means "Have enough time".
        max_minutes: Horizon limit.
    """
    step = 5 # minutes
    
    # 1. Grid Search (Best Bracket)
    # We look for the FIRST crossover from Positive to Negative (or Zero).
    # This implies we found a duration 'd' that is sufficient.
    
    best_bracket = None # (d_prev, d_curr)
    
    prev_val = eval_func(0)
    if prev_val <= 0:
        return 0.0 # 0 minutes is already enough (too warm)
        
    for d in range(step, max_minutes + step, step):
        val = eval_func(float(d))
        
        if val <= 0:
            # Crossed zero!
            best_bracket = (float(d - step), float(d))
            break
        
        prev_val = val
        
    # 2. Fallback / Bisection
    if not best_bracket:
        # Never crossed zero. We need max duration.
        # But wait, maybe the 'min abs error' was somewhere?
        # If monotonic increasing demand vs supplied, it should cross if max_minutes is huge.
        # If we hit max_minutes and still positive, return max.
        return float(max_minutes)
        
    # 3. Bisection
    low, high = best_bracket
    for _ in range(10): # 10 iterations -> precision ~0.01 min
        mid = (low + high) / 2
        val = eval_func(mid)
        
        if val <= 0:
            high = mid # Try smaller duration
        else:
            low = mid # Need more duration
            
    return high # Safer to return high (guaranteed sufficient) or mid? High is safe comfort wise.

def calculate_coast_duration(
    t_start: float,
    t_floor: float,
    t_out_eff: float,
    tau_hours: float,
    max_minutes: float = 240.0
) -> float:
    """
    Calculate how long (in minutes) it takes to cool down to t_floor.
    
    Formula: t = -tau * ln( (T_floor - T_out) / (T_start - T_out) )
    
    Args:
        t_start: Current indoor temperature.
        t_floor: Target floor temperature (Target - Tolerance).
        t_out_eff: Effective outdoor temperature (Sink).
        tau_hours: Thermal Time Constant in hours.
        max_minutes: Cap for the result.
        
    Returns:
        float: Duration in minutes (0.0 if not possible or too slow).
    """
    # 1. Edge Case: Already too cold
    if t_start <= t_floor:
        return 0.0
        
    # 2. Edge Case: Warm Outside (Short-Circuit)
    # If outside is warmer than (Floor - 2.0), cooling is extremely slow/impossible via transmission.
    if t_out_eff >= (t_floor - 2.0):
        return 0.0
        
    # 3. Physics Check (Log Domain)
    # We need (T_floor - T_out) > 0 and (T_start - T_out) > 0.
    # From checks 1 & 2, we know T_start > T_floor > T_out.
    # So numerator and denominator are positive.
    
    numerator = t_floor - t_out_eff
    denominator = t_start - t_out_eff
    
    if denominator == 0: return 0.0 # Should not happen due to checks, but safety.
    
    ratio = numerator / denominator
    if ratio <= 0: return 0.0 # Math domain error protection
    
    # 4. Calculation
    # result in hours = -tau * ln(ratio)
    hours = -tau_hours * math.log(ratio)
    minutes = hours * 60.0
    
    # 5. Clamping
    if minutes < 0: return 0.0
    if minutes > max_minutes: return max_minutes
    
    return minutes

def calc_forecast_mean_or_p90_placeholder(forecasts: list[dict], start_dt: datetime, end_dt: datetime) -> float:
    """
    Helper to get effective T_out for Coasting.
    Uses 'Balanced' (Mean) logic by default as spec requests.
    """
    return integrate_forecast(forecasts, start_dt, end_dt)
