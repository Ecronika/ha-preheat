
import unittest
import importlib
import pkgutil
import os
import sys
import dataclasses
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import timedelta

# Mock dependencies before importing integration
sys.modules['homeassistant'] = MagicMock()
sys.modules['homeassistant.core'] = MagicMock()
sys.modules['homeassistant.config_entries'] = MagicMock()
sys.modules['homeassistant.const'] = MagicMock()
sys.modules['homeassistant.helpers'] = MagicMock()
# Deep Mock for components with real classes to avoid Metaclass conflicts
class MockEntity:
    pass

@dataclasses.dataclass(frozen=True)
class MockEntityDescription:
    key: str | None = None
    device_class: str | None = None
    entity_category: str | None = None
    entity_registry_enabled_default: bool = True
    entity_registry_visible_default: bool = True
    force_update: bool = False
    icon: str | None = None
    has_entity_name: bool = False
    name: str | None = None
    translation_key: str | None = None
    unit_of_measurement: str | None = None

class MockBinarySensorEntity(MockEntity):
    pass

class MockSensorEntity(MockEntity):
    pass

class MockCoordinatorEntity(MockEntity):
    def __init__(self, coordinator):
        self.coordinator = coordinator
    def __class_getitem__(cls, item): return cls

class MockDataUpdateCoordinator:
    def __init__(self, hass, logger, name, update_interval=None, **kwargs):
        self.hass = hass
        self.logger = logger
        self.name = name
    async def _async_update_data(self): pass
    def __class_getitem__(cls, item): return cls

# Patch sys modules
sys.modules['homeassistant.helpers.update_coordinator'] = MagicMock()
sys.modules['homeassistant.helpers.update_coordinator'].DataUpdateCoordinator = MockDataUpdateCoordinator
sys.modules['homeassistant.helpers.update_coordinator'].CoordinatorEntity = MockCoordinatorEntity

# Restore other helpers
sys.modules['homeassistant.helpers.event'] = MagicMock()
sys.modules['homeassistant.helpers.storage'] = MagicMock()
sys.modules['homeassistant.helpers.issue_registry'] = MagicMock()
sys.modules['homeassistant.helpers.device_registry'] = MagicMock() # Added
sys.modules['homeassistant.data_entry_flow'] = MagicMock() # Added
sys.modules['homeassistant.util'] = MagicMock()
sys.modules['homeassistant.util.dt'] = MagicMock()

# Patch components
components_mock = MagicMock()
components_mock.binary_sensor = MagicMock()
components_mock.binary_sensor.BinarySensorEntity = MockBinarySensorEntity
components_mock.binary_sensor.BinarySensorDeviceClass = MagicMock()

components_mock.sensor = MagicMock()
components_mock.sensor.SensorEntity = MockSensorEntity
components_mock.sensor.SensorDeviceClass = MagicMock()
components_mock.sensor.SensorStateClass = MagicMock()

components_mock.button = MagicMock()
components_mock.button.ButtonEntity = MockEntity
components_mock.button.ButtonEntityDescription = MockEntityDescription
components_mock.button.ButtonDeviceClass = MagicMock()

components_mock.diagnostics = MagicMock() # Added

components_mock.switch = MagicMock()
components_mock.switch.SwitchEntity = MockEntity
components_mock.switch.SwitchDeviceClass = MagicMock()

sys.modules['homeassistant.components'] = components_mock
sys.modules['homeassistant.components.binary_sensor'] = components_mock.binary_sensor
sys.modules['homeassistant.components.sensor'] = components_mock.sensor
sys.modules['homeassistant.components.button'] = components_mock.button
sys.modules['homeassistant.components.diagnostics'] = components_mock.diagnostics
sys.modules['homeassistant.components.switch'] = components_mock.switch # Added # Added

import custom_components.preheat
from custom_components.preheat.coordinator import PreheatingCoordinator
from custom_components.preheat.const import DOMAIN

class TestResilience(unittest.TestCase):
    """
    Resilience tests to prevent regressions found in v2.6.0-beta phase.
    Covers: Import errors, Legacy/Empty Configs, Corrupted Data.
    """

    def test_import_all_modules(self):
        """
        Verify that all modules in the package can be imported without error.
        Catches: IndentationError, NameError (missing imports), SyntaxError.
        """
        package = custom_components.preheat
        path = package.__path__
        prefix = package.__name__ + "."

        for _, name, _ in pkgutil.walk_packages(path, prefix):
            try:
                importlib.import_module(name)
            except Exception as e:
                self.fail(f"Failed to import module '{name}': {e}")

    def test_coordinator_legacy_config(self):
        """Wrapper for async test."""
        async def run_test():
            hass = MagicMock()
            entry = MagicMock()
            entry.entry_id = "test_legacy"
            # EMPTY Options and Data (Worst case scenario)
            entry.options = {} 
            entry.data = {}
            
            # Init Coordinator
            coord = PreheatingCoordinator(hass, entry)
            
            # Now verify _get_conf returns defaults
            from custom_components.preheat.const import CONF_MAX_COAST_HOURS, DEFAULT_MAX_COAST_HOURS
            val = coord._get_conf(CONF_MAX_COAST_HOURS, DEFAULT_MAX_COAST_HOURS)
            self.assertIsNotNone(val)
            self.assertEqual(val, DEFAULT_MAX_COAST_HOURS)
            
            # Verify no crash during property access
            _ = coord.optimal_stop_manager
            
        import asyncio
        asyncio.run(run_test())

    def test_physics_resilience_to_nulls(self):
        """
        Verify Physics module handles corrupted (None) data.
        Ref: v2.6.0-beta18 fix.
        """
        from custom_components.preheat.physics import ThermalPhysics, ThermalModelData
        
        # 1. Corrupted Data Object (Fields explicitly None)
        bad_data = MagicMock()
        bad_data.mass_factor = None
        bad_data.loss_factor = None
        bad_data.sample_count = 5
        bad_data.avg_error = None
        bad_data.deadtime = None
        
        # 2. Initialize
        physics = ThermalPhysics(data=bad_data)
        
        # 3. Assert Defaults Applied
        self.assertIsNotNone(physics.mass_factor)
        self.assertIsNotNone(physics.loss_factor)
        self.assertIsNotNone(physics.deadtime)
        self.assertEqual(physics.deadtime, 0.0) # Fallback
        
        # 4. Assert Calculation (Runtime)
        # Should not crash with TypeError
        duration = physics.calculate_duration(20.0, 5.0)
        self.assertIsInstance(duration, float)

if __name__ == "__main__":
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Run sync tests
    unittest.main(exit=False)
