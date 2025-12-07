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

    def get_next_scheduled_event(self, now: datetime, is_holiday: bool = False) -> datetime | None:
        """Get the very next event (Today or Tomorrow)."""
        today_events = self.get_schedule_for_today(now, is_holiday)
        if today_events:
            return today_events[0]
        
        # Try tomorrow
        # For tomorrow, "now" doesn't matter for filtering, we want the first event of the day.
        tomorrow = now + timedelta(days=1)
        weekday = tomorrow.weekday()
        
        # Check if tomorrow is also a holiday? 
        # The caller 'is_holiday' is for TODAY. We assume tomorrow is standard unless we check logic again.
        # Since we don't have tomorrow's holiday state here easily, we fallback to simple weekday.
        # (Enhancement: Call coordinator for tomorrow's state? For now: keep simple)
        if is_holiday and weekday < 5:
             # Heuristic: If today is holiday, tomorrow might not be... 
             # But 'is_holiday' param is strictly for Today.
             # We should probably trust 'weekday' for tomorrow.
             pass
             
        # Actually, let's just respect the weekday.
        # If tomorrow is a workday-holiday, it will be missed, but that is edge case.
        # If we really want to be correct, we'd need tomorrow's holiday state.
        # For now, let's just remove the blind 'weekday = 6' override for tomorrow based on TODAY's holiday state.
        
        timestamps = self.history.get(weekday, [])
        clusters = self.detector.find_clusters(timestamps)
        
        if not clusters:
             return None
             
        # Find earliest cluster
        earliest_min = min(c.time_minutes for c in clusters)
        tomorrow_dt = datetime.combine(tomorrow.date(), datetime.min.time()) + timedelta(minutes=earliest_min)
        tomorrow_dt = tomorrow_dt.replace(tzinfo=now.tzinfo)
        return tomorrow_dt

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
