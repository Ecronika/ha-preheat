"""Test migration logic."""
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys

# Mock HA
sys.modules["homeassistant"] = MagicMock()
from custom_components.preheat.const import (
    DOMAIN, 
    CONF_PRESET_MODE, 
    CONF_EXPERT_MODE, 
    PRESET_BALANCED,
)
from custom_components.preheat import async_migrate_entry

class TestMigration(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        """Set up test migration environment."""
        helpers = sys.modules.get("homeassistant.helpers")
        if helpers is None:
            helpers = MagicMock()
            sys.modules["homeassistant.helpers"] = helpers
            
        self.mock_dev_reg = MagicMock()
        self.mock_dev_reg.async_get.return_value = self.mock_dev_reg
        self.mock_dev_reg.async_get_device.return_value = None
        
        self.mock_ent_reg = MagicMock()
        def mock_er_async_get(arg):
            if isinstance(arg, str):
                return None
            return self.mock_ent_reg
        self.mock_ent_reg.async_get.side_effect = mock_er_async_get
        self.mock_ent_reg.async_get_entity_id.return_value = None
        
        helpers.device_registry = self.mock_dev_reg
        helpers.entity_registry = self.mock_ent_reg

    async def test_migrate_v1_to_v2(self):
        hass = MagicMock()
        
        entry = MagicMock()
        entry.version = 1
        entry.options = {"some_option": 1}
        entry.data = {}
        
        # We need mock config entries in hass.config_entries.async_entries
        system_entry = MagicMock()
        system_entry.unique_id = "preheat_system"
        system_entry.entry_id = "system_id"
        system_entry.options = {}
        
        entries = [entry]
        hass.config_entries.async_entries.return_value = entries
        
        async def mock_async_init(domain, context):
            entries.append(system_entry)
            
        hass.config_entries.flow.async_init = AsyncMock(side_effect=mock_async_init)
        
        # Mock Persistence
        def update_effect(e, **kwargs):
            if "options" in kwargs: e.options.update(kwargs["options"])
            if "version" in kwargs: e.version = kwargs["version"]
            
        hass.config_entries.async_update_entry.side_effect = update_effect
        
        # Call migration
        await async_migrate_entry(hass, entry)
        
        # Verify update call (v1->v2->v3->v4->v5->v6 = 6 calls total, including system entry update)
        self.assertEqual(hass.config_entries.async_update_entry.call_count, 6)
        
        # Check Final Call (v6)
        last_call_args = hass.config_entries.async_update_entry.call_args
        kwargs = last_call_args[1]
        
        self.assertEqual(kwargs["version"], 6)

    async def test_migrate_v2_to_v3(self):
        hass = MagicMock()
        
        entry = MagicMock()
        entry.version = 2
        entry.options = {"opt": 1}
        entry.data = {"dat": 2} # Data should move to options
        
        system_entry = MagicMock()
        system_entry.unique_id = "preheat_system"
        system_entry.entry_id = "system_id"
        system_entry.options = {}
        
        entries = [entry]
        hass.config_entries.async_entries.return_value = entries
        
        async def mock_async_init(domain, context):
            entries.append(system_entry)
            
        hass.config_entries.flow.async_init = AsyncMock(side_effect=mock_async_init)
        
        def update_entry_spy(e, **kwargs):
            if e == system_entry:
                system_entry.options.update(kwargs.get("options", {}))
            elif e == entry:
                entry.options = kwargs.get("options", entry.options)
                entry.data = kwargs.get("data", entry.data)
                entry.version = kwargs.get("version", entry.version)
                
        hass.config_entries.async_update_entry.side_effect = update_entry_spy
        
        await async_migrate_entry(hass, entry)
        
        self.assertEqual(entry.version, 6)
        self.assertEqual(entry.data, {"dat": 2}) # Data preserved
        self.assertEqual(entry.options["opt"], 1)

    async def test_migrate_v5_to_v6(self):
        hass = MagicMock()
        
        # We need mock config entries in hass.config_entries.async_entries
        system_entry = MagicMock()
        system_entry.unique_id = "preheat_system"
        system_entry.entry_id = "system_id"
        system_entry.options = {}
        
        zone_entry = MagicMock()
        zone_entry.version = 5
        zone_entry.entry_id = "zone_id"
        zone_entry.unique_id = "zone_id"
        zone_entry.options = {
            "global_presence_source": "binary_sensor.presence",
            "arrival_comfort_bias": "comfort",
            "evening_comfort_window": "17:00-22:00",
            "zone_option": "value",
        }
        zone_entry.data = {}
        
        entries = [zone_entry]
        hass.config_entries.async_entries.return_value = entries
        
        async def mock_async_init(domain, context):
            entries.append(system_entry)
            
        hass.config_entries.flow.async_init = AsyncMock(side_effect=mock_async_init)
        
        mock_dev = MagicMock()
        mock_dev.id = "device_id"
        mock_dev.config_entries = {"zone_id"}
        self.mock_dev_reg.async_get_device.return_value = mock_dev
        
        def mock_get_entity_id(platform, domain, unique_id):
            return f"sensor.{unique_id}"
        self.mock_ent_reg.async_get_entity_id.side_effect = mock_get_entity_id
        
        mock_entities = {}
        for uid in ["house_next_arrival", "house_arrival_confidence", "house_arrival_window", "house_incoming"]:
            ent = MagicMock()
            ent.config_entry_id = "zone_id"
            mock_entities[f"sensor.{uid}"] = ent
            
        def mock_er_async_get(arg):
            if isinstance(arg, str):
                return mock_entities.get(arg)
            return self.mock_ent_reg
        self.mock_ent_reg.async_get.side_effect = mock_er_async_get
        
        def update_entry_spy(entry, **kwargs):
            if entry == system_entry:
                system_entry.options.update(kwargs.get("options", {}))
            elif entry == zone_entry:
                zone_entry.options = kwargs.get("options", zone_entry.options)
                zone_entry.data = kwargs.get("data", zone_entry.data)
                zone_entry.version = kwargs.get("version", zone_entry.version)
                
        hass.config_entries.async_update_entry.side_effect = update_entry_spy
        
        await async_migrate_entry(hass, zone_entry)
        
        hass.config_entries.flow.async_init.assert_called_once()
        
        self.mock_dev_reg.async_update_device.assert_called_once_with(
            "device_id",
            add_config_entry_id="system_id",
            remove_config_entry_id="zone_id"
        )
        
        self.assertEqual(self.mock_ent_reg.async_update_entity.call_count, 4)
        for uid in ["house_next_arrival", "house_arrival_confidence", "house_arrival_window", "house_incoming"]:
            self.mock_ent_reg.async_update_entity.assert_any_call(
                f"sensor.{uid}", config_entry_id="system_id"
            )
            
        self.assertEqual(system_entry.options["global_presence_source"], "binary_sensor.presence")
        self.assertEqual(system_entry.options["arrival_comfort_bias"], "comfort")
        self.assertEqual(system_entry.options["evening_comfort_window"], "17:00-22:00")
        
        self.assertNotIn("global_presence_source", zone_entry.options)
        self.assertNotIn("arrival_comfort_bias", zone_entry.options)
        self.assertNotIn("evening_comfort_window", zone_entry.options)
        self.assertEqual(zone_entry.options["zone_option"], "value")
        self.assertEqual(zone_entry.version, 6)
