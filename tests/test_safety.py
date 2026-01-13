import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import timedelta, datetime
import sys
import types

# --- MOCK SETUP START ---
# Mock 'homeassistant' and its submodules aggressively before importing logic
mock_ha = types.ModuleType("homeassistant")
mock_ha.const = types.ModuleType("homeassistant.const")
mock_ha.core = types.ModuleType("homeassistant.core")
mock_ha.config_entries = types.ModuleType("homeassistant.config_entries")
mock_ha.helpers = types.ModuleType("homeassistant.helpers")
mock_ha.util = types.ModuleType("homeassistant.util")
mock_ha.components = types.ModuleType("homeassistant.components")
mock_ha.exceptions = types.ModuleType("homeassistant.exceptions")

# Populate common attributes
mock_ha.const.EVENT_HOMEASSISTANT_START = "homeassistant_start"
mock_ha.const.STATE_ON = "on"
mock_ha.const.STATE_OFF = "off"
mock_ha.const.STATE_UNAVAILABLE = "unavailable"
mock_ha.const.STATE_UNKNOWN = "unknown"
mock_ha.const.UnitOfTemperature = MagicMock()
mock_ha.const.UnitOfTemperature.CELSIUS = "°C"
mock_ha.const.Platform = MagicMock()
mock_ha.const.Platform.SENSOR = "sensor"
mock_ha.const.Platform.CLIMATE = "climate"
mock_ha.const.Platform.BINARY_SENSOR = "binary_sensor"
mock_ha.const.Platform.SWITCH = "switch"
mock_ha.const.Platform.BUTTON = "button"

mock_ha.core.HomeAssistant = MagicMock
mock_ha.core.State = MagicMock
mock_ha.core.callback = MagicMock(side_effect=lambda x: x) # Simplistic decorator
mock_ha.core.ServiceCall = MagicMock
mock_ha.config_entries.ConfigEntry = MagicMock
mock_ha.exceptions.HomeAssistantError = Exception
mock_ha.exceptions.ConfigEntryNotReady = Exception

# Mock basic helpers
mock_ha.helpers.storage = MagicMock()
mock_ha.helpers.event = MagicMock()
mock_ha.helpers.issue_registry = MagicMock()
mock_ha.helpers.translation = MagicMock()
mock_ha.helpers.config_validation = MagicMock()
mock_ha.helpers.entity_platform = MagicMock()
mock_ha.helpers.dispatcher = MagicMock()

# Mock components that might be imported
mock_ha.components.sensor = MagicMock()
mock_ha.components.climate = MagicMock()
mock_ha.components.binary_sensor = MagicMock()
mock_ha.components.switch = MagicMock()

# Link sub-modules
mock_dt = types.ModuleType("homeassistant.util.dt")
mock_dt.utcnow = MagicMock(return_value=datetime(2023, 10, 10, 12, 0, 0))
mock_dt.now = MagicMock(return_value=datetime(2023, 10, 10, 12, 0, 0))
mock_ha.util.dt = mock_dt

sys.modules["homeassistant"] = mock_ha
sys.modules["homeassistant.const"] = mock_ha.const
sys.modules["homeassistant.core"] = mock_ha.core
sys.modules["homeassistant.config_entries"] = mock_ha.config_entries
sys.modules["homeassistant.helpers"] = mock_ha.helpers
sys.modules["homeassistant.util"] = mock_ha.util
sys.modules["homeassistant.util.dt"] = mock_dt
sys.modules["homeassistant.components"] = mock_ha.components
sys.modules["homeassistant.exceptions"] = mock_ha.exceptions
sys.modules["homeassistant.components.sensor"] = mock_ha.components.sensor
sys.modules["homeassistant.components.climate"] = mock_ha.components.climate
sys.modules["homeassistant.components.binary_sensor"] = mock_ha.components.binary_sensor

# Register Helper Submodules
sys.modules["homeassistant.helpers.issue_registry"] = mock_ha.helpers.issue_registry
sys.modules["homeassistant.helpers.config_validation"] = mock_ha.helpers.config_validation
sys.modules["homeassistant.helpers.entity_platform"] = mock_ha.helpers.entity_platform
sys.modules["homeassistant.helpers.dispatcher"] = mock_ha.helpers.dispatcher
sys.modules["homeassistant.helpers.storage"] = mock_ha.helpers.storage
sys.modules["homeassistant.helpers.event"] = mock_ha.helpers.event
sys.modules["homeassistant.helpers.translation"] = mock_ha.helpers.translation

# Pre-Emptive Mocking of Coordinator Dependencies
mock_coord = types.ModuleType("homeassistant.helpers.update_coordinator")

class MockCoordinator:
    def __class_getitem__(cls, item):
        return cls
    def __init__(self, hass, logger, name, update_interval, config_entry):
        # super().__init__() # Removed MagicMock init
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.config_entry = config_entry
        self.data = {} # Real dictionary
        
        self.last_update_success = True
        self.last_exception = None
        self._listeners = []
        
    def async_add_listener(self, update_callback):
        self._listeners.append(update_callback)
        return lambda: self._listeners.remove(update_callback)
        
    async def async_refresh(self):
        pass

