"""House Arrival Collector for Preheat."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime, timedelta
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_GLOBAL_PRESENCE,
    CONF_ARRIVAL_COMFORT_BIAS,
    CONF_EVENING_COMFORT_WINDOW,
    CONF_WORKDAY,
    NO_TEMP_ERROR_THRESHOLD,
)

_LOGGER = logging.getLogger(__name__)

# Rolling window of house arrivals used for prediction (older habits age out)
HOUSE_ARRIVAL_MAX_AGE_DAYS = 30
DEFAULT_WORKDAYS = frozenset(range(5))  # Mon-Fri
_WEEKDAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _entry(item) -> tuple[date, int, bool | None]:
    """Normalise a history entry: (date, minutes) or (date, minutes, is_workday)."""
    return item[0], item[1], (item[2] if len(item) > 2 else None)

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
        # weekday -> [(date, minutes, is_workday)]; is_workday is the workday sensor's
        # verdict when the arrival was recorded live (None if unknown, e.g. bootstrap)
        self.history: dict[int, list[tuple[date, int, bool | None]]] = defaultdict(list)
        self._store = Store(hass, 1, "preheat.house")
        self.bootstrap_done = False
        self._unsub_listener = None
        self._listeners: list[callback] = []
        
        self.global_presence: str | None = None
        self.comfort_bias: str = "comfort"
        self.evening_window_str: str | None = None



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
                        d_str, minutes = item[0], item[1]
                        flag = item[2] if len(item) > 2 and isinstance(item[2], bool) else None
                        self.history[weekday].append((date.fromisoformat(d_str), int(minutes), flag))
                except Exception as e:
                    _LOGGER.warning("Failed to parse house history entry for key %s: %s", k, e)
        self.update_config()
        if self._prune(dt_util.now().date()):
            await self.async_save()

    def _prune(self, today: date) -> bool:
        """Drop arrivals older than the rolling window. Returns True if anything was removed."""
        cutoff = today - timedelta(days=HOUSE_ARRIVAL_MAX_AGE_DAYS)
        removed = False
        for weekday in list(self.history):
            kept = [e for e in self.history[weekday] if e[0] >= cutoff]
            if len(kept) != len(self.history[weekday]):
                removed = True
                self.history[weekday] = kept
        return removed

    # --- Workday handling -------------------------------------------------------
    def _workday_entity(self) -> str | None:
        """Workday sensor: the first one configured on a zone, else HA's default entity."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            ws = entry.options[CONF_WORKDAY] if CONF_WORKDAY in entry.options else entry.data.get(CONF_WORKDAY)
            if ws:
                return ws
        default = "binary_sensor.workday_sensor"
        return default if self.hass.states.get(default) else None

    def _workday_info(self) -> tuple[frozenset[int], bool | None]:
        """(weekdays that are workdays, is today a workday per the sensor or None)."""
        entity = self._workday_entity()
        state = self.hass.states.get(entity) if entity else None
        if state is None or state.state in ("unavailable", "unknown"):
            return DEFAULT_WORKDAYS, None
        days = state.attributes.get("workdays")
        workdays = DEFAULT_WORKDAYS
        if isinstance(days, list):
            parsed = frozenset(_WEEKDAY_MAP[str(d).lower()] for d in days if str(d).lower() in _WEEKDAY_MAP)
            if parsed:
                workdays = parsed
        today = True if state.state == "on" else False if state.state == "off" else None
        return workdays, today

    async def async_save(self) -> None:
        """Save learned data to storage."""
        v3_container = {}
        for k, v in self.history.items():
            if not v:
                continue
            v3_container[str(k)] = [
                (d.isoformat(), m) if flag is None else (d.isoformat(), m, flag)
                for d, m, flag in map(_entry, v)
            ]
        
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
        
        # Try to find the system entry first
        system_entry = None
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.unique_id == "preheat_system":
                system_entry = entry
                break
                
        def conf(entry, key):
            # Options take precedence over data, including an explicit None (cleared option)
            return entry.options[key] if key in entry.options else entry.data.get(key)

        if system_entry:
            global_presence = conf(system_entry, CONF_GLOBAL_PRESENCE)
            comfort_bias = conf(system_entry, CONF_ARRIVAL_COMFORT_BIAS) or "comfort"
            evening_window_str = conf(system_entry, CONF_EVENING_COMFORT_WINDOW)
        else:
            # Fallback to zones for backward compatibility
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                gp = conf(entry, CONF_GLOBAL_PRESENCE)
                if gp:
                    global_presence = gp
                cb = conf(entry, CONF_ARRIVAL_COMFORT_BIAS)
                if cb:
                    comfort_bias = cb
                ew = conf(entry, CONF_EVENING_COMFORT_WINDOW)
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
        has_same_block = any(
            d == today and (m < 720) == block_am for d, m, _ in map(_entry, self.history[weekday])
        )
        if not has_same_block:
            is_workday = None
            if today == dt_util.now().date():
                _, is_workday = self._workday_info()
            self.history[weekday].append((today, minutes, is_workday))
            self._prune(today)
            await self.async_save()
            self.async_update_listeners()

    def get_pooled_arrivals(
        self, is_weekend: bool, today: date | None = None,
        workdays: frozenset[int] = DEFAULT_WORKDAYS,
    ) -> tuple[list[int], list[int]]:
        """Return sorted AM and PM arrival minutes of the rolling window, pooled by
        workday vs. non-workday (the workday sensor's verdict at recording time where
        known, e.g. a public holiday counts as non-workday; else the configured workdays)."""
        cutoff = (today - timedelta(days=HOUSE_ARRIVAL_MAX_AGE_DAYS)) if today else None
        am_list = []
        pm_list = []
        for weekday, events in self.history.items():
            for d, m, flag in map(_entry, events):
                if cutoff and d < cutoff:
                    continue
                entry_is_workday = flag if flag is not None else (weekday in workdays)
                if entry_is_workday == is_weekend:
                    continue
                if m < 720:
                    am_list.append(m)
                else:
                    pm_list.append(m)
        return sorted(am_list), sorted(pm_list)

    def get_next_arrival(
        self, now: datetime, is_excluded: Callable[[date], bool] | None = None,
    ) -> tuple[datetime | None, float, str]:
        """Predict the next expected house arrival time and return (arrival_dt, confidence, source).

        `is_excluded` lets a zone skip days it does not preheat on (holiday calendar,
        "only on workdays").
        """
        now_local = dt_util.as_local(now)
        today_date = now_local.date()
        workdays, today_is_workday = self._workday_info()
        
        # Look ahead 8 days to find the next future event
        for day_offset in range(8):
            check_date = today_date + timedelta(days=day_offset)
            if is_excluded is not None and is_excluded(check_date):
                continue
            if check_date == today_date and today_is_workday is not None:
                is_weekend = not today_is_workday
            else:
                is_weekend = check_date.weekday() not in workdays
            am_list, pm_list = self.get_pooled_arrivals(is_weekend, today_date, workdays)
            
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
                    # Skip if zone has no temperature
                    if getattr(coord, "_consecutive_readiness_errors", 0) >= NO_TEMP_ERROR_THRESHOLD:
                        continue
                    lead = getattr(coord.data, "lead_time", 0.0) or 0.0
                    max_dur = max(max_dur, coord.data.predicted_duration, lead)
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
                self.history[weekday].append((date_obj, min(am_mins), None))
            if pm_mins:
                self.history[weekday].append((date_obj, min(pm_mins), None))
                
        self._prune(dt_util.now().date())
        self.bootstrap_done = True
        await self.async_save()
        _LOGGER.info("House Arrival Collector bootstrap complete. Loaded data for %d dates.", len(events_by_date))
