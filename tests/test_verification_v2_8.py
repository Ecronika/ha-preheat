"""
verification_tests_v2_8.py

This module contains targeted tests for the "Integrator" update (v2.8.0).
It validates the behavior specified in the implementation_plan.
"""
import unittest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import sys

# --- Mock Entities to avoid Metaclass Conflict (Pollution from other tests) ---
class MockEntity:
    pass

class MockSensorEntity(MockEntity):
    pass

class MockBinarySensorEntity(MockEntity):
    pass

class MockCoordinatorEntity(MockEntity):
    def __init__(self, coordinator):
        self.coordinator = coordinator
    def __class_getitem__(cls, item): return cls

# Patch sys.modules BEFORE imports
import types
ha = types.ModuleType("homeassistant")
ha.__path__ = []
sys.modules['homeassistant'] = ha

# Core
ha.core = MagicMock()
sys.modules['homeassistant.core'] = ha.core

# Helpers
ha.helpers = types.ModuleType("homeassistant.helpers")
ha.helpers.__path__ = []
sys.modules['homeassistant.helpers'] = ha.helpers

ha.helpers.update_coordinator = MagicMock()
sys.modules['homeassistant.helpers.update_coordinator'] = ha.helpers.update_coordinator
ha.helpers.update_coordinator.CoordinatorEntity = MockCoordinatorEntity

# Components
ha.components = types.ModuleType("homeassistant.components")
ha.components.__path__ = []
sys.modules['homeassistant.components'] = ha.components

ha.components.sensor = MagicMock()
sys.modules['homeassistant.components.sensor'] = ha.components.sensor
ha.components.sensor.SensorEntity = MockSensorEntity
ha.components.sensor.SensorDeviceClass = MagicMock()
ha.components.sensor.SensorStateClass = MagicMock()

ha.components.binary_sensor = MagicMock()
sys.modules['homeassistant.components.binary_sensor'] = ha.components.binary_sensor
ha.components.binary_sensor.BinarySensorEntity = MockBinarySensorEntity
ha.components.binary_sensor.BinarySensorDeviceClass = MagicMock()


from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import sys

from custom_components.preheat.coordinator import OccupancyDebouncer, PreheatingCoordinator
from custom_components.preheat.const import (
    CONF_DEBOUNCE_MIN,
    CONF_PHYSICS_MODE,
    PHYSICS_STANDARD,
    PHYSICS_ADVANCED,
    CONF_SCHEDULE_ENTITY,
)
from custom_components.preheat.optimal_stop import OptimalStopManager, SessionResolver
from custom_components.preheat.physics import ThermalPhysics

