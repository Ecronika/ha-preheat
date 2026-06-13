"""House Arrival Collector for Preheat."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_GLOBAL_PRESENCE,
    CONF_ARRIVAL_COMFORT_BIAS,
    CONF_EVENING_COMFORT_WINDOW,
)

_LOGGER = logging.getLogger(__name__)

def get_percentile(sorted_list: list[int], q: float) -> int:
    """Calculate the percentile index and return the value."""
    if not sorted_list:
        return 0
    idx = int(q * (len(sorted_list) - 1))
    return sorted_list[idx]

def parse_window(window_str: str) -> tuple[int, int] | None:
    """Parse a time window string like '17:00-22:00' into start and end minutes."""
    if not window_str:
        return None
    try:
        parts = window_str.split("-")
        if len(parts) != 2:
            return None
        start_parts = parts[0].split(":")
        end_parts = parts[1].split(":")
        start_min = int(start_parts[0]) * 60 + int(start_parts[1])
        end_min = int(end_parts[0]) * 60 + int(end_parts[1])
        return start_min, end_min
    except Exception:
        return None

class HouseArrivalCollector:
    """Collects and predicts house arrival times across all zone entries."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the house collector."""
        self.hass = hass
        self.history: dict[int, list[tuple[date, int]]] = defaultdict(list)
        self._store = Store(hass, 1, "preheat.house")
        self.bootstrap_done = False
        self.global_entities_entry_id = None
        self._unsub_listener = None
        self._listeners: list[callback] = []
        
        self.global_presence: str | None = None
        self.comfort_bias: str = "comfort"
        self.evening_window_str: str | None = None

    def register_global_entities(self, entry_id: str) -> bool:
        """Register which entry ID 'owns' the global entities (once)."""
        if self.global_entities_entry_id is None:
            self.global_entities_entry_id = entry_id
            return True
        return self.global_entities_entry_id == entry_id

    def unregister_global_entities(self, entry_id: str) -> None:
        """Clean up owner entry ID on unload."""
        if self.global_entities_entry_id == entry_id:
            self.global_entities_entry_id = None

    def async_add_listener(self, update_callback: callback) -> callback:
        """Listen for updates."""
        self._listeners.append(update_callback)
        return lambda: self.async_remove_listener(update_callback)

    def async_remove_listener(self, update_callback: callback) -> None:
        """Remove a listener."""
        if update_callback in self._listeners:
            self._listeners.remove(update_callback)

    def async_update_listeners(self) -> None:
        """Update all listeners."""
        for cb in self._listeners:
            try:
                cb()
            except Exception as e:
                _LOGGER.error("Error updating house listener: %s", e)

    async def async_load(self) -> None:
        """Load learned data from storage."""
        data = await self._store.async_load()
        if data:
            self.bootstrap_done = data.get("bootstrap_done", False)
            history_data = data.get("arrival_history_v2", {}).get("999", {})
            self.history.clear()
            for k, v in history_data.items():
                try:
                    weekday = int(k)
                    for item in v:
                        d_str, minutes = item
                        self.history[weekday].append((date.fromisoformat(d_str), int(minutes)))
                except Exception as e:
                    _LOGGER.warning("Failed to parse house history entry for key %s: %s", k, e)
        self.update_config()

    async def async_save(self) -> None:
        """Save learned data to storage."""
        v3_container = {}
        for k, v in self.history.items():
            if not v:
                continue
            v3_container[str(k)] = [(d.isoformat(), m) for d, m in v]
        
        data = {
            "bootstrap_done": self.bootstrap_done,
            "arrival_history_v2": {"999": v3_container}
        }
        await self._store.async_save(data)

    def update_config(self) -> None:
        """Gather current configurations from all config entries."""
        global_presence = None
        comfort_bias = "comfort"
        evening_window_str = None
        
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            gp = entry.options.get(CONF_GLOBAL_PRESENCE) or entry.data.get(CONF_GLOBAL_PRESENCE)
            if gp:
                global_presence = gp
            cb = entry.options.get(CONF_ARRIVAL_COMFORT_BIAS) or entry.data.get(CONF_ARRIVAL_COMFORT_BIAS)
            if cb:
                comfort_bias = cb
            ew = entry.options.get(CONF_EVENING_COMFORT_WINDOW) or entry.data.get(CONF_EVENING_COMFORT_WINDOW)
            if ew:
                evening_window_str = ew
                
        self.global_presence = global_presence
        self.comfort_bias = comfort_bias
        self.evening_window_str = evening_window_str
        
        # Setup listener for global presence source
        if self._unsub_listener:
            self._unsub_listener()
            self._unsub_listener = None
            
        if self.global_presence:
            from homeassistant.helpers.event import async_track_state_change_event
            
            async def _handle_state_change(event):
                new_state = event.data.get("new_state")
                old_state = event.data.get("old_state")
                if new_state and new_state.state == "on" and (not old_state or old_state.state != "on"):
                    _LOGGER.info("Global presence source %s turned ON. Recording arrival.", self.global_presence)
                    await self.async_record_arrival(dt_util.now())
                    
            self._unsub_listener = async_track_state_change_event(
                self.hass, [self.global_presence], _handle_state_change
            )

    async def async_record_zone_arrival(self, entry_id: str, dt: datetime) -> None:
        """Record an arrival propagated from a zone coordinator (live feed)."""
        if self.global_presence:
            return  # Ignore zone arrivals if global presence source is set
        await self.async_record_arrival(dt)

    async def async_record_arrival(self, dt: datetime) -> None:
        """Record a house-level arrival event (deduplicated per day per AM/PM block)."""
        dt_local = dt_util.as_local(dt)
        weekday = dt_local.weekday()
        minutes = dt_local.hour * 60 + dt_local.minute
        today = dt_local.date()
        
        block_am = minutes < 720
        today_entries = [item for item in self.history[weekday] if item[0] == today]
        
        has_same_block = False
        for d, m in today_entries:
            m_am = m < 720
            if m_am == block_am:
                has_same_block = True
                break
                
        if not has_same_block:
            self.history[weekday].append((today, minutes))
            await self.async_save()
            self.async_update_listeners()

    def get_pooled_arrivals(self, is_weekend: bool) -> tuple[list[int], list[int]]:
        """Return sorted AM and PM arrival minutes pooled by workday/weekend."""
        am_list = []
        pm_list = []
        for weekday, events in self.history.items():
            is_wd_weekend = (weekday >= 5)
            if is_wd_weekend == is_weekend:
                for d, m in events:
                    if m < 720:
                        am_list.append(m)
                    else:
                        pm_list.append(m)
        return sorted(am_list), sorted(pm_list)

    def get_next_arrival(self, now: datetime) -> tuple[datetime | None, float, str]:
        """Predict the next expected house arrival time and return (arrival_dt, confidence, source)."""
        now_local = dt_util.as_local(now)
        today_date = now_local.date()
        
        # Look ahead 8 days to find the next future event
        for day_offset in range(8):
            check_date = today_date + timedelta(days=day_offset)
            is_weekend = (check_date.weekday() >= 5)
            am_list, pm_list = self.get_pooled_arrivals(is_weekend)
            
            # Check AM block (Morning)
            if len(am_list) >= 2:
                p25 = get_percentile(am_list, 0.25)
                p75 = get_percentile(am_list, 0.75)
                spread = p75 - p25
                conf = max(0.0, 1.0 - (spread / 300.0))
                if conf >= 0.7:
                    event_dt = datetime.combine(check_date, datetime.min.time(), tzinfo=now_local.tzinfo) + timedelta(minutes=p25)
                    if event_dt > now_local:
                        return event_dt, conf, "confident"
            
            # Check PM block (Evening)
            if len(pm_list) >= 2:
                p25 = get_percentile(pm_list, 0.25)
                p75 = get_percentile(pm_list, 0.75)
                spread = p75 - p25
                conf = max(0.0, 1.0 - (spread / 300.0))
                
                # Apply comfort bias to evening prediction
                q = 0.25
                if self.comfort_bias == "comfort":
                    q = 0.15
                elif self.comfort_bias == "economy":
                    q = 0.50
                    
                target_time = get_percentile(pm_list, q)
                
                if conf >= 0.7:
                    event_dt = datetime.combine(check_date, datetime.min.time(), tzinfo=now_local.tzinfo) + timedelta(minutes=target_time)
                    if event_dt > now_local:
                        return event_dt, conf, "confident"
                else:
                    # Fallback comfort window
                    if self.evening_window_str:
                        window = parse_window(self.evening_window_str)
                        if window:
                            start_min, _ = window
                            event_dt = datetime.combine(check_date, datetime.min.time(), tzinfo=now_local.tzinfo) + timedelta(minutes=start_min)
                            if event_dt > now_local:
                                return event_dt, conf, "fallback"
                                
        return None, 0.0, "none"

    def get_max_predicted_duration(self) -> float:
        """Find the maximum predicted preheat duration across all active zones."""
        max_dur = 0.0
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if hasattr(entry, "runtime_data"):
                coord = entry.runtime_data
                if coord and hasattr(coord, "data") and coord.data:
                    max_dur = max(max_dur, coord.data.predicted_duration)
        return max_dur if max_dur > 0.0 else 120.0 # Default fallback to 2 hours

    async def async_bootstrap(self) -> None:
        """Perform a one-time data-safe bootstrap from existing zone stores and optional recorder backfill."""
        if self.bootstrap_done:
            return
            
        _LOGGER.info("Starting House Arrival Collector bootstrap from existing zone entries...")
        events_by_date = defaultdict(list)
        
        # 1. Load from all zone config entry stores
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            store = Store(self.hass, 4, f"preheat.{entry.entry_id}")
            try:
                data = await store.async_load()
                if data:
                    v3_container = data.get("arrival_history_v2", {}).get("999", {})
                    for k, v in v3_container.items():
                        for item in v:
                            try:
                                d_obj = date.fromisoformat(item[0])
                                mins = int(item[1])
                                events_by_date[d_obj].append(mins)
                            except Exception:
                                continue
            except Exception as e:
                _LOGGER.warning("Failed to read store for bootstrap for entry %s: %s", entry.entry_id, e)
                
        # Update config first to know if we have a global presence source
        self.update_config()
        
        # 2. Optional Recorder Backfill from global presence source
        if self.global_presence:
            try:
                from homeassistant.components.recorder import history, get_instance
                recorder_instance = get_instance(self.hass)
                purge_keep_days = getattr(recorder_instance, "purge_keep_days", 10)
                
                start_date = dt_util.utcnow() - timedelta(days=purge_keep_days)
                _LOGGER.info("Performing recorder backfill for global presence source %s from past %d days...", self.global_presence, purge_keep_days)
                
                history_data = await get_instance(self.hass).async_add_executor_job(
                    history.get_significant_states,
                    self.hass,
                    start_date,
                    None,
                    [self.global_presence]
                )
                
                if history_data and self.global_presence in history_data:
                    states = history_data[self.global_presence]
                    for state in states:
                        if state.state == "on":
                            local_dt = dt_util.as_local(state.last_changed)
                            d_obj = local_dt.date()
                            mins = local_dt.hour * 60 + local_dt.minute
                            events_by_date[d_obj].append(mins)
            except Exception as e:
                _LOGGER.error("Failed to perform recorder backfill: %s", e)
                
        # 3. Deduplicate per day per block (AM/PM) and fill house history
        self.history.clear()
        for date_obj, minutes_list in events_by_date.items():
            weekday = date_obj.weekday()
            am_mins = [m for m in minutes_list if m < 720]
            pm_mins = [m for m in minutes_list if m >= 720]
            if am_mins:
                self.history[weekday].append((date_obj, min(am_mins)))
            if pm_mins:
                self.history[weekday].append((date_obj, min(pm_mins)))
                
        self.bootstrap_done = True
        await self.async_save()
        _LOGGER.info("House Arrival Collector bootstrap complete. Loaded data for %d dates.", len(events_by_date))
