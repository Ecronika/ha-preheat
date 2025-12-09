"""Test migration logic."""
import unittest
from unittest.mock import MagicMock, patch
import sys

# Mock HA
sys.modules["homeassistant"] = MagicMock()
from homeassistant.const import CONF_NAME # Mocked?
from custom_components.preheat.const import (
    DOMAIN, 
    CONF_PRESET_MODE, 
    CONF_EXPERT_MODE, 
    PRESET_BALANCED,
    CONF_HEATING_PROFILE
)
from custom_components.preheat import async_migrate_entry

class TestMigration(unittest.IsolatedAsyncioTestCase):
    
    async def test_migrate_v1_to_v2(self):
        hass = MagicMock()
        
        entry = MagicMock()
        entry.version = 1
        entry.options = {"some_option": 1}
        entry.data = {}
        
        # Call migration
        await async_migrate_entry(hass, entry)
        
        # Verify update call
        hass.config_entries.async_update_entry.assert_called_once()
        call_args = hass.config_entries.async_update_entry.call_args
        
        # Check args
        entry_arg = call_args[0][0]
        kwargs = call_args[1]
        
        self.assertEqual(entry_arg, entry)
        self.assertEqual(kwargs["version"], 2)
        self.assertEqual(kwargs["options"][CONF_PRESET_MODE], PRESET_BALANCED)
        self.assertEqual(kwargs["options"][CONF_EXPERT_MODE], True)

    async def test_migrate_v2_to_v3(self):
        hass = MagicMock()
        
        entry = MagicMock()
        entry.version = 2
        entry.options = {"opt": 1}
        entry.data = {"dat": 2} # Data should move to options
        
        await async_migrate_entry(hass, entry)
        
        call_args = hass.config_entries.async_update_entry.call_args
        kwargs = call_args[1]
        
        self.assertEqual(kwargs["version"], 3)
        self.assertEqual(kwargs["data"], {}) # Data cleared
        self.assertEqual(kwargs["options"]["opt"], 1)
        self.assertEqual(kwargs["options"]["dat"], 2) # Moved
        self.assertEqual(kwargs["options"][CONF_PRESET_MODE], PRESET_BALANCED) # Default applied