class TestV28Features(unittest.TestCase):

    def run_async(self, coro):
        return asyncio.run(coro)

    def test_occupancy_debouncer_boundary(self):
        """
        Test Debounce Logic:
        - OFF at 15:00. Debounce 15m.
        - ON at 15:14:59 -> NO Commit.
        - ON at 15:15:01 -> COMMIT (Timestamp 15:00).
        """
        hass = MagicMock()
        mock_planner = MagicMock()
        debouncer = OccupancyDebouncer(15, hass) # Arg 1 is debounce_min, Arg 2 is coordinator (hass here for simplicity)
        
        # NOTE: OccupancyDebouncer.__init__ signature is (debounce_min, parent_coordinator)
        # My test instantiation `OccupancyDebouncer(hass, mock_planner)` was WRONG order too?
        # Let's check init: `def __init__(self, debounce_min: float, parent_coordinator: "PreheatingCoordinator"):`
        # Yes. Fixed above.
        
        debouncer._coordinator = MagicMock()
        debouncer._coordinator.planner = mock_planner
        
        # 1. Start Event (OFF) at 15:00
        t0 = datetime(2025, 1, 1, 15, 0, 0, tzinfo=timezone.utc)
        
        # The debouncer.handle_change logic:
        # If ON -> OFF: Record off_start_time
        debouncer.handle_change(new_state_on=False, now=t0)
        self.assertEqual(debouncer._off_start_time, t0)
        
        # 2. Case A: Recovery within debounce (False Alarm)
        # Time is 15:14:59 (1s before timeout)
        t1 = t0 + timedelta(minutes=14, seconds=59)
        # User comes back (ON)
        debouncer.handle_change(new_state_on=True, now=t1)
        
        # Expect: Reset, NO commit
        self.assertIsNone(debouncer._off_start_time)
        mock_planner.record_departure.assert_not_called()
        
        # 3. Case B: True Departure
        # Reset state manually for test
        debouncer.handle_change(new_state_on=False, now=t0)
        
        # Time is 15:15:01 (1s after timeout)
        t2 = t0 + timedelta(minutes=15, seconds=1)
        debouncer.handle_change(new_state_on=True, now=t2)
        
        # Expect: Commit called with t0 (Original departure time)
        mock_planner.record_departure.assert_called_once()
        args, _ = mock_planner.record_departure.call_args
        self.assertEqual(args[0], t0)
        self.assertIsNone(debouncer._off_start_time)

    def test_dst_flagging(self):
        """
        Verify that patterns.predict_departure filters out flagged entries (DST).
        """
        from custom_components.preheat.patterns import PatternDetector
        pd = PatternDetector()
        
        history = [
            {"minutes": 100, "dst_flag": False},
            {"minutes": 110, "dst_flag": False},
            {"minutes": 900, "dst_flag": True}, # Anomaly
            {"minutes": 105, "dst_flag": False}
        ]
        
        # Filtered: [100, 105, 110]
        # P90 (Idx 1) = 105
        
        result = pd.predict_departure(history)
        self.assertIsNotNone(result)
        prediction, confidence = result
        
        # P90 of 3 items sorted: 100, 105, 110. 
        # Index = 0.9 * 2 = 1.8 -> 1
        self.assertEqual(prediction, 105)
        
    def test_midnight_wrapping(self):
        """
        Test Case: Schedule Mon 16:00 - Tue 02:00.
        Verify `session_end` is correctly identified.
        """
        hass = MagicMock()
        resolver = SessionResolver(hass, "schedule.test")
        
        # Tue 02:00
        tue_0200 = datetime(2025, 1, 7, 2, 0, 0, tzinfo=timezone.utc)
        
        # Fix: Patch locally
        with patch("custom_components.preheat.optimal_stop.dt_util") as mock_dt:
            mock_dt.parse_datetime.side_effect = lambda x: datetime.fromisoformat(x)
            mock_dt.now.return_value = datetime(2025, 1, 6, 23, 0, 0, tzinfo=timezone.utc)
            mock_dt.UTC = timezone.utc
            
            with patch.object(hass.states, 'get') as mock_get:
                mock_state = MagicMock()
                mock_state.state = "on"
                mock_state.attributes = {"next_event": tue_0200.isoformat()}
                mock_get.return_value = mock_state
                
                end_time = resolver.get_current_session_end()
                self.assertEqual(end_time, tue_0200)

    def test_physics_mode_switch(self):
        """
        Verify Feature Flag correctly swaps models.
        """
        hass = MagicMock()
        manager = OptimalStopManager(hass)
        
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        future = now + timedelta(hours=2)
        forecasts = [{"datetime": now, "temperature": 0}, {"datetime": future, "temperature": 0}]
        
        # Configure global mock for this test
        # Fix: Patch the imported module locally to survive global pollution by other tests
        with patch("custom_components.preheat.optimal_stop.dt_util") as mock_dt:
            mock_dt.utcnow.return_value = now
            
            # Ensure we patch the imported functions in optimal_stop
            # Note: 'custom_components' path must resolve to what was imported.
            
            patch_euler = patch("custom_components.preheat.optimal_stop.calculate_coast_duration_euler")
            patch_std = patch("custom_components.preheat.optimal_stop.calculate_coast_duration")
            
            with patch_euler as mock_euler, patch_std as mock_std:
                mock_euler.return_value = 30.0
                mock_std.return_value = 30.0
                    
                # 1. Advanced Mode
                config_adv = {
                    CONF_PHYSICS_MODE: PHYSICS_ADVANCED,
                    "forecasts": forecasts,
                    "stop_tolerance": 0.5
                }
                
                # Setup environment to avoid safety break
                # Floor = 21.0 - 0.5 = 20.5.
                # Current = 21.0.
                # 21.0 >= 20.3 (floor-0.2). OK.
                
                manager.update(21.0, 21.0, future, lambda s,e: 0, 10, config_adv)
                
                # Debug Assertions
                if mock_euler.call_count == 0:
                     print("DEBUG: mock_euler was NOT called.")
                     print(f"Manager Active? {manager._active}")
                     print(f"Reason? {manager._reason}")
                
                mock_euler.assert_called()
                mock_std.assert_not_called()
                
                mock_euler.reset_mock()
                mock_std.reset_mock()
                
                # 2. Standard Mode
                config_std = {
                    CONF_PHYSICS_MODE: PHYSICS_STANDARD,
                    "stop_tolerance": 0.5
                }
                manager.update(21.0, 21.0, future, lambda s,e: 0, 10, config_std)
                mock_std.assert_called()
                mock_euler.assert_not_called()

    def test_v28_new_entities(self):
        """
        Verify new v2.8 entities can be instantiated and provide correct values.
        """
        from custom_components.preheat.sensor import PreheatNextSessionEndSensor
        from custom_components.preheat.binary_sensor import (
            PreheatNeededBinarySensor,
            PreheatBlockedBinarySensor,
            PreheatActiveBinarySensor
        )
        
        # Setup Mocks
        coord = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_123"
        entry.title = "Test Zone"
        
        # 1. NextSessionEnd
        # Data: next_departure = 12:00
        sensor = PreheatNextSessionEndSensor(coord, entry)
        t_val = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        coord.data.next_departure = t_val
        self.assertEqual(sensor.native_value, t_val)
        
        # 2. PreheatNeeded
        # Logic: now >= next_start
        needed = PreheatNeededBinarySensor(coord, entry)
        
        # Case A: No schedule -> False
        coord.data.next_start_time = None
        self.assertFalse(needed.is_on)
        
        # Case B: Future Start -> False
        t_start = datetime(2025, 1, 1, 15, 0, 0, tzinfo=timezone.utc)
        coord.data.next_start_time = t_start
        
        # Mock dt_util.utcnow() < t_start
        # Mock global dt_util since it is imported inside the function
        # We need to patch the one in sys.modules or use a global patch context
        mock_dt = sys.modules["homeassistant.util"].dt
        
        # BEFORE
        mock_dt.utcnow.return_value = t_start - timedelta(minutes=1)
        self.assertFalse(needed.is_on)
        
        # AFTER
        mock_dt.utcnow.return_value = t_start + timedelta(seconds=1)
        self.assertTrue(needed.is_on)
             
        # 3. PreheatBlocked
        blocked = PreheatBlockedBinarySensor(coord, entry)
        
        # Case A: Not blocked
        coord.data.decision_trace = {"blocked": False}
        self.assertFalse(blocked.is_on)
        self.assertEqual(blocked.extra_state_attributes, {})
        
        # Case B: Blocked
        coord.data.decision_trace = {"blocked": True, "reason": "window_open"}
        self.assertTrue(blocked.is_on)
        self.assertEqual(blocked.extra_state_attributes["reason"], "window_open")
        
        # 4. Active (Rehabilitated)
        active = PreheatActiveBinarySensor(coord, entry)
        self.assertTrue(hasattr(active, "_attr_device_class")) 
        self.assertFalse(hasattr(active, "_attr_entity_registry_enabled_default")) # Should NOT generally be False anymore (unless logic change)
        # Actually line 62 in binary_sensor check:
        # _attr_entity_registry_enabled_default = False WAS removed.
        # So hasattr should be False (if not defined) or we check default behavior.
        # Let's just check device class.
        from homeassistant.components.binary_sensor import BinarySensorDeviceClass
        # Note: In unit tests without full Entity platform, property accessors might behave differently 
        # or require registry mocking. We check the internal attribute.
        self.assertEqual(active._attr_device_class, BinarySensorDeviceClass.RUNNING)

    def test_v28_persistence(self):
        """
        Verify v2.8+ persistence logic (Enable Switch).
        """
        hass = MagicMock()
        entry = MagicMock()
        coord = PreheatingCoordinator(hass, entry)
        
        # 1. Test Save
        # Set non-default
        coord.enable_active = False
        coord.cooling_analyzer = MagicMock()
        coord.physics = MagicMock()
        coord.planner = MagicMock()
        # Mock methods to return dicts
        coord.physics.to_dict.return_value = {"mass_factor": 10, "loss_factor": 5, "sample_count": 1}
        coord.planner.to_dict.return_value = {}
        
        data_to_save = coord._get_data_for_storage()
        self.assertIn("enable_active", data_to_save)
        self.assertEqual(data_to_save["enable_active"], False)
        
        # 2. Test Load
        # Mock store.async_load
        coord._store = MagicMock()
        
        # Case A: Legacy (No key) -> Default True
        async def mock_load_legacy():
             return {"some_other_key": 1}
        coord._store.async_load.side_effect = mock_load_legacy
        
        self.run_async(coord.async_load_data())
        self.assertTrue(coord.enable_active)
        
        # Case B: Saved False
        async def mock_load_saved():
             return {"enable_active": False, "physics_version": 2}
        coord._store.async_load.side_effect = mock_load_saved
        
        self.run_async(coord.async_load_data())
        self.assertFalse(coord.enable_active)

if __name__ == "__main__":
    unittest.main()
