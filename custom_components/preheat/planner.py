"""Planner module for intelligent preheating."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, date
from collections import defaultdict

from homeassistant.util import dt as dt_util

from .patterns import PatternDetector, ArrivalCluster, PatternResult
from .const import (
    DEFAULT_ARRIVAL_MIN,
    ATTR_ARRIVAL_HISTORY,
)

_LOGGER = logging.getLogger(__name__)

# v2.6 Constants
WINDOW_SIZE = 30
MIN_POINTS_FOR_V3 = 3
FULL_V3_POINTS = 10

class PreheatPlanner:
    """Manages arrival history and prediction."""

    def __init__(self, stored_history: dict | None = None) -> None:
        """Initialize."""
        self.detector = PatternDetector()
        
        # v3 History: {weekday_int: [(date, minutes), ...]}
        self.history: dict[int, list[tuple[date, int]]] = defaultdict(list)
        
        # v2 History (Legacy): {weekday_int: [minutes, ...]}
        self.history_v2: dict[int, list[int]] = defaultdict(list)
        
        self.last_pattern_result: PatternResult | None = None # For Sensor exposure
        
        if stored_history:
            self._load_history(stored_history)

    def _load_history(self, stored: dict) -> None:
        """Load history handling v2 vs v3 formats."""
        for k, v in stored.items():
            try:
                # 1. Handle "v3_X" keys (Explicit V3 Storage)
                if k.startswith("v3_"):
                    try:
                        weekday = int(k.split("_")[1])
                        # v3 format: list of [iso_date_str, int]
                        for item in v:
                            if len(item) == 2:
                                d_str, minutes = item
                                d_obj = datetime.fromisoformat(d_str).date() if isinstance(d_str, str) else d_str
                                self.history[weekday].append((d_obj, minutes))
                    except Exception:
                        pass
                    continue

                # 2. Handle "v2_X" keys (Explicit V2 Storage - Legacy from Beta)
                if k.startswith("v2_"):
                    try:
                        weekday = int(k.split("_")[1])
                        self.history_v2[weekday] = v
                    except Exception:
                        pass
                    continue

                # 3. Handle Integer keys (Standard: v2.5 Legacy OR v2.6 Beta)
                # In v2.5, this was always v2 data.
                # In v2.6 Beta 1-8, this was v3 data.
                # We interpret based on content type to be safe.
                weekday = int(k)
                if not v:
                    continue
                
                first = v[0]
                if isinstance(first, int):
                    # v2 format (Legacy 2.5): list of ints
                    self.history_v2[weekday] = v
                elif isinstance(first, list) or isinstance(first, tuple):
                    # v3 format (Beta 1-8): Migrate to v3 memory
                    for item in v:
                        if len(item) == 2:
                            d_str, minutes = item
                            d_obj = datetime.fromisoformat(d_str).date() if isinstance(d_str, str) else d_str
                            self.history[weekday].append((d_obj, minutes))
            except Exception as e:
                _LOGGER.warning("Failed to load history for weekday %s: %s", k, e)

    # ... (record_arrival and other methods remain unchanged) ...

    def record_arrival(self, dt: datetime) -> None:
        """Record a new arrival event."""
        weekday = dt.weekday()
        minutes = dt.hour * 60 + dt.minute
        
        # Update v3 History
        # Dedup: Don't add if already exists for this date
        today_entry = next((item for item in self.history[weekday] if item[0] == dt.date()), None)
        if not today_entry:
            self.history[weekday].append((dt.date(), minutes))
            
            # Rolling Window
            if len(self.history[weekday]) > WINDOW_SIZE:
                self.history[weekday] = self.history[weekday][-WINDOW_SIZE:]

        # Update v2 History (Dual Write for Downgrade Safety)
        self.history_v2[weekday].append(minutes)
        if len(self.history_v2[weekday]) > 20: # Keep v2 limit
             self.history_v2[weekday] = self.history_v2[weekday][-20:]

    # ... (get_schedule_for_today etc) ...

    def to_dict(self) -> dict:
        """Export history (Persistence)."""
        export = {}
        
        # 1. Save V2 Data to Standard Keys "0".."6"
        # This ensures v2.5 (which expects int keys) reads valid v2 data (list of ints).
        for k, v in self.history_v2.items():
            if v:
                export[str(k)] = v
                
        # 2. Save V3 Data to New Keys "v3_0".."v3_6"
        # This preserves v3 data for v2.6+ while being invisible/ignored by v2.5.
        for k, v in self.history.items():
            serializable = [(d.isoformat(), m) for d, m in v]
            export[f"v3_{k}"] = serializable
                
        return export
