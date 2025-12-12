"""Planner module for intelligent preheating."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, date

from homeassistant.util import dt as dt_util

from .patterns import PatternDetector, ArrivalCluster
from .const import (
    DEFAULT_ARRIVAL_MIN,
    ATTR_ARRIVAL_HISTORY,
)
from collections import defaultdict

_LOGGER = logging.getLogger(__name__)

class PreheatPlanner:
    """Manages arrival history and prediction."""

    def __init__(self, stored_history: dict | None = None) -> None:
        """Initialize."""
        self.detector = PatternDetector()
        # History format: {weekday_int: [minutes, minutes, ...]}
        # We keep last N entries.
        self.history: dict[int, list[int]] = defaultdict(list)
        
        if stored_history:
            # Migration or Load
            for k, v in stored_history.items():
                self.history[int(k)] = v

    def record_arrival(self, dt: datetime) -> None:
        """Record a new arrival event."""
        # Check for duplicate (same day, close time) to avoid noise
        # Actually pattern detector handles noise, but we don't want to store 100 points for one day.
        # Simple debounce: 
        weekday = dt.weekday()
        minutes = dt.hour * 60 + dt.minute
        
        self.history[weekday].append(minutes)
        # Keep last 20 per weekday
        if len(self.history[weekday]) > 20:
             self.history[weekday] = self.history[weekday][-20:]

    def get_schedule_for_today(self, now: datetime, is_holiday: bool = False) -> list[datetime]:
        """
        Get list of predicted arrival times for the rest of the day.
        """
        weekday = now.weekday()
        
        # Holiday Logic: 
        # Only treat Mon-Fri (0-4) as Sunday (6) if Holiday.
        # Weekends (5,6) keep their own identity.
        if is_holiday and weekday < 5:
            weekday = 6
            
        timestamps = self.history.get(weekday, [])
        if not timestamps:
            # Fallback if no data: Return a default if it's the first time?
            # Or return empty and let fallback logic handle it.
            # Let's return a default 18:00 if absolutely empty?
            # No, better to be safe and not preheat if we know nothing.
            # Wait, preheat implies comfort. 
            # Let's fallback to "Default Arrival" from config if empty.
            return []

        clusters = self.detector.find_clusters(timestamps)
        
        # Convert clusters to datetimes for today
        events = []
        today = now.date()
        
        for c in clusters:
            # Create datetime
            event_dt = datetime.combine(today, datetime.min.time()) + timedelta(minutes=c.time_minutes)
            event_dt = event_dt.replace(tzinfo=now.tzinfo)
            
            if event_dt > now:
                events.append(event_dt)
                
        # Sort
        events.sort()
        return events

    def get_next_scheduled_event(self, now: datetime, allowed_weekdays: list[int] | None = None) -> datetime | None:
        """
        Get the very next event (Lookahead up to 7 days).
        
        Args:
            now: Current timestamp (aware).
            allowed_weekdays: List of allowed weekday integers (0=Mon, 6=Sun). 
                              If None, all days are allowed.
        """
        today_date = now.date()
        
        # Look ahead 7 days to cover a full weekly cycle
        for day_offset in range(8):
            check_date = today_date + timedelta(days=day_offset)
            weekday = check_date.weekday()
            
            # 1. Check Workday Restriction
            if allowed_weekdays is not None:
                if weekday not in allowed_weekdays:
                    continue # Skip this day (e.g. Weekend)
            
            # 2. Get Events for this Weekday
            timestamps = self.history.get(weekday, [])
            if not timestamps:
                continue
                
            clusters = self.detector.find_clusters(timestamps)
            if not clusters:
                continue
            
            # 3. Find valid event on this day
            earliest_min = min(c.time_minutes for c in clusters)
            event_dt = datetime.combine(check_date, datetime.min.time()) + timedelta(minutes=earliest_min)
            event_dt = event_dt.replace(tzinfo=now.tzinfo)
            
            # 4. Filter Past Events (Only relevant for Today/offset=0)
            if event_dt > now:
                return event_dt
                
            # If Today has multiple events, we might need to check the next cluster?
            # Current logic just takes min(). If min is past, it discards Today entirely?
            # Enhancement: Check all clusters for Today.
            if day_offset == 0:
                # Iterate all clusters to find one > now
                sorted_mins = sorted([c.time_minutes for c in clusters])
                for m in sorted_mins:
                     dt_candidate = datetime.combine(check_date, datetime.min.time()) + timedelta(minutes=m)
                     dt_candidate = dt_candidate.replace(tzinfo=now.tzinfo)
                     if dt_candidate > now:
                         return dt_candidate
        
        # No event found in next 7 days matching criteria
        return None

    def get_schedule_summary(self) -> dict[str, str]:
        """Get a human readable summary of learned times per weekday."""
        summary = {}
        weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i in range(7):
            timestamps = self.history.get(i, [])
            if not timestamps:
                summary[weekdays[i]] = "-"
                continue
            
            clusters = self.detector.find_clusters(timestamps)
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
        """Export history."""
        return dict(self.history)
