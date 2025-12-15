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
        """Call API and parse results."""
        try:
            # Check if entity exists (Startup Race Condition)
            state = self.hass.states.get(self.entity_id)
            if not state:
                 _LOGGER.info("Weather entity %s not ready yet. Skipping forecast.", self.entity_id)
                 return None
            
            if state.state in ("unavailable", "unknown"):
                 _LOGGER.info("Weather entity %s is %s. Skipping forecast.", self.entity_id, state.state)
                 return None

            _LOGGER.debug("Fetching fresh forecast for %s", self.entity_id)
            response = await self.hass.services.async_call(
                "weather", "get_forecasts",
                {"entity_id": self.entity_id, "type": "hourly"},
                blocking=True,
                return_response=True
            )
            
            if not response or self.entity_id not in response:
                # Try daily if hourly fails? For now just log error.
                _LOGGER.warning("No forecast data returned for %s", self.entity_id)
                return None
                
            raw_data = response[self.entity_id].get("forecast", [])
            if not raw_data:
                _LOGGER.warning("Empty forecast list for %s", self.entity_id)
                return None
                
            # 3. Clean & Normalize Data
            cleaned = []
            now_utc = dt_util.utcnow()
            
            for item in raw_data:
                # Validation
                if "temperature" not in item or item["temperature"] is None: continue
                if "datetime" not in item: continue
                
                # Parse & Normalize to UTC
                try:
                    dt = dt_util.parse_datetime(str(item["datetime"]))
                    if dt is None: continue
                    
                    # Convert to UTC
                    dt_utc = dt.astimezone(dt_util.UTC)
                    
                    cleaned.append({
                        "datetime": dt_utc,
                        "temperature": float(item["temperature"])
                    })
                except (ValueError, TypeError):
                    continue
            
            if not cleaned: return None
            
            # Sort just in case
            cleaned.sort(key=lambda x: x["datetime"])
            
            # Update Cache
            self._forecast_cache = cleaned
            self._cache_ts = dt_util.utcnow()
            _LOGGER.debug("Cached %d forecast points for %s", len(cleaned), self.entity_id)
            
            return cleaned
            
        except Exception as err:
            _LOGGER.error("Error fetching forecast: %s", err)
            return None