mock_coord.DataUpdateCoordinator = MockCoordinator
mock_coord.UpdateFailed = Exception
sys.modules["homeassistant.helpers.update_coordinator"] = mock_coord

sys.modules["homeassistant.helpers.entity_platform"] = MagicMock()
sys.modules["homeassistant.helpers.service"] = MagicMock()

# --- MOCK SETUP END ---

# Now safe to import
from homeassistant.core import HomeAssistant, State
from homeassistant.config_entries import ConfigEntry
from homeassistant.util import dt as dt_util

# System Under Test
from custom_components.preheat.coordinator import PreheatingCoordinator, PreheatData
from custom_components.preheat.const import CONF_OCCUPANCY, CONF_CLIMATE, CONF_TEMPERATURE, DOMAIN

class TestSafetyFeatures(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = MagicMock(spec=HomeAssistant)
        self.hass.states = MagicMock()
        self.hass.bus = MagicMock()
        self.hass.services = MagicMock()
        self.hass.async_create_task = MagicMock()
        
        # Helper for as_local
        mock_dt.as_local = MagicMock(side_effect=lambda x: x)
        
        self.entry = MagicMock() # Removed spec=ConfigEntry to avoid AttributeErrors on missing mocked attrs
        self.entry.entry_id = "test_entry"
        self.entry.title = "Test Zone"
        self.entry.data = {
            CONF_CLIMATE: "climate.test",
            CONF_TEMPERATURE: "sensor.temp",
            CONF_OCCUPANCY: "binary_sensor.occ"
        }
        self.entry.options = {}
        
        self.hass.state = "RUNNING" # Mock State as String for simple check
        
        # Ensure Default State Returns a Valid Mock with .state
        default_state = MagicMock()
        default_state.state = "unknown"
        default_state.last_changed = dt_util.utcnow() # Default to now (mocked)
        self.hass.states.get.return_value = default_state
        
        # Patch internals
        with patch("custom_components.preheat.coordinator.PreheatPlanner") as MockPlanner, \
             patch("custom_components.preheat.coordinator.Store"), \
             patch("custom_components.preheat.coordinator.OptimalStopManager"), \
             patch("custom_components.preheat.coordinator.async_track_state_change_event"):
             
            # Manually inject dt_util to ensure coordinator uses our mock
            import custom_components.preheat.coordinator
            custom_components.preheat.coordinator.dt_util = mock_dt
            
            self.coordinator = PreheatingCoordinator(self.hass, self.entry)
            
            # Configure Planner Mock deeply
            planner_instance = MockPlanner.return_value
            # We need to ensure last_pattern_result has 'confidence' as a float
            p_res = MagicMock()
            p_res.confidence = 1.0
            p_res.pattern_type = "mock_pattern"
            p_res.stability = 1.0
            p_res.modes_found = {}
            p_res.fallback_used = False
            planner_instance.last_pattern_result = p_res
            planner_instance.last_pattern_result = p_res
            self.coordinator.planner = planner_instance
            
            # Physics Mock
            self.coordinator.physics = MagicMock()
            self.coordinator.physics.sample_count = 10
            self.coordinator.physics.avg_error = 2.0
            self.coordinator.physics.mass_factor = 20.0
            self.coordinator.physics.get_confidence.return_value = 50.0
            self.coordinator.physics.calculate_duration.return_value = 30.0 # 30 mins
            self.coordinator.physics.calculate_energy_savings.return_value = 0.0 # Fix NoneType error


        self.coordinator._startup_time = dt_util.utcnow() - timedelta(hours=2)
        
        # Configure hass.states.get side effect to return unique mocks with state per entity_id
        def get_state_side_effect(entity_id):
            m = MagicMock()
            m.state = "unknown"
            m.attributes = {}
            m.last_changed = dt_util.utcnow() # Default to now (mocked)
            m.last_updated = m.last_changed # Fix for AttributeError in stale checks
            
            if entity_id == "sensor.temp":
                 m.state = "20.0"
            if entity_id == "climate.test":
                 m.state = "heat"
                 m.attributes = {"hvac_action": "heating"}
            return m
        
        self.hass.states.get.side_effect = get_state_side_effect
        self.hass.states.is_state = MagicMock(return_value=False) # Fix for Occupancy Check passing erroneously

        self.coordinator.enable_active = False
        self.coordinator._preheat_active = False # Ensure it's false to allow start call
        
        # Mock methods to avoid side effects
        self.coordinator._start_preheat = AsyncMock()
        self.coordinator._stop_preheat = AsyncMock()
        # Removed: self.coordinator._check_diagnostics = AsyncMock() - Need this to run!
        self.coordinator.planner.get_next_scheduled_event = MagicMock(return_value=None)
        self.coordinator.planner.get_next_predicted_departure = MagicMock(return_value=None)
        
    async def test_frost_protection_triggers_when_disabled(self):
        """Test that frost protection overrides disabled state."""
        # 1. Disable System
        self.coordinator.enable_active = False
        self.coordinator._preheat_active = False # Ensure it's false to allow start call
        
        # 2. Mock Low Temp (4.0 C)
        self.hass.states.get.side_effect = None
        mock_temp_state = MagicMock()
        mock_temp_state.state = "4.0"
        mock_temp_state.last_changed = dt_util.utcnow()
        mock_temp_state.last_updated = mock_temp_state.last_changed
        self.hass.states.get.return_value = mock_temp_state
        
        # Mock other dependencies
        self.coordinator._get_operative_temperature = AsyncMock(return_value=4.0)
        self.coordinator._get_target_setpoint = AsyncMock(return_value=20.0)
        self.coordinator._get_outdoor_temp_current = AsyncMock(return_value=0.0)
        
        # Run Update
        await self.coordinator._async_update_data()
        
        # Assertions
        # Should have called _start_preheat because temp 4.0 < 5.0
        self.coordinator._start_preheat.assert_called_once()
        self.assertTrue(self.coordinator._frost_active)

    async def test_frost_protection_releases_when_safe(self):
        """Test that frost protection turns off when temp rises."""
        self.coordinator.enable_active = False
        self.coordinator._frost_active = True # Already active
        
        self.hass.states.get.side_effect = None
        mock_temp_state = MagicMock()
        mock_temp_state.state = "6.0"
        mock_temp_state.last_changed = dt_util.utcnow()
        mock_temp_state.last_updated = mock_temp_state.last_changed
        self.hass.states.get.return_value = mock_temp_state

        # Mock Safe Temp (6.0 C)
        self.coordinator._get_operative_temperature = AsyncMock(return_value=6.0)
        self.coordinator._get_target_setpoint = AsyncMock(return_value=20.0)
        self.coordinator._get_outdoor_temp_current = AsyncMock(return_value=0.0)
        
        # Run Update
        await self.coordinator._async_update_data()
        
        # Should NOT start preheat (disabled and safe)
        self.coordinator._start_preheat.assert_not_called()
        # Should reset flag
        self.assertFalse(self.coordinator._frost_active)

    async def test_stale_sensor_fallback_check(self):
        """Test that Check Diagnostics inspects Climate if no Sensor."""
        # Patch PreheatingCoordinator._get_conf (CLASS LEVEL)
        # Note: side_effect does not receive 'self' when patching class method?
        # Actually it does if passed as method. But here it's function.
        # Arguments passed to mock() call are passed to side_effect.
        # Call: self.coordinator._get_conf(key, default)
        # args: (key, default)
        
        test_self = self
        def side_effect_class_get_conf(key, default=None):
             if key == CONF_TEMPERATURE:
                  return None
             if key == CONF_CLIMATE:
                  return "climate.test_stale"
             # Use test_self.coordinator
             return test_self.coordinator.entry.options.get(key, test_self.coordinator.entry.data.get(key, default))
        
        with patch.object(PreheatingCoordinator, '_get_conf', side_effect=side_effect_class_get_conf):
             # Clear Side Effect so return_value works
             self.hass.states.get.side_effect = None
             
             # Mock Climate State: Stale (>6h)
             # Use mock_dt.utcnow() to verify alignment
             now = mock_dt.utcnow()
             stale_ts = now - timedelta(hours=7)
             
             # Fix Grace Period: Ensure uptime > 30 min
             self.coordinator._startup_time = now - timedelta(hours=1)
             
             stale_state = MagicMock(spec=State)
             stale_state.state = "heat"
             stale_state.last_changed = stale_ts
             stale_state.last_updated = stale_ts
             stale_state.attributes = {"current_temperature": 20}
             self.hass.states.get.return_value = stale_state
             
             # Ensure diagnostics dict is ready
             self.coordinator.diagnostics_data["stale_sensor_counter"] = 0
             
             with patch("custom_components.preheat.coordinator.async_create_issue") as mock_issue:
                  # Ensure outdoor temp is mocked so we don't trip 'no_outdoor_source'
                  self.coordinator._get_outdoor_temp_current = AsyncMock(return_value=10.0)
                  
                  # First Pass (Counter -> 1)
                  await self.coordinator._check_diagnostics()
                  mock_issue.assert_not_called()
                  self.assertEqual(self.coordinator.diagnostics_data["stale_sensor_counter"], 1)
                  
                  # Advance time to bypass Rate Limit (3600s)
                  # Advance by 1 hr + 1 sec
                  mock_dt.utcnow.return_value += timedelta(seconds=3660)
                  
                  # Second Pass (Counter -> 2 -> Error)
                  await self.coordinator._check_diagnostics()
                  
                  self.assertEqual(self.coordinator.diagnostics_data["stale_sensor_counter"], 2)
                  
                  from unittest.mock import ANY
                  from homeassistant.helpers.issue_registry import async_create_issue
                  
                  async_create_issue.assert_any_call(
                      self.hass, DOMAIN, f"stale_sensor_{self.entry.entry_id}",
                      is_fixable=False, is_persistent=True, severity=ANY, 
                      translation_key="stale_sensor", translation_placeholders=ANY
                  )
