"""Test the Preheat config flow Logic."""
import unittest
from unittest.mock import MagicMock, patch
import sys
import types

# --- MOCK Home Assistant ---
# We must setup mocks with string constants BEFORE they are imported by the component
mock_const = MagicMock()
mock_const.CONF_NAME = "name"
sys.modules["homeassistant.const"] = mock_const

mock_ha = MagicMock()
sys.modules["homeassistant"] = mock_ha
sys.modules["homeassistant.config_entries"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.data_entry_flow"] = MagicMock()
sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.helpers.selector"] = MagicMock()

import homeassistant
from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResultType

# Import local constants
from custom_components.preheat.const import (
    DOMAIN,
    CONF_OCCUPANCY,
    CONF_CLIMATE,
    CONF_TEMPERATURE,
    CONF_ENABLE_OPTIMAL_STOP,
    CONF_SCHEDULE_ENTITY,
    CONF_HEATING_PROFILE,
    PROFILE_RADIATOR_NEW,
    CONF_PRESET_MODE,
    PRESET_BALANCED,
    CONF_EXPERT_MODE,
)

# Mock Shims 
class MockConfigFlow:
    """Shim for ConfigFlow."""
    def __init__(self):
        self.context = {}
    
    def __init_subclass__(cls, **kwargs):
        pass

class MockOptionsFlow:
    """Shim for OptionsFlow."""
    def __init__(self, config_entry):
        self.config_entry = config_entry

homeassistant.config_entries.ConfigFlow = MockConfigFlow
homeassistant.config_entries.OptionsFlow = MockOptionsFlow

# Import local constants
from custom_components.preheat.config_flow import PreheatingConfigFlow, PreheatingOptionsFlow

class TestConfigFlow(unittest.IsolatedAsyncioTestCase):
    """Test Config and Options Flow Logic."""

    async def asyncSetUp(self):
        """Setup for async tests."""
        self.hass = MagicMock()
        self.hass.config_entries = MagicMock()
        self.hass.config_entries.flow.async_init = MagicMock()
        self.hass.config_entries.flow.async_configure = MagicMock()
        
        from homeassistant.helpers import selector
        
        def entity_selector_config_side_effect(**kwargs):
            return kwargs
            
        def entity_selector_side_effect(config):
            m = MagicMock()
            m.config = config
            return m
            
        selector.EntitySelectorConfig.side_effect = entity_selector_config_side_effect
        selector.EntitySelector.side_effect = entity_selector_side_effect

        self.flow = PreheatingConfigFlow()
        self._inject_methods(self.flow)

    def _inject_methods(self, obj):
        """Inject helper methods into flow object."""
        obj.async_create_entry = MagicMock(return_value={"type": FlowResultType.CREATE_ENTRY})
        
        def show_form_side_effect(**kwargs):
            return {"type": FlowResultType.FORM, "errors": {}, **kwargs}
            
        obj.async_show_form = MagicMock(side_effect=show_form_side_effect)
        obj.add_suggested_values_to_schema = MagicMock(side_effect=lambda schema, _: schema)
        obj.async_update_reload_and_abort = MagicMock()
        obj.hass = self.hass
        
    async def test_setup_with_optimal_stop_and_schedule(self):
        """Test setting up with Optimal Stop enabled and Schedule provided."""
        result = await self.flow.async_step_user()
        self.assertEqual(result["type"], FlowResultType.FORM)
        
        user_input = {
            CONF_NAME: "Test Zone",
            CONF_OCCUPANCY: "binary_sensor.occupancy",
            CONF_CLIMATE: "climate.thermostat",
            CONF_HEATING_PROFILE: PROFILE_RADIATOR_NEW,
            CONF_ENABLE_OPTIMAL_STOP: True,
            CONF_SCHEDULE_ENTITY: "schedule.my_schedule"
        }
        
        self.flow.async_create_entry.return_value = {"type": FlowResultType.CREATE_ENTRY, "result": "created"}
        self.flow.async_create_entry.reset_mock() 

        result = await self.flow.async_step_user(user_input)
            
        self.flow.async_create_entry.assert_called_once()
        call_args = self.flow.async_create_entry.call_args[1]
        data = call_args["data"]
        options = call_args["options"]
            
        self.assertEqual(data[CONF_OCCUPANCY], "binary_sensor.occupancy")
        self.assertTrue(options[CONF_ENABLE_OPTIMAL_STOP])

    async def test_setup_with_optimal_stop_missing_schedule(self):
        """Test that missing schedule is ALLOWED (Fall back to Observer)."""
        await self.flow.async_step_user()
        
        user_input = {
            CONF_NAME: "Test Zone",
            CONF_OCCUPANCY: "binary_sensor.occupancy",
            CONF_CLIMATE: "climate.thermostat",
            CONF_HEATING_PROFILE: PROFILE_RADIATOR_NEW,
            CONF_ENABLE_OPTIMAL_STOP: True,
        }
        
        self.flow.async_create_entry.return_value = {"type": FlowResultType.CREATE_ENTRY, "result": "created"}
        self.flow.async_create_entry.reset_mock()
        
        # Should now SUCCEED, not fail
        await self.flow.async_step_user(user_input)
        
        self.flow.async_create_entry.assert_called_once()


    async def test_setup_without_optimal_stop(self):
        """Test without optimal stop (Schedule not required)."""
        await self.flow.async_step_user()
        
        user_input = {
            CONF_NAME: "Test Zone",
            CONF_OCCUPANCY: "binary_sensor.occupancy",
            CONF_CLIMATE: "climate.thermostat",
            CONF_HEATING_PROFILE: PROFILE_RADIATOR_NEW,
            CONF_ENABLE_OPTIMAL_STOP: False,
        }
        
        self.flow.async_create_entry.return_value = {"type": FlowResultType.CREATE_ENTRY}
        self.flow.async_create_entry.reset_mock()

        await self.flow.async_step_user(user_input)
            
        self.flow.async_create_entry.assert_called_once()
        options = self.flow.async_create_entry.call_args[1]["options"]
        self.assertFalse(options.get(CONF_ENABLE_OPTIMAL_STOP))

    async def test_options_flow_visibility(self):
        """Verify options flow schema visibility."""
        entry = MagicMock()
        entry.data = {}
        entry.options = {CONF_ENABLE_OPTIMAL_STOP: False, CONF_EXPERT_MODE: False}
        
        options_flow = PreheatingOptionsFlow(entry)
        options_flow.context = {}
        self._inject_methods(options_flow)
        
        result = await options_flow.async_step_init()
        
        self.assertEqual(result["type"], FlowResultType.FORM)
        schema = result["data_schema"]
        
        found = False
        for key in schema.schema:
            if str(key) == CONF_SCHEDULE_ENTITY:
                found = True
                break
        self.assertTrue(found)

    async def test_options_flow_validation(self):
        """Verify options flow validation."""
        entry = MagicMock()
        entry.data = {}
        entry.options = {CONF_ENABLE_OPTIMAL_STOP: False, CONF_EXPERT_MODE: False}
        
        options_flow = PreheatingOptionsFlow(entry)
        self._inject_methods(options_flow)
        
        # 1. Submit valid (Missing schedule is now ignored/allowed)
        user_input = {CONF_ENABLE_OPTIMAL_STOP: True}
        options_flow.async_create_entry.return_value = {"type": FlowResultType.CREATE_ENTRY, "data": user_input}
        
        result = await options_flow.async_step_init(user_input)
        self.assertEqual(result["type"], FlowResultType.CREATE_ENTRY)
        
        # 2. Submit Valid
        user_input = {CONF_ENABLE_OPTIMAL_STOP: True, CONF_SCHEDULE_ENTITY: "schedule.test"}
        options_flow.async_create_entry.return_value = {"type": FlowResultType.CREATE_ENTRY, "data": user_input}
        
        result = await options_flow.async_step_init(user_input)
        
        self.assertEqual(result["type"], FlowResultType.CREATE_ENTRY)
