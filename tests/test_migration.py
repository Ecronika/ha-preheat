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
        
        # Mock Persistence
        def update_effect(e, **kwargs):
            if "options" in kwargs: e.options.update(kwargs["options"])
            if "version" in kwargs: e.version = kwargs["version"]
            
        hass.config_entries.async_update_entry.side_effect = update_effect
        
        # Call migration
        await async_migrate_entry(hass, entry)
        
        # Verify update call (Called twice: v1->v2, v2->v3)
        self.assertEqual(hass.config_entries.async_update_entry.call_count, 2)
        
        # Check Final Call (v3)
        last_call_args = hass.config_entries.async_update_entry.call_args
        kwargs = last_call_args[1]
        
        self.assertEqual(kwargs["version"], 3)
        self.assertEqual(kwargs["options"][CONF_PRESET_MODE], PRESET_BALANCED)
        # Note: v3 logic ensures Expert Mode is False (Simple) if not present, checking implementation logic
        # v1->v2 set Expert=True. v2->v3 keeps options. So it should be True.
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
        self.assertEqual(kwargs["data"], {"dat": 2}) # Data preserved
        self.assertEqual(kwargs["options"]["opt"], 1)
        self.assertEqual(kwargs["options"][CONF_PRESET_MODE], PRESET_BALANCED) # Default applied
