"""Session Manager for managing occupancy sessions."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .coordinator import PreheatingCoordinator

_LOGGER = logging.getLogger(__name__)

class SessionManager:
    """
    Manages occupancy sessions (Start/End) with debouncing and anti-flapping logic.
    Replaces OccupancyDebouncer (v2.8).
    """

    def __init__(self, debounce_min: float, coordinator: PreheatingCoordinator) -> None:
        self._debounce_limit_sec = debounce_min * 60.0
        self._coordinator = coordinator
        
        # State
        self._session_start_time: datetime | None = None
        self._last_departure_time: datetime | None = None
        
        # Debounce State
        self._off_candidate_start: datetime | None = None
        self._is_debouncing: bool = False
        self._last_committed_time: datetime | None = None

    @property
    def session_start_time(self) -> datetime | None:
        """Return the start time of the current session, or None if unoccupied."""
        return self._session_start_time

    @property
    def is_occupied(self) -> bool:
        """Return True if currently in a valid session."""
        return self._session_start_time is not None

    def update(self, is_occupied: bool, now: datetime) -> bool:
        """
        Update occupancy state.
        Returns True if a NEW session has started (for learning triggers).
        """
        is_new_session_event = False

        if not is_occupied:
            # ON -> OFF (Potential Session End)
            if self.is_occupied: # Only if we were occupied
                if not self._is_debouncing:
                    _LOGGER.debug("[Session] Session End Candidate? Starting timer (%.1f min). Off at: %s", 
                                  self._debounce_limit_sec/60, now)
                    self._off_candidate_start = now
                    self._is_debouncing = True
                    # Note: We do NOT clear _session_start_time yet! We wait for debounce.
            else:
                 # Already off, nothing to do
                 pass
        else:
            # OFF -> ON (Flapping / Return / New Session)
            
            # 1. Check Anti-Flapping (Gap Check)
            debounce_min_min = self._debounce_limit_sec / 60.0
            
            should_start_session = False
            
            if self._last_departure_time:
                off_duration = (now - self._last_departure_time).total_seconds() / 60.0
                if off_duration >= debounce_min_min:
                    should_start_session = True
                else:
                    if not self.is_occupied:
                         _LOGGER.debug("[Anti-Flapping] Ignored Arrival (Gap %.1f min < %.1f min). Maintaining previous session state.", 
                                       off_duration, debounce_min_min)
            else:
                 # First session ever or reset
                 should_start_session = True

            # 2. Debouncing Logic (Correcting false departures)
            if self._is_debouncing and self._off_candidate_start:
                # RACE CONDITION CHECK:
                # If OFF duration > Limit, but check() missed it (jitter), we MUST commit now before resetting!
                elapsed = (now - self._off_candidate_start).total_seconds()
                if elapsed >= self._debounce_limit_sec:
                    _LOGGER.info("[Session] Race Condition Caught! Session actually ended before return. Committing.")
                    self._commit_departure(self._off_candidate_start)
                    # And now we immediately start a new one?
                    # If we commit departure, session ends. Then 'should_start_session' logic applies below.
                else:
                    _LOGGER.debug("[Session] False Alarm (Flapping). Session continues. (Off duration: %.1fs)", elapsed)
                
                # Cancel Debounce (We are back ON)
                self._is_debouncing = False
                self._off_candidate_start = None
            
            # 3. Start Session if needed
            if should_start_session and not self.is_occupied:
                 self._session_start_time = now
                 is_new_session_event = True
                 self._off_candidate_start = None # Clear any pending debounce
                 self._is_debouncing = False

        return is_new_session_event

    def mark_departure(self, now: datetime) -> None:
         """Manually mark a departure (e.g. initial load or logic trigger)."""
         self._last_departure_time = now
         self._session_start_time = None
         self._is_debouncing = False

    def _commit_departure(self, departure_time: datetime) -> None:
        """Commit the session end."""
        # Double-Commit Guard
        if self._last_committed_time == departure_time:
            return

        # End Session Locally
        self._session_start_time = None 
        self._last_departure_time = departure_time
        self._last_committed_time = departure_time
        
        # Notify Coordinator/Planner
        self._coordinator.planner.record_departure(departure_time)
        
        # Throttled Save
        if hasattr(self._coordinator._store, "async_delay_save"):
             self._coordinator._store.async_delay_save(self._coordinator._get_data_for_storage, 10.0)
        else:
             self._coordinator.hass.async_create_task(self._coordinator._async_save_data())

    async def check_debounce(self, now: datetime) -> None:
        """Called periodically to check if debounce timer expired."""
        if not self._is_debouncing or self._off_candidate_start is None:
            return

        elapsed = (now - self._off_candidate_start).total_seconds()
        if elapsed >= self._debounce_limit_sec:
            final_departure_time = self._off_candidate_start
            _LOGGER.info("[Session] Session End CONFIRMED. Departed at: %s (Latency: %.1fs)", 
                         final_departure_time, elapsed)
            
            self._commit_departure(final_departure_time)
            
            self._is_debouncing = False
            self._off_candidate_start = None
