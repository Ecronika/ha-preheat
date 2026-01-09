"""Test Action 2.3: UX Simplification Defaults."""
from unittest.mock import MagicMock, patch
import unittest
import sys

# MOCK Home Assistant
mock_hass = MagicMock()
sys.modules['homeassistant'] = mock_hass
sys.modules['homeassistant.config_entries'] = MagicMock()
sys.modules['homeassistant.const'] = MagicMock()
sys.modules['homeassistant.core'] = MagicMock()
sys.modules['homeassistant.exceptions'] = MagicMock()
sys.modules['homeassistant.helpers'] = MagicMock()
sys.modules['homeassistant.helpers.storage'] = MagicMock()

# Create a Dummy Coordinator to inherit from
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
sys.modules['homeassistant.helpers.event'] = MagicMock()
sys.modules['homeassistant.helpers.issue_registry'] = MagicMock()
sys.modules['homeassistant.util'] = MagicMock()

from custom_components.preheat.coordinator import PreheatingCoordinator
from custom_components.preheat.const import (
    CONF_HEATING_PROFILE, PROFILE_RADIATOR_NEW, HEATING_PROFILES,
    CONF_PHYSICS_MODE, PHYSICS_STANDARD, PHYSICS_ADVANCED,
    CONF_USE_FORECAST, CONF_WEATHER_ENTITY,
    CONF_INITIAL_GAIN, CONF_MAX_PREHEAT_HOURS,
    CONF_RISK_MODE, RISK_BALANCED, CONF_EMA_ALPHA
)

class TestConfigDefaults(unittest.TestCase):
    
    def setUp(self):
        self.entry = MagicMock()
        self.entry.entry_id = "test_entry"
        self.entry.title = "Test Device"
        self.entry.options = {} # Symulate Action 2.3: Options stripped
        self.entry.data = {
            CONF_HEATING_PROFILE: PROFILE_RADIATOR_NEW
        }
        self.hass = MagicMock()
        
    def test_profile_defaults(self):
        """Test that missing params fall back to Profile."""
        coord = PreheatingCoordinator(self.hass, self.entry)
        
        # Test Gain (removed from Expert)
        gain = coord._get_conf(CONF_INITIAL_GAIN, None)
        expected_gain = HEATING_PROFILES[PROFILE_RADIATOR_NEW]["default_mass"]
        self.assertEqual(gain, expected_gain, "Should derive Gain from Profile")
        
        # Test Max Preheat (removed from Expert)
        max_ph = coord._get_conf(CONF_MAX_PREHEAT_HOURS, None)
        expected_ph = HEATING_PROFILES[PROFILE_RADIATOR_NEW]["max_duration"]
        self.assertEqual(max_ph, expected_ph, "Should derive Max Preheat from Profile")

    def test_context_detection(self):
        """Test Physics Mode auto-detection."""
        # 1. No Weather
        coord = PreheatingCoordinator(self.hass, self.entry)
        mode = coord._get_conf(CONF_PHYSICS_MODE, None)
        self.assertEqual(mode, PHYSICS_STANDARD, "Should default to Standard without weather")
        
        # 2. With Weather
        self.entry.data[CONF_WEATHER_ENTITY] = "weather.home"
        coord_w = PreheatingCoordinator(self.hass, self.entry)
        mode_w = coord_w._get_conf(CONF_PHYSICS_MODE, None)
        self.assertEqual(mode_w, PHYSICS_ADVANCED, "Should upgrade to Advanced with weather")
        
        # 3. Use Forecast
        use_f = coord_w._get_conf(CONF_USE_FORECAST, None)
        self.assertTrue(use_f, "Should enable forecast if weather present")

    def test_hardcoded_defaults(self):
        """Test strict simplification defaults."""
        coord = PreheatingCoordinator(self.hass, self.entry)
        
        self.assertEqual(coord._get_conf(CONF_RISK_MODE, None), RISK_BALANCED)
        self.assertEqual(coord._get_conf(CONF_EMA_ALPHA, None), 0.3)
