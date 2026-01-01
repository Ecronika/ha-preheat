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
    ha.helpers.update_coordinator = MagicMock()
    ha.helpers.storage = MagicMock()
    ha.helpers.service = MagicMock()
    ha.helpers.entity = MagicMock()
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
    sys.modules["homeassistant.helpers.entity_platform"] = ha.helpers.entity_platform
    sys.modules["homeassistant.helpers.typing"] = ha.helpers.typing
    
    # Issue Registry (v2.8)
    ha.helpers.issue_registry = MagicMock()
    sys.modules["homeassistant.helpers.issue_registry"] = ha.helpers.issue_registry
    
    # Utils
    ha.util = MagicMock()
    ha.util.dt = MagicMock()
    sys.modules["homeassistant.util"] = ha.util
    sys.modules["homeassistant.util.dt"] = ha.util.dt

    # Components
    ha.components = MagicMock()
    ha.components.sensor = MagicMock()
    ha.components.climate = MagicMock()
    sys.modules["homeassistant.components"] = ha.components
    sys.modules["homeassistant.components.sensor"] = ha.components.sensor
    sys.modules["homeassistant.components.sensor"] = ha.components.sensor
    sys.modules["homeassistant.components.climate"] = ha.components.climate

@pytest.fixture
def hass():
    """Fixture to provide a mocked Home Assistant Core."""
    import sys
    return sys.modules["homeassistant"]

