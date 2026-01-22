"""Weather Service helper for Forecast Integration."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import event as event_helper
from homeassistant.util import dt as dt_util



_LOGGER = logging.getLogger(__name__)

# Constants
DEFAULT_CACHE_TTL = 30 # Minutes
DEBOUNCE_INVALIDATION = 10 # Minutes

class WeatherService:
    """Helper to fetch and cache weather forecasts."""

    def __init__(self, hass: HomeAssistant, entity_id: str, cache_ttl_min: int = DEFAULT_CACHE_TTL):
        self.hass = hass
        self.entity_id = entity_id
        self._cache_ttl = timedelta(minutes=cache_ttl_min)
        
        self._forecast_cache: list[dict] | None = None
        self._cache_ts: datetime | None = None
        self._forecast_type_used: str = "none" # Fix: Initialize to avoid AttributeError
        self._lock = asyncio.Lock()
        
        self._setup_listener()
        
    def _setup_listener(self):
        """Listen for state changes to invalidate cache (Debounced)."""
        event_helper.async_track_state_change_event(
            self.hass, [self.entity_id], self._handle_state_change
        )
        
    @callback
    def _handle_state_change(self, event):
        """Invalidate cache if it is 'stale enough'."""
        if not self._cache_ts: return
        
        age = dt_util.utcnow() - self._cache_ts
        if age > timedelta(minutes=DEBOUNCE_INVALIDATION):
            _LOGGER.debug("Weather entity changed and cache is > %d min old. Invalidating.", DEBOUNCE_INVALIDATION)
            self._forecast_cache = None
            self._cache_ts = None
            
    @property
    def forecast_type_used(self) -> str:
        """Return the forecast type currently in cache (hourly, twice_daily, daily, none)."""
        return self._forecast_type_used

    def get_cached_forecast(self) -> list[dict] | None:
        """Return cached forecast data (Sync for Coordinator)."""
        return self._forecast_cache
            
    async def get_forecasts(self) -> list[dict] | None:
        """Get forecasts (Cached or Fresh)."""
        async with self._lock:
            # 1. Check Cache
            if self._forecast_cache and self._cache_ts:
                age = dt_util.utcnow() - self._cache_ts
                if age < self._cache_ttl:
                    return self._forecast_cache
            
            # 2. Fetch Fresh
            return await self._fetch_fresh_forecast()



    async def _fetch_fresh_forecast(self) -> list[dict] | None:
        """Call API with fallback strategy."""
        # Check if entity exists
        state = self.hass.states.get(self.entity_id)
        if not state or state.state in ("unavailable", "unknown"):
             _LOGGER.info("Weather entity %s not ready/valid. Skipping.", self.entity_id)
             return None

        # Fallback Order: Hourly -> Twice Daily -> Daily
        try_types = ["hourly", "twice_daily", "daily"]
        
        for f_type in try_types:
            _LOGGER.debug("Fetching forecast for %s (type: %s)", self.entity_id, f_type)
            try:
                response = await self.hass.services.async_call(
                    "weather", "get_forecasts",
                    {"entity_id": self.entity_id, "type": f_type},
                    blocking=True,
                    return_response=True
                )
                
                if response and self.entity_id in response:
                    raw_data = response[self.entity_id].get("forecast", [])
                    if raw_data:
                        # Found data!
                        if f_type == "hourly":
                             clean_data = self._clean_data(raw_data)
                             if clean_data:
                                 self._forecast_cache = clean_data
                                 self._cache_ts = dt_util.utcnow()
                                 self._forecast_type_used = "hourly"
                                 _LOGGER.debug("Cached %d forecast points for %s (hourly)", len(clean_data), self.entity_id)
                                 return clean_data
                        else:
                             # Needs Interpolation
                             clean_data = self._clean_data(raw_data)
                             if clean_data and len(clean_data) >= 2:
                                 _LOGGER.info("Hourly forecast empty. Fallback to %s (Interpolating).", f_type)
                                 interpolated = self._interpolate_to_hourly(clean_data)
                                 self._forecast_cache = interpolated
                                 self._cache_ts = dt_util.utcnow()
                                 self._forecast_type_used = f_type
                                 _LOGGER.debug("Cached %d forecast points for %s (interpolated from %s)", len(interpolated), self.entity_id, f_type)
                                 return interpolated
            except Exception as err:
                _LOGGER.debug("Failed fetching %s for %s: %s", f_type, self.entity_id, err)
                
        _LOGGER.warning("All forecast types failed for %s", self.entity_id)
        self._forecast_type_used = "none"
        return None

    def _clean_data(self, raw_data: list[dict]) -> list[dict]:
        """Validate, parse (to UTC datetime), and sort raw data."""
        cleaned = []
        for item in raw_data:
            if "temperature" not in item or item["temperature"] is None: continue
            if "datetime" not in item: continue
            
            # Parse & Normalize to UTC
            try:
                # If already datetime, ensure UTC
                if isinstance(item["datetime"], datetime):
                    dt = item["datetime"]
                else:
                    # DEBUG
                    # print(f"DEBUG: Parsing {item['datetime']}", file=sys.stderr)
                    dt = dt_util.parse_datetime(str(item["datetime"]))
                
                if dt is None: 
                    print("DEBUG: dt is None", file=sys.stderr)
                    continue
                
                # Convert to UTC (Robust for naive datetimes)
                dt_utc = dt_util.as_utc(dt)
                
                cleaned.append({
                    "datetime": dt_utc,
                    "temperature": float(item["temperature"])
                })
            except (ValueError, TypeError):
                continue
        
        # Sort by time
        cleaned.sort(key=lambda x: x["datetime"])
        return cleaned

    def _interpolate_to_hourly(self, data: list[dict]) -> list[dict]:
        """Interpolate sparse data (daily/twice_daily) to hourly grid."""
        if len(data) < 2: return data # Cannot interpolate
        
        interpolated = []
        
        # Convert all to dt objects if not already (assuming string iso)
        # But usually integration returns strings. We need to handle that carefully.
        # Coordinator expects strings? Or datetime objects? 
        # _extract_target_forecast parses them. Ideally we work with parsed DT here for math.
        # But to match 'hourly' output, we should probably output strings? 
        # Re-using coordinator's parser logic is hard here without dependency loop.
        # Let's assume standard ISO strings.
        
        # Data is already cleaned (datetime objects in UTC)
        points = []
        for item in data:
            dt = item["datetime"]
            # Ensure it is a datetime
            if isinstance(dt, datetime):
                 points.append( (dt, float(item["temperature"])) )
            
        if not points: return []
        
        # 1. Fill Intervals
        for i in range(len(points) - 1):
            t_start, v_start = points[i]
            t_end, v_end = points[i+1]
            
            # Duration in hours
            delta_h = (t_end - t_start).total_seconds() / 3600.0
            if delta_h <= 0: continue
            
            # Slope
            slope = (v_end - v_start) / delta_h
            
            # Generate hourly points
            # We start at t_start. 
            # If delta_h is e.g. 24, we generate 0, 1, ... 23 hours offset
            steps = int(delta_h)
            for h in range(steps):
                t_new = t_start + timedelta(hours=h)
                v_new = v_start + (slope * h)
                
                interpolated.append({
                    "datetime": t_new, # Keep as datetime object (UTC)
                    "temperature": round(v_new, 1) # Round to 1 decimal like forecast
                })
                
        # Append last point
        last_t, last_v = points[-1]
        interpolated.append({
             "datetime": last_t, # Keep as datetime object (UTC)
             "temperature": last_v
        })
        
        return interpolated
                

