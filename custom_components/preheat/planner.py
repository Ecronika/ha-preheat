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

        # v2.8 Departure History: {weekday_int: [{"date": iso_date, "minutes": int, "dst_flag": bool}, ...]}
        self.history_departure: dict[int, list[dict]] = defaultdict(list)
        
        # v2 History (Legacy): {weekday_int: [minutes, ...]}
        self.history_v2: dict[int, list[int]] = defaultdict(list)
        
        self.last_pattern_result: PatternResult | None = None # For Sensor exposure
        
        if stored_history:
            self._load_history(stored_history)

    def _load_history(self, stored: dict) -> None:
        """Load history handling v2 vs v3 formats."""
        for k, v in stored.items():
            try:
                # 1. Handle Special Container Key "999" (v3 Data Safe Storage)
                # We use an integer key so older versions (which might run `int(k)`) don't crash.
                # They will just load this garbage data into `history[999]` and ignore it (looping 0-6).
                if k == "999" and isinstance(v, dict):
                    self._load_v3_container(v)
                    continue

                if k == "888" and isinstance(v, dict):
                    self._load_departure_container(v)
                    continue

                # 2. Legacy: Handle "v3_X" keys (from Beta 10, deprecated but supported for migration)
                if k.startswith("v3_"):
                    self._parse_v3_item(k, v)
                    continue

                # 3. Legacy: Handle "v2_X" keys (from Beta 10/Beta 1-8 leftovers)
                if k.startswith("v2_"):
                    try:
                        weekday = int(k.split("_")[1])
                        self.history_v2[weekday] = v
                    except Exception:
                        pass
                    continue

                # 4. Standard Integer Keys (The universal payload)
                # In v2.5/2.4/2.2: This is observed history (lists of ints).
                # In v2.6: We dual-write v2 data here for downgrade safety.
                weekday = int(k)
                if not v:
                    continue
                
                first = v[0]
                if isinstance(first, int):
                    self.history_v2[weekday] = v
                elif isinstance(first, list) or isinstance(first, tuple):
                    # Direct v3 storage (Beta 1-pre-10)
                    self._parse_v3_list(weekday, v)

            except Exception as e:
                _LOGGER.warning("Failed to load history for weekday %s: %s", k, e)
                
        # Global Maintenance on Startup
        self.prune_all_history()

    def _load_v3_container(self, container: dict) -> None:
        """Unpack v3 data from the safe container."""
        for k, v in container.items():
            try:
                weekday = int(k)
                self._parse_v3_list(weekday, v)
            except Exception:
                pass

    def _load_departure_container(self, container: dict) -> None:
        """Unpack departure history (v2.8)."""
        for k, v in container.items():
            try:
                weekday = int(k)
                if isinstance(v, list):
                    # Validate dict structure if needed, but trust input mostly
                    self.history_departure[weekday] = v
            except Exception:
                pass

    def _parse_v3_item(self, k: str, v: list) -> None:
        try:
            weekday = int(k.split("_")[1])
            self._parse_v3_list(weekday, v)
        except Exception:
            pass

    def _parse_v3_list(self, weekday: int, data: list) -> None:
        for item in data:
            if len(item) == 2:
                d_str, minutes = item
                d_obj = datetime.fromisoformat(d_str).date() if isinstance(d_str, str) else d_str
                self.history[weekday].append((d_obj, minutes))

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

    def record_departure(self, dt: datetime, max_age_days: int = 60, max_entries: int = 10) -> None:
        """Video Recorder for Departures (v2.8)."""
        dt_local = dt_util.as_local(dt)
        weekday = dt_local.weekday()
        minutes = dt_local.hour * 60 + dt_local.minute
        today_date = dt_local.date()
        date_iso = today_date.isoformat()
        
        # 1. DST Detection
        # Compare Timezone Offset of Today 03:00 vs Yesterday 03:00
        # If diff -> DST Switch Night
        dst_flag = False
        try:
            today_3am = datetime.combine(today_date, datetime.min.time()) + timedelta(hours=3)
            today_3am = today_3am.replace(tzinfo=dt_local.tzinfo)
            yesterday_3am = today_3am - timedelta(days=1)
            
            if today_3am.utcoffset() != yesterday_3am.utcoffset():
                dst_flag = True
                _LOGGER.info("DST Switch Detected for %s. Flagging departure.", date_iso)
        except Exception:
            pass # Fallback safe
            
        # 2. Add New Entry
        # Dedup by date:
        # BETA 1 LIMITATION: We only record 1 departure per day (the first one that sticks).
        # This simplifies storage but misses multi-session days. Improving this requires a full Session ID concept (v3.0).
        existing = next((x for x in self.history_departure[weekday] if x["date"] == date_iso), None)
        if not existing:
            entry = {
                "date": date_iso,
                "minutes": minutes,
                "dst_flag": dst_flag
            }
            self.history_departure[weekday].append(entry)
            
            # 3. Pruning (Age First)
            cutoff_date = (today_date - timedelta(days=max_age_days)).isoformat()
            self.history_departure[weekday] = [
                x for x in self.history_departure[weekday] 
                if x["date"] > cutoff_date
            ]
            
            # 4. Pruning (Count Second - FIFO)
            if len(self.history_departure[weekday]) > max_entries:
                self.history_departure[weekday] = self.history_departure[weekday][-max_entries:]

    def prune_all_history(self, max_age_days: int = 60, max_entries: int = 10) -> None:
        """Global Pruning for all weekdays (Startup Maintenance)."""
        today_date = dt_util.now().date()
        cutoff_date = (today_date - timedelta(days=max_age_days)).isoformat()
        
        for weekday in list(self.history_departure.keys()): # Safe iteration
            # 1. Age
            self.history_departure[weekday] = [
                x for x in self.history_departure[weekday] 
                if x["date"] > cutoff_date
            ]
            
            # 2. Count
            if len(self.history_departure[weekday]) > max_entries:
                self.history_departure[weekday] = self.history_departure[weekday][-max_entries:]

    def get_schedule_for_today(self, now: datetime, is_holiday: bool = False) -> list[datetime]:
        """
        Get list of predicted arrival times for the rest of the day.
        Legacy-like wrapper.
        """
        events = []
        weekday = now.weekday()
        if is_holiday and weekday < 5:
            weekday = 6
            
        # Use v2 logic for general schedule view (multimodal list)
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

    def get_next_scheduled_event(self, now: datetime, allowed_weekdays: list[int] | None = None, blocked_dates: set[date] | None = None) -> datetime | None:
        """
        Get the very next event (Lookahead up to 7 days).
        Implements v3 Migration Logic.
        """
        today_date = now.date()
        self.last_pattern_result = None # Reset
        
        for day_offset in range(8):
            check_date = today_date + timedelta(days=day_offset)
            weekday = check_date.weekday()
            
            # 1. Blocked Dates (Holidays from Calendar)
            if blocked_dates and check_date in blocked_dates:
                 continue

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
                
                # Setup legacy result for Sensor
                if prediction_minute is not None:
                     # Create a dummy result to show something
                     self.last_pattern_result = PatternResult(
                         prediction="legacy",
                         prediction_time=prediction_minute,
                         pattern_type="legacy_v2",
                         confidence=1.0, # Legacy is trusted by default
                         fallback_used=True,
                         modes_found={"legacy": 1}
                     )
                
            elif v3_count < FULL_V3_POINTS:
                # Phase 2: Hybrid Blending
                v2_min = self._predict_v2(v2_data)
                v3_res = self.detector.predict(v3_data, check_date)
                
                # Store result for inspection (even if blending)
                if v3_res.prediction != "insufficient_data":
                     self.last_pattern_result = v3_res
                elif v2_min is not None:
                     # Fallback to legacy metadata if v3 failed pattern check
                      self.last_pattern_result = PatternResult(
                         prediction="legacy_blended",
                         prediction_time=v2_min,
                         pattern_type="legacy_v2",
                         confidence=0.5,
                         fallback_used=True
                     )

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
            # Prefer v3 data for summary ONLY if sufficient points
            v3_data = self.history.get(i, [])
            
            # Check sufficiency
            clusters = []
            if len(v3_data) >= MIN_POINTS_FOR_V3:
                # Convert to minutes for simple clustering display
                mins = [m for _, m in v3_data]
                clusters = self.detector.find_clusters_v2(mins)
            
            # Fallback to v2 if v3 insufficient or yielded no clusters (noise)
            if not clusters:
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
        export = {}
        
        # 1. Save V2 Data to Standard Keys "0".."6"
        # Compatible with v2.5, v2.4, v2.2 (Expect Integer Keys -> List of Ints)
        for k, v in self.history_v2.items():
            if v:
                export[str(k)] = v
                
        # 2. Save V3 Data to Safe Container Key "999"
        # Older versions will read `history[999] = {...}` and ignore it.
        # This prevents `ValueError` in versions that do `int(k)` blindly.
        v3_container = {}
        for k, v in self.history.items():
            serializable = [(d.isoformat(), m) for d, m in v]
            v3_container[str(k)] = serializable
        
        if v3_container:
            export["999"] = v3_container
            
        # 3. Save Departure History (v2.8) -> Key "888"
        # Safe Container for dicts. Older versions ignore it.
        if self.history_departure:
            dep_container = {}
            for k, v in self.history_departure.items():
                dep_container[str(k)] = v
            export["888"] = dep_container
                
        return export
