"""
Unit Tests for Repair Issues Logic (Diagnostics).
Covers refined logic for v2.9.0-beta9.
"""
import sys
import os
import unittest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, AsyncMock, ANY

# Add parent dir
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# --- MOCK Home Assistant ---
import types
ha = types.ModuleType("homeassistant")
ha.__path__ = []
sys.modules["homeassistant"] = ha

# Setup Module Hierarchy Explicitly
mock_core = MagicMock()
sys.modules["homeassistant.core"] = mock_core
ha.core = mock_core

mock_config_entries = MagicMock()
sys.modules["homeassistant.config_entries"] = mock_config_entries
ha.config_entries = mock_config_entries

mock_const = MagicMock()
sys.modules["homeassistant.const"] = mock_const
ha.const = mock_const
# Define Core Constants
mock_const.STATE_OFF = "off"
mock_const.STATE_ON = "on"
mock_const.STATE_UNAVAILABLE = "unavailable"
mock_const.STATE_UNKNOWN = "unknown"

mock_util = MagicMock()
sys.modules["homeassistant.util"] = mock_util
ha.util = mock_util

# Mock dt_util with REAL datetime method for test control
mock_dt = MagicMock()
mock_dt.UTC = timezone.utc
# Default side_effect returns real UTC now unless overriden
mock_dt.utcnow.side_effect = lambda: datetime.now(timezone.utc)
mock_dt.as_utc.side_effect = lambda d: d

sys.modules["homeassistant.util.dt"] = mock_dt
mock_util.dt = mock_dt # Link it!

mock_helpers = MagicMock()
sys.modules["homeassistant.helpers"] = mock_helpers
ha.helpers = mock_helpers

mock_event = MagicMock()
sys.modules["homeassistant.helpers.event"] = mock_event
mock_helpers.event = mock_event

mock_storage = MagicMock()
sys.modules["homeassistant.helpers.storage"] = mock_storage
mock_helpers.storage = mock_storage

mock_issue_registry = MagicMock()
sys.modules["homeassistant.helpers.issue_registry"] = mock_issue_registry
mock_helpers.issue_registry = mock_issue_registry

mock_exceptions = MagicMock()
sys.modules["homeassistant.exceptions"] = mock_exceptions
ha.exceptions = mock_exceptions

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

class MockUpdateFailed(Exception): pass

mock_duc_mod = MagicMock()
mock_duc_mod.DataUpdateCoordinator = MockDataUpdateCoordinator
mock_duc_mod.UpdateFailed = MockUpdateFailed
sys.modules["homeassistant.helpers.update_coordinator"] = mock_duc_mod
mock_helpers.update_coordinator = mock_duc_mod

# Import Component
from custom_components.preheat.coordinator import PreheatingCoordinator
from homeassistant.helpers.issue_registry import IssueSeverity

