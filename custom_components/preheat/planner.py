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
MIN_POINTS_FOR_V3 = 4
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
                # 1. Handle "v2_X" keys (explicit v2 storage from v2.6+)
                if k.startswith("v2_"):
                    try:
                        weekday = int(k.split("_")[1])
                        self.history_v2[weekday] = v
                    except (IndexError, ValueError):
                        pass
                    continue

                # 2. Handle Integer keys (Standard v3 OR Legacy v2.5)
                weekday = int(k)
                if not v:
                    continue
                
                # Check format of first item
                first = v[0]
                if isinstance(first, int):
                    # v2 format (Legacy 2.5): list of ints
                    self.history_v2[weekday] = v
                elif isinstance(first, list) or isinstance(first, tuple):
                    # v3 format: list of [iso_date_str, int] (from JSON)
                    for item in v:
                        if len(item) == 2:
                            d_str, minutes = item
                            # Parse date if string
                            d_obj = datetime.fromisoformat(d_str).date() if isinstance(d_str, str) else d_str
                            self.history[weekday].append((d_obj, minutes))
            except Exception as e:
                _LOGGER.warning("Failed to load history for weekday %s: %s", k, e)

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

        # Update v2 History (Keep it alive for now, or just stop specific v2 recording?
        # Concept says "Strict Dual-Read", usually implies we stop polluting old data?
        # But if we rely on "Gradual Transition", having v2 data for fallback is good.
        # Let's keep recording v2 to ensure fallback works if v3 fails or during transition.
        self.history_v2[weekday].append(minutes)
        if len(self.history_v2[weekday]) > 20: # Keep v2 limit
             self.history_v2[weekday] = self.history_v2[weekday][-20:]

    def get_schedule_for_today(self, now: datetime, is_holiday: bool = False) -> list[datetime]:
        """
        Get list of predicted arrival times for the rest of the day.
        Legacy-like wrapper, might need to use v3 logic?
        For simplicity in v2.6, let's delegate to get_next_scheduled_event logic per day?
        Or stick to simpler clustering for "List of events".
        """
        # ... logic similar to previous but using `_get_events_for_day` helper ...
        # Simplified for brevity/correctness using the new detector on today's data?
        # Actually `get_schedule_for_today` is rarely used if `get_next_scheduled_event` covers it.
        # But let's implement it robustly.
        
        events = []
        # This function is used for specific "Today" check.
        # Let's try to be consistent with `get_next_scheduled_event` logic:
        # If we have v3 data, we should use v3 prediction.
        # BUT v3 predicts ONE "Mode" usually.
        # If today has passed that mode, what then?
        
        # Fallback to simple clustering for now to show "potential events"
        # Using v2 history for broad overview is safer for "List of Events".
        # v3 is very specific about "Next Prediction".
        weekday = now.weekday()
        if is_holiday and weekday < 5:
            weekday = 6
            
        # Use v2 logic for general schedule view (multimodal list)
        # Because v3 is focused on "Primary Prediction".
        timestamps = self.history_v2.get(weekday, [])
        if not timestamps and weekday in self.history:
             # Create v2-like timestamps from v3 if clean v2 missing
             timestamps = [m for _, m in self.history[weekday]]
             
        if not timestamps:
            return []

        clusters = self.detector.find_clusters_v2(timestamps)
        today = now.date()
        
        for c in clusters:
            event_dt = datetime.combine(today, datetime.min.time()) + timedelta(minutes=c.time_minutes)
            event_dt = event_dt.replace(tzinfo=now.tzinfo)
            if event_dt > now:
                events.append(event_dt)
        events.sort()
        return events

    def get_next_scheduled_event(self, now: datetime, allowed_weekdays: list[int] | None = None) -> datetime | None:
        """
        Get the very next event (Lookahead up to 7 days).
        Implements v3 Migration Logic.
        """
        today_date = now.date()
        self.last_pattern_result = None # Reset
        
        for day_offset in range(8):
            check_date = today_date + timedelta(days=day_offset)
            weekday = check_date.weekday()
            
            if allowed_weekdays is not None and weekday not in allowed_weekdays:
                continue

            # --- PREDICTION LOGIC ---
            v3_data = self.history.get(weekday, [])
            v2_data = self.history_v2.get(weekday, [])
            
            # Use v2 data as backup if v3 missing effectively
            if not v3_data and not v2_data:
                continue
                
            prediction_minute: int | None = None
            
            v3_count = len(v3_data)
            
            # LOGIC START
            if v3_count < MIN_POINTS_FOR_V3:
                # Phase 1: Pure v2
                prediction_minute = self._predict_v2(v2_data)
                
            elif v3_count < FULL_V3_POINTS:
                # Phase 2: Hybrid Blending
                v2_min = self._predict_v2(v2_data)
                v3_res = self.detector.predict(v3_data, check_date)
                
                # Store result for inspection (even if blending)
                if day_offset == 0: # Only store for nearest event to avoid overwrite?
                     # Actually we want the result for the *found* event.
                     self.last_pattern_result = v3_res
                
                if v2_min is not None and v3_res.prediction_time is not None:
                    weight = (v3_count - MIN_POINTS_FOR_V3) / (FULL_V3_POINTS - MIN_POINTS_FOR_V3)
                    # Blended
                    prediction_minute = int(v2_min * (1 - weight) + v3_res.prediction_time * weight)
                elif v3_res.prediction_time is not None:
                     prediction_minute = v3_res.prediction_time
                else:
                     prediction_minute = v2_min

            else:
                # Phase 3: Pure v3
                v3_res = self.detector.predict(v3_data, check_date)
                self.last_pattern_result = v3_res
                prediction_minute = v3_res.prediction_time
            
            # --- END LOGIC ---

            if prediction_minute is None:
                continue
                
            event_dt = datetime.combine(check_date, datetime.min.time()) + timedelta(minutes=prediction_minute)
            event_dt = event_dt.replace(tzinfo=now.tzinfo)
            
            if event_dt > now:
                return event_dt
                
        return None

    def _predict_v2(self, timestamps: list[int]) -> int | None:
        """Legacy helper: Earliest cluster."""
        if not timestamps:
            return None
        clusters = self.detector.find_clusters_v2(timestamps)
        if not clusters:
            return None
        return min(c.time_minutes for c in clusters)

    def get_schedule_summary(self) -> dict[str, str]:
        """Get a human readable summary of learned times per weekday."""
        summary = {}
        weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i in range(7):
            # Prefer v3 data for summary
            v3_data = self.history.get(i, [])
            if v3_data:
                # Convert to minutes for simple clustering display
                mins = [m for _, m in v3_data]
                clusters = self.detector.find_clusters_v2(mins)
            else:
                v2_data = self.history_v2.get(i, [])
                clusters = self.detector.find_clusters_v2(v2_data)
                
            if not clusters:
                summary[weekdays[i]] = "-"
            else:
                times = []
                for c in clusters:
                    h = c.time_minutes // 60
                    m = c.time_minutes % 60
                    times.append(f"{h:02d}:{m:02d}")
                summary[weekdays[i]] = ", ".join(times)
        return summary

    def to_dict(self) -> dict:
        """Export history (Persistence)."""
        # Concept: Persist both? Or migrate V2 to V3 on save?
        # We need to save v2 for the transition period.
        # But we can't save two dicts easily in current architecture which expects one dict?
        # Wait, the coordinator loads `stored_history`.
        # `to_dict` returns the dict that gets saved.
        # If I return just `self.history`, I lose v2 data.
        # If I return merged... `_load_history` handles parsing.
        # I can merge them: v2 ints and v3 tuples in same list?
        # `_load_history` already supports checking type Item-by-Item!
        # "first = v[0]" check might be too simple if mixed.
        # Let's save them separately or just append?
        # Cleaner: Since `check_format` looks at first item, we shouldn't mix types in one list.
        # Let's merge disjointly? 
        # Actually, if we are in Phase 2/3, we care about V3.
        # If we are in Phase 1, we care about V2.
        # Let's try to migrate fully to V3 storage format eventually.
        # But for now, let's just save `self.history` (V3) and if V3 is empty/small, maybe we should also validly convert V2 to V3?
        # NO, "Data Migration: Avoid polluting new data structures with old".
        # So we MUST store them disjointly.
        # HACK: Store v2 as negative keys? No.
        # HACK: Store v3 normally. Store v2 in keys 100+? No.
        # PROPER: Change `to_dict` to return a structure `{'v3': ..., 'v2': ...}`?
        # This would break `_load_history` if it expects `{0: [], 1: ...}`.
        # But I control `_load_history`.
        # Existing `stored_history` is `{ "0": [1,2], ...}`.
        # If I change structure, I break older versions if user rolls back.
        # ROLLBACK SAFETY:
        # If I create `custom_components/preheat/planner.py`, I can't easily change the JSON structure root without logic.
        # Strategy:
        # Save V3 in keys `0..6`.
        # Save V2 in keys `"v2_0".."v2_6"`?
        # `_load_history` typically iterates keys.
        # If I assume `try: int(k)` in load, string keys are skipped/fail.
        # My `_load_history` has `try: weekday = int(k)`.
        # So if I save v2 in non-int keys, old version will ignore them (Safe!).
        # And my new version can read them.
        
        export = {}
        # Save V3 (Primary)
        for k, v in self.history.items():
            # v is list of tuples (date, int). JSON needs list of list.
            # date -> isoformat
            serializable = [(d.isoformat(), m) for d, m in v]
            export[str(k)] = serializable
            
        # Save V2 (Secondary) -> Keys "v2_0"
        for k, v in self.history_v2.items():
            if v:
                export[f"v2_{k}"] = v
                
        return export
