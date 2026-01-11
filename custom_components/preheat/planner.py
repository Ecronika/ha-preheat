"""Planner module for intelligent preheating."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, date
from collections import defaultdict

from homeassistant.util import dt as dt_util

from .patterns import PatternDetector, PatternResult
from .const import (
    MAX_HISTORY_ENTRIES,
    DEBOUNCE_THRESHOLD_MINUTES,
    SEARCH_LOOKAHEAD_DAYS,
    MIN_POINTS_FOR_V3,
    FULL_V3_POINTS,
)

_LOGGER = logging.getLogger(__name__)

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
        """
        Load history handling v2 vs v3 formats (Robust Load).
        Strategy:
        - Primary: Canonical v3 format (dict[int, list[tuple]]).
        - Legacy: Validates and loads v2 data (list[int]).
        Policy: Read v2 (Compat), Write v3 only (Phase-Out).
        """
        for k, v in stored.items():
            try:
                # 1. Normalize Key
                k_str = str(k).strip()
                
                # 2. Handle Special Container Keys
                if k_str == "999" and isinstance(v, dict):
                    self._load_v3_container(v)
                    continue

                if k_str == "888" and isinstance(v, dict):
                    self._load_departure_container(v)
                    continue

                # 3. Handle Legacy Prefixes (v3_X, v2_X)
                # Attempt to extract weekday from various key formats
                weekday = None
                
                if k_str.startswith("v3_"):
                    try:
                        weekday = int(k_str.split("_")[1])
                        # v3_X format is list of [date_str, min]
                        self._parse_v3_list(weekday, v)
                        continue
                    except (IndexError, ValueError):
                        pass

                elif k_str.startswith("v2_"):
                    # Legacy v2 format: Read only (no conversion to v3 possible - no dates).
                    try:
                        weekday = int(k_str.split("_")[1])
                        # Validate v2: Must be list of ints
                        if isinstance(v, list) and all(isinstance(x, (int, float)) for x in v):
                             self.history_v2[weekday] = [int(x) for x in v]
                        else:
                             _LOGGER.warning("Ignoring invalid v2 history item %s (not list of ints)", k)
                        continue  # Always continue after handling v2_
                    except (IndexError, ValueError):
                        continue  # Always continue after handling v2_

                # 4. Standard Integer Keys (Universal Payload)
                # Could be integer or string-int
                try:
                    weekday = int(k_str)
                except ValueError:
                    # Not an integer key and not a known prefix -> Junk
                    _LOGGER.warning("Ignoring invalid history key: %s (Type: %s)", k, type(k))
                    continue
                
                if not v:
                    continue
                
                # Validate v is a list before accessing v[0]
                if not isinstance(v, list):
                    _LOGGER.warning("Invalid history format for weekday %s: expected list, got %s", weekday, type(v))
                    continue
                
                # Detect Payload Type (v2 list-of-ints OR v3 list-of-lists)
                first = v[0]
                if isinstance(first, (int, float)):
                    # Legacy v2 format found at root level - validate and cast
                    safe_v2 = []
                    for x in v:
                        if isinstance(x, (int, float)):
                            safe_v2.append(int(x))
                        else:
                            _LOGGER.debug("Dropping non-numeric v2 value in weekday %s: %s", weekday, x)
                    self.history_v2[weekday] = safe_v2
                elif isinstance(first, list) or isinstance(first, tuple):
                    # v3 format
                    self._parse_v3_list(weekday, v)
                else:
                    _LOGGER.warning("Unknown history format for weekday %s: %s", weekday, first)

            except Exception as e:
                # Granular error handling: One bad key doesn't kill the load
                _LOGGER.warning("Failed to parse history entry for key '%s': %s", k, e)
                
        # Global Maintenance on Startup
        self.prune_all_history()

    def _load_v3_container(self, container: dict) -> None:
        """Unpack v3 data from the safe container with error handling."""
        for k, v in container.items():
            try:
                weekday = int(str(k).strip())
                self._parse_v3_list(weekday, v)
            except Exception as e:
                _LOGGER.warning("Failed to load v3 history item %s: %s", k, e)

    def _load_departure_container(self, container: dict) -> None:
        """Unpack departure history (v2.8) with error handling."""
        for k, v in container.items():
            try:
                weekday = int(str(k).strip())
                if isinstance(v, list):
                    # Validate dict structure: Must have 'date' and 'minutes'
                    safe_list = []
                    for item in v:
                        if isinstance(item, dict) and "date" in item and "minutes" in item:
                            try:
                                # Validate date format is ISO
                                datetime.fromisoformat(item["date"])
                                # Copy item to avoid mutation of source
                                safe_item = {**item, "minutes": int(item["minutes"])}
                                safe_list.append(safe_item)
                            except (ValueError, TypeError) as e:
                                _LOGGER.debug("Skipping invalid departure item in %s: %s", k, e)
                    if safe_list:
                        self.history_departure[weekday] = safe_list
            except Exception as e:
                _LOGGER.warning("Failed to load departure history item %s: %s", k, e)


    def _parse_v3_list(self, weekday: int, data: list) -> None:
        """Parse raw v3 list into internal history (Robust per-item)."""
        for item in data:
            try:
                if len(item) != 2:
                    _LOGGER.debug("Skipping v3 item with unexpected shape in weekday %s: %s", weekday, item)
                    continue
                d_str, minutes = item
                # Normalize date object (handle str, date, datetime)
                if isinstance(d_str, datetime):
                    d_obj = d_str.date()
                elif isinstance(d_str, date):
                    d_obj = d_str
                elif isinstance(d_str, str):
                    d_obj = datetime.fromisoformat(d_str).date()
                else:
                    _LOGGER.debug("Skipping invalid v3 item in weekday %s: unrecognized date type %s", weekday, type(d_str))
                    continue
                # Validate minutes range (0-1439)
                mins = int(minutes)
                if 0 <= mins < 24 * 60:
                    self.history[weekday].append((d_obj, mins))
                else:
                    _LOGGER.debug("Skipping invalid v3 item in weekday %s: minutes out of range %s", weekday, mins)
            except Exception as e:
                 _LOGGER.debug("Skipping invalid v3 item in weekday %s: %s", weekday, e)

    def record_arrival(self, dt: datetime) -> None:
        """Record a new arrival event."""
        dt_local = dt_util.as_local(dt)
        weekday = dt_local.weekday()
        minutes = dt_local.hour * 60 + dt_local.minute
        today = dt_local.date()
        
        # Update v3 History
        # Multi-Modal Support (v2.9-beta19): Allow multiple arrivals per day
        # Condition: Must be distinct (> 2 hours apart) to capture separate shifts.
        
        today_entries = [item for item in self.history[weekday] if item[0] == today]
        # Extract minutes to check
        existing_mins = [item[1] for item in today_entries]
        
        if self._is_duplicate(minutes, existing_mins):
             return
        
        self.history[weekday].append((today, minutes))
            
        # Rolling Window (Max Entries)
        if len(self.history[weekday]) > MAX_HISTORY_ENTRIES:
            self.history[weekday] = self.history[weekday][-MAX_HISTORY_ENTRIES:]

        # Update v2 History - Phase-Out (Read Only)
        # self.history_v2[weekday].append(minutes)

    def record_departure(self, dt: datetime, max_age_days: int = 60) -> None:
        """Record a new departure event."""
        dt_local = dt_util.as_local(dt)
        weekday = dt_local.weekday()
        minutes = dt_local.hour * 60 + dt_local.minute
        today_date = dt_local.date()
        date_iso = today_date.isoformat()
        
        # 1. DST Detection (Best Effort / Diagnostic Only)
        # Compare Timezone Offset of Today 03:00 vs Yesterday 03:00
        # If diff -> DST Switch Night. Uses replace(tzinfo=...) which is approximate.
        # This flag is stored for analytics but not used for prediction logic.
        dst_flag = False
        try:
            today_3am = datetime.combine(today_date, datetime.min.time()) + timedelta(hours=3)
            today_3am = today_3am.replace(tzinfo=dt_local.tzinfo)
            yesterday_3am = today_3am - timedelta(days=1)
            
            if today_3am.utcoffset() != yesterday_3am.utcoffset():
                dst_flag = True
                _LOGGER.debug("DST Switch Detected for %s. Flagging departure.", date_iso)
        except Exception:
            pass # Fallback safe
            
        # 2. Add New Entry
        # Dedup by date + time window (Multi-Modal Support v2.9)
        # We allow multiple departures per day if they are distinct (e.g. > 2 hours apart).
        # This supports Lunch vs Evening shifts.
        today_entries_mins = [
             x["minutes"] for x in self.history_departure[weekday]
             if x["date"] == date_iso
        ]
        
        if self._is_duplicate(minutes, today_entries_mins):
             return
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
            if x["date"] >= cutoff_date
        ]
        
        # 4. Pruning (Count Second - FIFO)
        if len(self.history_departure[weekday]) > MAX_HISTORY_ENTRIES:
            self.history_departure[weekday] = self.history_departure[weekday][-MAX_HISTORY_ENTRIES:]

    def get_next_predicted_departure(self, now: datetime) -> datetime | None:
        """
        Predict the next probable departure time based on history.
        Uses Clustering to find multi-modal patterns (e.g. Lunch 12:00 AND Evening 18:00).
        """
        now = dt_util.as_local(now)  # Ensure TZ-aware
        today_date = now.date()
        
        # Lookahead
        for day_offset in range(SEARCH_LOOKAHEAD_DAYS):
            check_date = today_date + timedelta(days=day_offset)
            weekday = check_date.weekday()
            
            raw_entries = self.history_departure.get(weekday, [])
            if not raw_entries:
                continue
                
            # Extract minutes list
            minutes_list = [x["minutes"] for x in raw_entries]
            
            # Use PatternDetector to find clusters (reusing v2 engine)
            # This handles outliers and finds centers of density
            clusters = self.detector.find_clusters_v2(minutes_list)
            
            if not clusters:
                continue
            
            # Convert cluster centers to potential datetimes
            candidates = []
            for c in clusters:
                # Safer TZ-aware construction
                dt = datetime.combine(check_date, datetime.min.time(), tzinfo=now.tzinfo) + timedelta(minutes=c.time_minutes)
                candidates.append(dt)
            
            # Sort to find the next one
            candidates.sort()
            
            for cand in candidates:
                if cand > now:
                    return cand
                    
        return None

    def prune_all_history(self, max_age_days: int = 60) -> None:
        """
        Maintenance Job: Prune all history (Arrivals, Departures, Legacy).
        Enforces MAX_HISTORY_ENTRIES and max_age_days.
        """
        today_date = dt_util.now().date()
        cutoff_date = (today_date - timedelta(days=max_age_days)).isoformat()
        cutoff_date_obj = today_date - timedelta(days=max_age_days)
        
        # 1. Prune Departures (Dicts)
        for weekday in list(self.history_departure.keys()): # Safe iteration
            # Sort chronologically before pruning
            self.history_departure[weekday].sort(key=lambda x: (x["date"], x["minutes"]))
            # Age (>= includes cutoff day)
            self.history_departure[weekday] = [
                x for x in self.history_departure[weekday]
                if x["date"] >= cutoff_date
            ]
            # Count (FIFO)
            if len(self.history_departure[weekday]) > MAX_HISTORY_ENTRIES:
                 self.history_departure[weekday] = self.history_departure[weekday][-MAX_HISTORY_ENTRIES:]

            if not self.history_departure[weekday]:
                 del self.history_departure[weekday]

        # 2. Prune Arrivals v3 (Tuples: date, minutes)
        for weekday in list(self.history.keys()):
             # Sort chronologically before pruning
             self.history[weekday].sort(key=lambda x: (x[0], x[1]))
             # Age (>= includes cutoff day)
             self.history[weekday] = [
                 x for x in self.history[weekday]
                 if x[0] >= cutoff_date_obj
             ]
             # Count (FIFO)
             if len(self.history[weekday]) > MAX_HISTORY_ENTRIES:
                  self.history[weekday] = self.history[weekday][-MAX_HISTORY_ENTRIES:]
            
             if not self.history[weekday]:
                  del self.history[weekday]

        # 3. Prune Legacy v2 (Integers) - Count Only
        for weekday in list(self.history_v2.keys()):
             if len(self.history_v2[weekday]) > MAX_HISTORY_ENTRIES:
                  self.history_v2[weekday] = self.history_v2[weekday][-MAX_HISTORY_ENTRIES:]

             if not self.history_v2[weekday]:
                  del self.history_v2[weekday]

    def get_schedule_for_today(self, now: datetime, is_holiday: bool = False) -> list[datetime]:
        """
        Get list of predicted arrival times for the rest of the day.
        Legacy-like wrapper.
        If is_holiday=True and today is a weekday, uses Sunday's pattern.
        """
        now = dt_util.as_local(now)  # Ensure TZ-aware
        events = []
        weekday = now.weekday()
        if is_holiday and weekday < 5:
            weekday = 6  # Use Sunday pattern for holidays on weekdays
            
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
            # Safer TZ-aware construction
            event_dt = datetime.combine(today, datetime.min.time(), tzinfo=now.tzinfo) + timedelta(minutes=c.time_minutes)
            
            if event_dt > now:
                events.append(event_dt)
        events.sort()
        return events


    def get_next_scheduled_event(
        self, 
        now: datetime, 
        blocked_dates: set[date] | None = None, 
        allowed_weekdays: list[int] | None = None
    ) -> datetime | None:
        """
        Predict the next event time based on history.
        Refactored v2.9.3: Uses helper to isolate candidate selection logic.
        """
        now = dt_util.as_local(now)  # Ensure TZ-aware
        today_date = now.date()
        self.last_pattern_result = None # Reset for each call to the main prediction function
        
        # Lookahead defined by constant
        for day_offset in range(SEARCH_LOOKAHEAD_DAYS):
            check_date = today_date + timedelta(days=day_offset)
            weekday = check_date.weekday()
            
            # 1. Blocked Dates (Holidays from Calendar)
            if blocked_dates and check_date in blocked_dates:
                 continue

            if allowed_weekdays is not None and weekday not in allowed_weekdays:
                continue

            candidates = self._get_candidates_for_date(check_date)
            
            if candidates:
                candidates.sort() # Ensure order
                for minute in candidates:
                    # Robust datetime construction (TZ Aware)
                    # Use existing TZ from 'now' to ensure comparison validity
                    event_dt = datetime.combine(check_date, datetime.min.time(), tzinfo=now.tzinfo) + timedelta(minutes=minute)
                    
                    if event_dt > now:
                        return event_dt
                
        return None

    def _get_candidates_for_date(self, check_date: date) -> list[int]:
        """Determine potential event times for a specific date (Refactor Phase 2b)."""
        weekday = check_date.weekday()
        v3_data = self.history.get(weekday, [])
        v2_data = self.history_v2.get(weekday, [])
        v3_count = len(v3_data)
        
        candidates = []
        
        # Phase 1: Legacy (Insufficient v3 data)
        if v3_count < MIN_POINTS_FOR_V3 and not v2_data:
             return []
        
        elif v3_count < MIN_POINTS_FOR_V3:
            # Phase 1b: Legacy Fallback
            candidates = self._predict_v2_candidates(v2_data)
            if candidates:
                 self.last_pattern_result = PatternResult(
                     prediction="legacy",
                     prediction_time=candidates[0], 
                     pattern_type="legacy_v2",
                     confidence=1.0, 
                     fallback_used=True,
                     modes_found={"legacy": 1}
                 )

        elif v3_count < FULL_V3_POINTS:
            # Phase 2: Hybrid Blending
            v2_cands = self._predict_v2_candidates(v2_data)
            v2_min = v2_cands[0] if v2_cands else None
            
            v3_res = self.detector.predict(v3_data, check_date)
            
            # Note: last_pattern_result is set AFTER prediction_minute is determined
            # to ensure consistency between pattern result and actual candidates.

            prediction_minute = None
            if v2_min is not None and v3_res.prediction_time is not None:
                weight = (v3_count - MIN_POINTS_FOR_V3) / (FULL_V3_POINTS - MIN_POINTS_FOR_V3)
                prediction_minute = int(v2_min * (1 - weight) + v3_res.prediction_time * weight)
            elif v3_res.prediction_time is not None:
                 prediction_minute = v3_res.prediction_time
            else:
                 prediction_minute = v2_min
            
            if prediction_minute is not None:
                candidates = [prediction_minute]
                # Set pattern result with actual blended prediction time
                pattern_type = "hybrid_blended" if (v2_min is not None and v3_res.prediction_time is not None) else v3_res.pattern_type if v3_res.prediction != "insufficient_data" else "legacy_v2"
                self.last_pattern_result = PatternResult(
                    prediction="hybrid" if v3_res.prediction != "insufficient_data" else "legacy_blended",
                    prediction_time=prediction_minute,
                    pattern_type=pattern_type,
                    confidence=v3_res.confidence if v3_res.prediction != "insufficient_data" else 0.5,
                    fallback_used=(v2_min is not None and v3_res.prediction_time is None)
                )

        else:
            # Phase 3: Pure v3
            v3_res = self.detector.predict(v3_data, check_date)
            self.last_pattern_result = v3_res
            if v3_res.prediction_time is not None:
                candidates = [v3_res.prediction_time]
                
        return candidates

    def _is_duplicate(self, minutes: int, existing_list: list[int]) -> bool:
        """Check if a timestamp is a duplicate (Debounce)."""
        for ex in existing_list:
            if abs(ex - minutes) < DEBOUNCE_THRESHOLD_MINUTES:
                return True
        return False

    def _predict_v2_candidates(self, timestamps: list[int]) -> list[int]:
        """Legacy helper: Return ALL cluster centers."""
        if not timestamps:
            return []
        clusters = self.detector.find_clusters_v2(timestamps)
        if not clusters:
            return []
        
        # Provide sorted output for consistency
        results = [c.time_minutes for c in clusters]
        results.sort()
        return results

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

    def get_departure_schedule_summary(self) -> dict[str, str]:
        """Get a human readable summary of learned departure times per weekday."""
        summary = {}
        weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i in range(7):
            raw_entries = self.history_departure.get(i, [])
            if not raw_entries:
                summary[weekdays[i]] = "-"
                continue
                
            # Extract minutes list
            minutes_list = [x["minutes"] for x in raw_entries]
            
            # Use PatternDetector to find clusters
            clusters = self.detector.find_clusters_v2(minutes_list)
            
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
        # Note: v2 is legacy; may be empty in new installs (Phase-Out). 
        # Exported for downgrade compatibility only.
        for k, v in self.history_v2.items():
            if v:
                export[str(k)] = v
                
        # 2. Save V3 Data to Safe Container Key "999"
        # Older versions will read `history[999] = {...}` and ignore it.
        # This prevents `ValueError` in versions that do `int(k)` blindly.
        v3_container = {}
        for k, v in self.history.items():
            if not v:  # Skip empty lists
                continue
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
