"""Test Action 2.5: Retroactive History Learning (Departures)."""
from unittest.mock import MagicMock, patch
import unittest
import sys
import asyncio
from datetime import datetime, timedelta

# MOCK Home Assistant
mock_hass = MagicMock()
sys.modules['homeassistant'] = mock_hass
sys.modules['homeassistant.config_entries'] = MagicMock()
sys.modules['homeassistant.const'] = MagicMock()
sys.modules['homeassistant.const'].STATE_ON = "on"
sys.modules['homeassistant.const'].STATE_OFF = "off"
sys.modules['homeassistant.core'] = MagicMock()
sys.modules['homeassistant.exceptions'] = MagicMock()

# Ensure helpers is a package
mock_helpers = MagicMock()
mock_helpers.__path__ = []
sys.modules['homeassistant.helpers'] = mock_helpers
sys.modules['homeassistant.helpers.storage'] = MagicMock()
sys.modules['homeassistant.helpers.issue_registry'] = MagicMock()
sys.modules['homeassistant.helpers.event'] = MagicMock() # Ensure this exists
sys.modules['homeassistant.util'] = MagicMock()

# Mock Recorder
sys.modules['homeassistant.components'] = MagicMock()
sys.modules['homeassistant.components.recorder'] = MagicMock()

# Mock Generics in Update Coordinator
class MockDataUpdateCoordinator:
    def __class_getitem__(cls, item):
        return cls
    def __init__(self, hass, logger, name, update_interval, config_entry):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.config_entry = config_entry

mock_uc = MagicMock()
mock_uc.DataUpdateCoordinator = MockDataUpdateCoordinator
sys.modules['homeassistant.helpers.update_coordinator'] = mock_uc

# Import after mocks
from custom_components.preheat.coordinator import PreheatingCoordinator
from custom_components.preheat.const import CONF_OCCUPANCY

class MockState:
    def __init__(self, state, last_changed):
        self.state = state
        self.last_changed = last_changed

class TestRetroactiveLearning(unittest.IsolatedAsyncioTestCase):
    
    async def asyncSetUp(self):
        self.coord = PreheatingCoordinator(mock_hass, MagicMock())
        self.coord.planner = MagicMock()
        # Mock Default Config
        self.coord._get_conf = MagicMock(side_effect=lambda k, d=None: "binary_sensor.occ" if k == CONF_OCCUPANCY else d)
        self.coord._parse_time_to_minutes = MagicMock(side_effect=[0, 1440]) # Start 0, End 1440 (Full Day)
        
        # Mock Save Data (Awaitable) - Use get_running_loop inside async method
        loop = asyncio.get_running_loop()
        future_save = loop.create_future()
        future_save.set_result(None)
        self.coord._async_save_data = MagicMock(return_value=future_save)

    async def test_scan_history_learns_departures(self):
        """Verify OFF states trigger record_departure."""
        
        # Setup Mock History
        # Access the global mock we created in imports
        mock_recorder = sys.modules['homeassistant.components.recorder']
        mock_instance = MagicMock()
        mock_recorder.get_instance.return_value = mock_instance
        mock_recorder.history = MagicMock() # Ensure history attr exists
        
        # Patch dt_util.as_local where it is USED
        # Patch the imported name in coordinator.py
        p = patch("custom_components.preheat.coordinator.dt_util")
        mock_util = p.start()
        mock_util.as_local.side_effect = lambda x: x
        self.addCleanup(p.stop)
        
        # Patch STATE_ON/OFF in coordinator.py because they might be polluted by earlier mocked imports
        p_on = patch("custom_components.preheat.coordinator.STATE_ON", "on")
        p_off = patch("custom_components.preheat.coordinator.STATE_OFF", "off")
        p_on.start()
        p_off.start()
        self.addCleanup(p_on.stop)
        self.addCleanup(p_off.stop)
        
        # 3 Events: ON (Arr), OFF (Dep), ON (Arr)
        t0 = datetime(2025, 1, 1, 8, 0)
        t1 = datetime(2025, 1, 1, 9, 0) # Departure
        t2 = datetime(2025, 1, 1, 10, 0) # Arrival
        
        states = [
            MockState("on", t0),
            MockState("off", t1), # Should be learnt as departure
            MockState("on", t2)
        ]
        
        # Helper to return our mock states
        def mock_get_history(*args):
            return {"binary_sensor.occ": states}
            
        # Manually create a Future to satisfy await
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        future.set_result(mock_get_history())
        
        mock_instance.async_add_executor_job = MagicMock(return_value=future)

        # Run (Direct await, no asyncio.run needed)
        await self.coord.scan_history_from_recorder()
        
        # Verify
        # 1. record_arrival called twice (t0, t2)
        self.assertEqual(self.coord.planner.record_arrival.call_count, 2)
        
        # 2. record_departure called ONCE (t1) -> PROOF IT WORKS
        self.assertEqual(self.coord.planner.record_departure.call_count, 1)
