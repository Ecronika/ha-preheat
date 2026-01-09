
import sys
import os
import unittest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# --- MOCK Home Assistant ---
import types
ha = types.ModuleType("homeassistant")
ha.__path__ = []
sys.modules["homeassistant"] = ha

sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock()
sys.modules["homeassistant.const"] = MagicMock()
sys.modules["homeassistant.util"] = MagicMock()
mock_dt = MagicMock()
mock_dt.UTC = timezone.utc
mock_dt.utcnow.side_effect = lambda: datetime.now(timezone.utc)
sys.modules["homeassistant.util.dt"] = mock_dt
sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.helpers.event"] = MagicMock()
sys.modules["homeassistant.helpers.storage"] = MagicMock()
sys.modules["homeassistant.helpers.issue_registry"] = MagicMock()
sys.modules["homeassistant.exceptions"] = MagicMock()

# Mock DUC
class MockDataUpdateCoordinator:
    def __init__(self, hass, logger, name, update_interval, **kwargs):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None
    async def _async_update_data(self): pass
    def async_add_listener(self, *args): pass
    async def async_refresh(self): pass
    async def async_request_refresh(self): pass
    def __class_getitem__(cls, item): return cls
    def _schedule_refresh(self): pass # Mock DUC internal

mock_duc_mod = MagicMock()
mock_duc_mod.DataUpdateCoordinator = MockDataUpdateCoordinator
mock_duc_mod.UpdateFailed = Exception
sys.modules["homeassistant.helpers.update_coordinator"] = mock_duc_mod

from custom_components.preheat.coordinator import PreheatingCoordinator, PreheatData, CONF_DEBOUNCE_MIN
from custom_components.preheat.const import DEFAULT_DEBOUNCE_MIN

class TestAdaptivePolling(unittest.IsolatedAsyncioTestCase):
    """Test Adaptive Polling Logic (Action 3.2)."""

    def setUp(self):
        self.hass = MagicMock()
        self.entry = MagicMock()
        self.entry.entry_id = "test_entry"
        self.entry.title = "Test Zone"
        self.entry.options = {}
        self.entry.data = {}
        
        # Patch heavy initialization
        with patch("custom_components.preheat.coordinator.PreheatingCoordinator._setup_listeners"), \
             patch("custom_components.preheat.coordinator.PreheatingCoordinator.async_load_data"):
             self.coord = PreheatingCoordinator(self.hass, self.entry)
        
        # Init dummy data
        self.coord.data = PreheatData(
            preheat_active=False,
            next_start_time=None,
            operative_temp=20.0,
            target_setpoint=21.0,
            next_arrival=None,
            predicted_duration=0.0,
            mass_factor=20.0,
            loss_factor=5.0,
            learning_active=True,
            is_occupied=False,
            window_open=False
        )
        self.coord.diagnostics_data = {}

        # Reset Update Interval to Standard (1 min)
        self.coord.update_interval = timedelta(minutes=1)

    async def test_adaptive_polling_logic(self):
        """Verify interval adjustment based on state."""
        
        # 1. Idle State: OFF, Unoccupied, No Event
        # Expectation: 5 min
        self.coord.data = self.coord.data # Ensure data set
        self.coord.update_interval = timedelta(minutes=1) # Start fast
        
        # Mocking the new method if it's not yet in the class during this test execution
        # But we will add it shortly. For now, we assume it's there.
        # IF this test fails with AttributeError, it means we haven't patched the file yet
        if not hasattr(self.coord, "_update_polling_interval"):
            self.skipTest("_update_polling_interval not implemented yet")

        self.coord._update_polling_interval(self.coord.data)
        self.assertEqual(self.coord.update_interval, timedelta(minutes=5))
        
        # 2. Occupied: User Present
        # Expectation: 1 min
        # Create fresh data
        data_occ = PreheatData(
            preheat_active=False, next_start_time=None, operative_temp=20, target_setpoint=21, 
            next_arrival=None, predicted_duration=0, mass_factor=20, loss_factor=5, learning_active=True,
            is_occupied=True, window_open=False
        )
        self.coord._update_polling_interval(data_occ)
        self.assertEqual(self.coord.update_interval, timedelta(minutes=1))
        
        # 3. Preheat Active
        data_active = PreheatData(
            preheat_active=True, next_start_time=None, operative_temp=20, target_setpoint=21, 
            next_arrival=None, predicted_duration=0, mass_factor=20, loss_factor=5, learning_active=True,
            is_occupied=False, window_open=False
        )
        self.coord._update_polling_interval(data_active)
        self.assertEqual(self.coord.update_interval, timedelta(minutes=1))

        # 4. Window Open
        data_win = PreheatData(
            preheat_active=False, next_start_time=None, operative_temp=20, target_setpoint=21, 
            next_arrival=None, predicted_duration=0, mass_factor=20, loss_factor=5, learning_active=True,
            is_occupied=False, window_open=True
        )
        self.coord._update_polling_interval(data_win)
        self.assertEqual(self.coord.update_interval, timedelta(minutes=1))
        
        # 5. Approaching Start (< 2 hours)
        # 1 hour away
        now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        start = datetime(2025, 1, 1, 13, 0, tzinfo=timezone.utc)
        
        with patch("custom_components.preheat.coordinator.dt_util.utcnow", return_value=now):
            data_soon = PreheatData(
                preheat_active=False, next_start_time=start, operative_temp=20, target_setpoint=21, 
                next_arrival=None, predicted_duration=0, mass_factor=20, loss_factor=5, learning_active=True,
                is_occupied=False, window_open=False
            )
            self.coord._update_polling_interval(data_soon)
            self.assertEqual(self.coord.update_interval, timedelta(minutes=1))
            
            # 3 hours away -> Idle (5 min)
            start_far = datetime(2025, 1, 1, 15, 0, tzinfo=timezone.utc)
            data_far = PreheatData(
                preheat_active=False, next_start_time=start_far, operative_temp=20, target_setpoint=21, 
                next_arrival=None, predicted_duration=0, mass_factor=20, loss_factor=5, learning_active=True,
                is_occupied=False, window_open=False
            )
            self.coord._update_polling_interval(data_far)
            self.assertEqual(self.coord.update_interval, timedelta(minutes=5))

if __name__ == '__main__':
    unittest.main()
