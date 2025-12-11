"""History buffer and analysis for V3 deadtime detection."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Tuple, Optional

_LOGGER = logging.getLogger(__name__)

@dataclass
class HistoryPoint:
    timestamp: float # Unix timestamp
    temp: float
    valve: float # 0-100 or 0-1 if binary
    is_active: bool # Preheat active state

class RingBuffer:
    """Fixed-size buffer for historical data."""
    def __init__(self, capacity: int = 360) -> None:
        self.capacity = capacity
        self._buffer: List[HistoryPoint] = []

    def append(self, point: HistoryPoint) -> None:
        self._buffer.append(point)
        if len(self._buffer) > self.capacity:
            self._buffer.pop(0)

    def get_all(self) -> List[HistoryPoint]:
        return list(self._buffer)
    
    def clear(self) -> None:
        self._buffer.clear()

    def get_average_valve(self, start_ts: float, end_ts: float) -> float | None:
        """Calculate average valve position within the time window."""
        total = 0.0
        count = 0
        for p in self._buffer:
            if start_ts <= p.timestamp <= end_ts:
                total += p.valve
                count += 1
        
        return (total / count) if count > 0 else None

class DeadtimeAnalyzer:
    """Analyzes heating curves to find deadtime (Totzeit)."""

    def analyze(self, data: List[HistoryPoint]) -> Optional[float]:
        """
        Analyze the buffer to find the deadtime.
        Returns deadtime in minutes, or None if detection failed.
        """
        if not data or len(data) < 15:
            return None

        # 1. Find Start Event (T0)
        # Look for the last transition from Inactive -> Active
        start_idx = -1
        for i in range(len(data) - 1, 0, -1):
            if data[i].is_active and not data[i-1].is_active:
                start_idx = i
                break
        
        if start_idx == -1:
            return None # No start event found in buffer

        t_start = data[start_idx].timestamp
        start_temp = data[start_idx].temp
        
        # 2. Extract curve AFTER start
        # We need enough data after start to find the reaction
        relevant_data = data[start_idx:]
        if len(relevant_data) < 15: # Need at least 15 mins of data
            return None

        # 3. Find Max Gradient (Inflection Point)
        # We calculate the slope over a rolling window (e.g., 10 mins) to smooth noise
        window = 10 
        max_slope = 0.0
        max_slope_time = 0.0
        max_slope_temp = 0.0
        
        # Simple finite difference over 'window' size
        for i in range(window, len(relevant_data)):
            p_now = relevant_data[i]
            p_prev = relevant_data[i-window]
            
            dt = (p_now.timestamp - p_prev.timestamp) / 60.0 # Delta time in mins
            if dt < 1.0: continue

            d_temp = p_now.temp - p_prev.temp
            slope = d_temp / dt # K/min

            if slope > max_slope:
                max_slope = slope
                max_slope_time = p_now.timestamp
                max_slope_temp = p_now.temp

        # Validation: Is the slope significant?
        # > 0.1 K per hour = 0.0016 K/min. Let's say > 0.05 K / 10min = 0.005 K/min
        if max_slope < 0.005: 
            _LOGGER.debug("Slope too shallow for detection: %.4f K/min", max_slope)
            return None 

        # t_intersect = ((start_temp - max_slope_temp) / max_slope) + max_slope_time
        # Correction: slope is K/min. ((T - T) / (K/min)) = min.
        # Timestamps are seconds. Must convert result to seconds.
        
        time_shift_minutes = (start_temp - max_slope_temp) / max_slope
        t_intersect = max_slope_time + (time_shift_minutes * 60.0)
        
        deadtime_seconds = t_intersect - t_start
        deadtime_minutes = deadtime_seconds / 60.0
        
        # Sanity Check
        
        # Sanity Check
        if deadtime_minutes < 0 or deadtime_minutes > 480:
            return None

        return deadtime_minutes
