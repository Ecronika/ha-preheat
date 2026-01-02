import sys
import types
from unittest.mock import MagicMock
import pytest

# Global Mock for Home Assistant
# This must run before any test imports that rely on 'homeassistant'
if "homeassistant" not in sys.modules:
    ha = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = ha
    
    ha.core = MagicMock()
    ha.config_entries = MagicMock()
    ha.data_entry_flow = MagicMock()
    ha.data_entry_flow.FlowResultType = type('FlowResultType', (), {'FORM': 'form', 'CREATE_ENTRY': 'create_entry', 'ABORT': 'abort'})
    ha.const = MagicMock()
    ha.exceptions = MagicMock()
    ha.helpers = MagicMock()
    ha.helpers.selector = MagicMock()
    ha.helpers.event = MagicMock()
    ha.helpers.event = MagicMock()
    
    # Stub DataUpdateCoordinator to allow subclass testing
    from typing import Generic, TypeVar
    _T = TypeVar("_T")
    ha.helpers.update_coordinator = MagicMock()
    class _DataUpdateCoordinatorStub(Generic[_T]):
        def __init__(self, hass, logger, **kwargs):
             self.hass = hass
             self.logger = logger
             self.data = {}
             self.name = kwargs.get("name", "test")
             self.update_interval = kwargs.get("update_interval")
        async def async_refresh(self): pass
        async def async_config_entry_first_refresh(self): pass
        @property
        def last_update_success(self): return True
        
    ha.helpers.update_coordinator.DataUpdateCoordinator = _DataUpdateCoordinatorStub
    ha.helpers.update_coordinator.UpdateFailed = Exception
    ha.helpers.storage = MagicMock()
    ha.helpers.service = MagicMock()
    
    # Entity Stubs
    class _EntityStub:
        """Stub for Entity."""
        _attr_has_entity_name = True
        should_poll = False
        def __init__(self):
            self.hass = None
            self.entity_id = "test.entity"
        @property
        def unique_id(self): return "test_unique_id"
        async def async_added_to_hass(self): pass
        async def async_will_remove_from_hass(self): pass
        
    ha.helpers.entity.Entity = _EntityStub
    
    # CoordinatorEntity Stub
    class _CoordinatorEntityStub(_EntityStub, Generic[_T]):
        def __init__(self, coordinator: _T):
            super().__init__()
            self.coordinator = coordinator
        
    ha.helpers.update_coordinator.CoordinatorEntity = _CoordinatorEntityStub

    ha.helpers.entity_platform = MagicMock()
    ha.helpers.typing = MagicMock()
    
    # Submodules
    sys.modules["homeassistant.core"] = ha.core
    sys.modules["homeassistant.config_entries"] = ha.config_entries
    sys.modules["homeassistant.data_entry_flow"] = ha.data_entry_flow
    sys.modules["homeassistant.const"] = ha.const
    sys.modules["homeassistant.exceptions"] = ha.exceptions
    sys.modules["homeassistant.helpers"] = ha.helpers
    sys.modules["homeassistant.helpers.selector"] = ha.helpers.selector
    sys.modules["homeassistant.helpers.event"] = ha.helpers.event
    sys.modules["homeassistant.helpers.update_coordinator"] = ha.helpers.update_coordinator
    sys.modules["homeassistant.helpers.storage"] = ha.helpers.storage
    sys.modules["homeassistant.helpers.service"] = ha.helpers.service
    sys.modules["homeassistant.helpers.entity"] = ha.helpers.entity
    sys.modules["homeassistant.helpers.entity_platform"] = ha.helpers.entity_platform
    # sys.modules["homeassistant.helpers.entity_platform"] = ha.helpers.entity_platform # Dup removed
    sys.modules["homeassistant.helpers.typing"] = ha.helpers.typing
    
    # Issue Registry (v2.8)
    ha.helpers.issue_registry = MagicMock()
    sys.modules["homeassistant.helpers.issue_registry"] = ha.helpers.issue_registry
    
    # Utils
    ha.util = MagicMock()
    ha.util.dt = MagicMock()
    # Correctly mock UTC for type checking
    import datetime
    ha.util.dt.UTC = datetime.timezone.utc
    sys.modules["homeassistant.util"] = ha.util
    sys.modules["homeassistant.util.dt"] = ha.util.dt

    # Components
    ha.components = MagicMock()
    ha.components.sensor = MagicMock()
    ha.components.sensor.SensorEntity = _EntityStub # Reuse Stub
    
    ha.components.binary_sensor = MagicMock()
    ha.components.binary_sensor.BinarySensorEntity = _EntityStub
    sys.modules["homeassistant.components.binary_sensor"] = ha.components.binary_sensor

    ha.components.climate = MagicMock()
    ha.components.switch = MagicMock()
    ha.components.switch.SwitchEntity = _EntityStub
    sys.modules["homeassistant.components.switch"] = ha.components.switch
    
    sys.modules["homeassistant.components"] = ha.components
    sys.modules["homeassistant.components.sensor"] = ha.components.sensor
    sys.modules["homeassistant.components.sensor"] = ha.components.sensor
    sys.modules["homeassistant.components.climate"] = ha.components.climate

@pytest.fixture
def hass():
    """Fixture to provide a mocked Home Assistant Core."""
    import sys
    return sys.modules["homeassistant"]