class TestRepairIssuesLogic(unittest.TestCase):
    """Test Logic for Repair Issues."""
    
    def setUp(self):
        self.hass = MagicMock()
        self.entry = MagicMock()
        self.entry.entry_id = "test_entry"
        self.entry.options = {}
        self.entry.data = {}
        
        # Patch local mock_dt into coordinator for THIS test class
        self.patcher = patch("custom_components.preheat.coordinator.dt_util", mock_dt)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        
        # Patch init to control startup_time
        with patch("custom_components.preheat.coordinator.PreheatingCoordinator._setup_listeners"), \
             patch("custom_components.preheat.coordinator.PreheatingCoordinator.async_load_data"):
             self.coord = PreheatingCoordinator(self.hass, self.entry)
        
        # Set Startup Time to 2 hours ago (to pass uptime check)
        # Use mocked dt logic
        self.coord._startup_time = datetime.now(timezone.utc) - timedelta(hours=2)
        
        # Manually init diagnostics data
        self.coord.diagnostics_data = {}
        
        # Mock Issue Registry calls
        self.mock_create_issue = MagicMock()
        self.mock_delete_issue = MagicMock()
        
        # Mock sys.modules for import inside method
        sys.modules["homeassistant.helpers.issue_registry"].async_create_issue = self.mock_create_issue
        sys.modules["homeassistant.helpers.issue_registry"].async_delete_issue = self.mock_delete_issue
        
        # Mock dependencies
        self.coord.physics = MagicMock()
        self.coord.physics.sample_count = 0 
        self.coord.physics.avg_error = 0.0
        self.coord.physics.get_confidence.return_value = 0
        self.coord.physics.mass_factor = 100.0 # Safe value (>30 to avoid max_coast alert)
        self.coord.physics.min_mass = 1.0
        self.coord.physics.max_mass = 100.0
        self.coord.physics.loss_factor = 10.0
        
        self.coord.hold_active = False
        self.coord._preheat_active = False
        self.coord._external_inhibit = False
        
        self.coord.weather_service = MagicMock()
        self.coord.weather_service._cache_ts = None
        
        self.coord.planner = MagicMock()
        
        # Mock valve position helper
        self.coord._get_valve_position = MagicMock(return_value=None)
        
        # Mock _get_conf to return default if provided, else None or Mock IDs
        def get_conf_side_effect(key, default=None):
            if key == "temperature_sensor": return "sensor.indoor"
            if key == "outdoor_temp_sensor": return "sensor.outdoor"
            if key == "weather_entity": return "weather.home"
            if key == "occupancy_sensor": return "binary_sensor.occ"
            if key == "max_coast_hours": return 2.0 # Suppress High Coast
            return default
        self.coord._get_conf = MagicMock(side_effect=get_conf_side_effect) 
        
        # -- ROBUST STATE MOCK --
        # Ensure hass.states.get returns a valid object by default to prevent TypeErrors in Stale Check
        self.default_state = MagicMock()
        self.default_state.state = "20.0"
        self.default_state.last_changed = datetime.now(timezone.utc)
        self.default_state.last_updated = datetime.now(timezone.utc)
        self.default_state.attributes = {"unit_of_measurement": "°C", "device_class": "temperature"}
        self.hass.states.get.return_value = self.default_state 
        
    def test_physics_railing_refined(self):
        """Test refined Physics Check (Check 1)."""
        async def run():
            p = self.coord.physics
            # Case 1: Not enough samples
            p.sample_count = 10
            p.avg_error = 15.0 # High error
            p.mass_factor = 0.5 # Low mass (Limit)
            p.min_mass = 1.0
            p.max_mass = 100.0
            p.loss_factor = 10.0
            p.get_confidence.return_value = 50
            
            # Ensure max_coast_high doesn't trigger (Condition: mass < 30).
            # Here mass IS < 30 (0.5). So it WOULD trigger.
            # We must suppress it by mocking CONF_MAX_COAST_HOURS to 2.0 (below 3.0 trigger).
            # self.coord._get_conf.side_effect = lambda k, d=None: 2.0 if k == "max_coast_hours" else (d if d is not None else None)
            # handled by main mock
            
            await self.coord._check_diagnostics()
            # Use any_call to ignore others
            # Ensure NO call for 'physics_limit_mass_min'
            # We can iterate calls and check keys
            calls = self.mock_create_issue.call_args_list
            self.assertFalse(any(c[0][2].startswith("physics_limit") for c in calls))
            
            # Case 2: Enough samples (16), High Error -> TRIGGER
            p.sample_count = 16
            
            # Reset rate limit
            self.coord.diagnostics_data["last_check_ts"] = 0
            await self.coord._check_diagnostics()
            self.mock_create_issue.assert_any_call(
                self.hass, "preheat", "physics_limit_test_entry",
                is_fixable=False, is_persistent=True, severity=ANY,
                translation_key="physics_limit_mass_min", translation_placeholders={"current": "0.5"}
            )
            self.mock_create_issue.reset_mock()
            
            # Case 3: Enough samples, Low Error, Low Confidence -> NO TRIGGER
            p.avg_error = 5.0
            p.get_confidence.return_value = 10
            
            self.coord.diagnostics_data["last_check_ts"] = 0
            await self.coord._check_diagnostics()
            calls = self.mock_create_issue.call_args_list
            self.assertFalse(any(c[0][2].startswith("physics_limit") for c in calls))
            
            # Case 4: Enough samples, Low Error, High Confidence -> TRIGGER
            p.get_confidence.return_value = 30
            self.coord.diagnostics_data["last_check_ts"] = 0
            await self.coord._check_diagnostics()
            # Verify call
            self.assertTrue(any(c[0][2].startswith("physics_limit") for c in self.mock_create_issue.call_args_list))
            
        asyncio.run(run())

    def test_occupancy_adaptive(self):
        """Test Adaptive Occupancy Threshold (Check 5)."""
        async def run():
            now = datetime(2023, 1, 10, 12, 0, 0, tzinfo=timezone.utc)
            self.coord._startup_time = now - timedelta(hours=2) # Reset startup time relative to NOW
            
            # Override Mock DT
            mock_dt.utcnow.side_effect = None
            mock_dt.utcnow.return_value = now
            
            
            try:
                # Override states.get to return OFF for occupancy logic
                occ_state = MagicMock()
                occ_state.state = "off"
                occ_state.last_updated = now # Default
                
                def get_state_occ(eid):
                    if eid == "binary_sensor.occ": return occ_state
                    return self.default_state
                self.hass.states.get.side_effect = get_state_occ
                
                # Case 1: OFF for 4 days (Limit 3 days) -> Trigger
                self.coord.diagnostics_data["occupancy_last_change_ts"] = (now - timedelta(days=4)).timestamp()
                self.coord.diagnostics_data["last_occ_state"] = "off"
                
                self.coord.diagnostics_data["occupancy_last_change_ts"] = (now - timedelta(days=4)).timestamp()
                self.coord.diagnostics_data["last_occ_state"] = "off"
                
                await self.coord._check_diagnostics()
                self.mock_create_issue.assert_any_call(
                    self.hass, "preheat", "occupancy_stale_test_entry",
                    is_fixable=False, is_persistent=True, severity=ANY,
                    translation_key="occupancy_stale", translation_placeholders=None
                )
                self.mock_create_issue.reset_mock()
                
                # Case 2: ON for 4 days (Limit 7 days) -> No Trigger
                occ_state.state = "on"
                self.coord.diagnostics_data["last_occ_state"] = "on"
                self.coord.diagnostics_data["occupancy_last_change_ts"] = (now - timedelta(days=4)).timestamp()
                
                self.coord.diagnostics_data["last_check_ts"] = 0
                await self.coord._check_diagnostics()
                # Check occupancy_stale NOT called
                calls = self.mock_create_issue.call_args_list
                self.assertFalse(any(c[0][2] == "occupancy_stale_test_entry" for c in calls))
                
                 # Case 3: ON for 8 days (Limit 7 days) -> Trigger
                self.coord.diagnostics_data["occupancy_last_change_ts"] = (now - timedelta(days=8)).timestamp()
                self.coord.diagnostics_data["last_check_ts"] = 0
                await self.coord._check_diagnostics()
                self.mock_create_issue.assert_called() # At least one issue (likely occupancy)
            finally:
                # Cleanup Side Effect
                mock_dt.utcnow.side_effect = lambda: datetime.now(timezone.utc)


        asyncio.run(run())

    def test_temp_sanity_refined(self):
        """Test Temp Sanity with Heating Guard (Check 10)."""
        async def run():
            self.coord._get_conf.side_effect = lambda k, d=None: "sensor.in" if k == "temperature_sensor" else ("sensor.out" if k == "outdoor_temp_sensor" else d)
            
            s_in = MagicMock()
            s_in.state = "20.0"
            s_in.last_updated = datetime(2023, 1, 10, 11, 0, 0, tzinfo=timezone.utc) # 1h ago
            s_in.last_changed = s_in.last_updated # FIX: Set last_changed too
            s_in.attributes = {"unit_of_measurement": "°C", "device_class": "temperature"}
            s_out = MagicMock()
            s_out.state = "20.0" # Identical!
            s_out.last_updated = datetime(2023, 1, 10, 11, 0, 0, tzinfo=timezone.utc)
            s_out.last_changed = s_out.last_updated
            s_out.attributes = {"unit_of_measurement": "°C", "device_class": "temperature"}
            
            s_in = MagicMock()
            s_in.state = "20.0"
            s_in.last_updated = datetime(2023, 1, 10, 11, 0, 0, tzinfo=timezone.utc) # 1h ago
            s_in.last_changed = s_in.last_updated 
            s_in.attributes = {"unit_of_measurement": "°C", "device_class": "temperature"}
            s_out = MagicMock()
            s_out.state = "20.0" # Identical!
            s_out.last_updated = datetime(2023, 1, 10, 11, 0, 0, tzinfo=timezone.utc)
            s_out.last_changed = s_out.last_updated
            s_out.attributes = {"unit_of_measurement": "°C", "device_class": "temperature"}
            
            def get_state(eid):
                if eid == "sensor.indoor": return s_in
                if eid == "sensor.outdoor": return s_out
                # Return default for others to avoid TypeErrors in other checks
                return self.default_state
            self.hass.states.get.side_effect = get_state
            
            # Case 1: Heating Active -> No Trigger even if identical
            self.coord._preheat_active = True
            
            # Run 13 times (Limit 12)
            self.coord.diagnostics_data["sanity_swap_counter"] = 12
            
            # Since heating is active, counter should reset to 0
            await self.coord._check_diagnostics()
            # Assert sanity_temp NOT called
            calls = self.mock_create_issue.call_args_list
            self.assertFalse(any(c[0][2].startswith("sanity_temp") for c in calls))
            self.assertEqual(self.coord.diagnostics_data["sanity_swap_counter"], 0)
            
            # Case 2: Heating Inactive -> Trigger after debounce
            self.coord._preheat_active = False
            self.coord.diagnostics_data["sanity_swap_counter"] = 12
            
            self.coord.diagnostics_data["last_check_ts"] = 0
            await self.coord._check_diagnostics()
            self.mock_create_issue.assert_any_call(
                self.hass, "preheat", "sanity_temp_test_entry",
                is_fixable=False, is_persistent=True, severity=ANY,
                translation_key="sanity_temp_swap", translation_placeholders=None
            )

        asyncio.run(run())

    def test_forecast_stale_and_valve_saturation(self):
        """Test Checks 14 and 15."""
        async def run():
            now = datetime(2023, 1, 10, 12, 0, 0, tzinfo=timezone.utc)
            ts_now = now.timestamp()
            self.coord._startup_time = now - timedelta(hours=2)

            # Override Mock DT
            mock_dt.utcnow.side_effect = None
            mock_dt.utcnow.return_value = now
            
            try:
                # -- Check 14: Forecast Stale --
                # Stale (3 hours old)
                self.coord.weather_service._cache_ts = now - timedelta(hours=3)
                
                await self.coord._check_diagnostics()
                self.mock_create_issue.assert_any_call(
                    self.hass, "preheat", "forecast_stale_test_entry",
                    is_fixable=False, is_persistent=True, severity=ANY,
                    translation_key="forecast_stale", translation_placeholders=None
                )
                self.mock_create_issue.reset_mock()
                
                # Fresh (1 hour old)
                self.coord.weather_service._cache_ts = now - timedelta(hours=1)
                self.coord.diagnostics_data["last_check_ts"] = 0
                await self.coord._check_diagnostics()
                self.mock_delete_issue.assert_any_call(self.hass, "preheat", "forecast_stale_test_entry") 
                
                # -- Check 15: Valve Saturation --
                self.coord._get_valve_position.return_value = 96.0
                
                # First pass: Sets TS
                self.coord.diagnostics_data["valve_saturation_ts"] = None
                self.coord.diagnostics_data["last_check_ts"] = 0
                await self.coord._check_diagnostics()
                self.assertIsNotNone(self.coord.diagnostics_data["valve_saturation_ts"])
                self.mock_create_issue.assert_not_called()
                
                # Second pass: 4 hours later -> Trigger
                # Determine what TS was set
                ts_set = self.coord.diagnostics_data["valve_saturation_ts"]
                # Force it to be old
                self.coord.diagnostics_data["valve_saturation_ts"] = ts_set - 14400 # 4h ago
                
                self.coord.diagnostics_data["last_check_ts"] = 0
                await self.coord._check_diagnostics()
                self.mock_create_issue.assert_any_call(
                    self.hass, "preheat", "valve_saturation_test_entry",
                    is_fixable=False, is_persistent=True, severity=ANY,
                    translation_key="valve_saturation", translation_placeholders=None
                )
            finally:
                mock_dt.utcnow.side_effect = lambda: datetime.now(timezone.utc)

        asyncio.run(run())
        
if __name__ == "__main__":
    unittest.main()
