"""Test Diagnostics."""
import sys
import os
import asyncio
from unittest.mock import MagicMock

# Add parent dir
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Mock HA
sys.modules["homeassistant"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock() # FIX: Added this
sys.modules["homeassistant.const"] = MagicMock()
sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.helpers.update_coordinator"] = MagicMock()
sys.modules["homeassistant.helpers.event"] = MagicMock()
sys.modules["homeassistant.helpers.storage"] = MagicMock()
sys.modules["homeassistant.helpers.issue_registry"] = MagicMock()
sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.diagnostics"] = MagicMock()
sys.modules["homeassistant.components.diagnostics"].async_redact_data = lambda d, r: d
sys.modules["homeassistant.util"] = MagicMock()
sys.modules["homeassistant.util.dt"] = MagicMock()

from custom_components.preheat.diagnostics import async_get_config_entry_diagnostics

async def test_diagnostics_structure():
    # Setup Mocks
    hass = MagicMock()
    entry = MagicMock()
    entry.data = {"some": "data"}
    entry.options = {"expert_mode": True}
    
    coordinator = MagicMock()
    entry.runtime_data = coordinator
    
    # Mock Physics
    coordinator.physics.to_dict.return_value = {"mass": 10}
    coordinator.physics.health_score = 95
    
    # Mock Planner
    coordinator.planner.get_schedule_summary.return_value = {"Mon": "07:00"}
    
    # Mock Data
    coordinator.data.preheat_active = True
    coordinator.data.target_setpoint = 22.0
    coordinator.data.operative_temp = 20.0
    coordinator.data.outdoor_temp = 5.0
    coordinator.data.next_arrival = None
    coordinator.data.valve_signal = 50.0
    coordinator.data.learning_active = False
    
    # Mock Window State (Attribute on coordinator directly)
    coordinator.window_open_detected = False

    # Execute
    diag = await async_get_config_entry_diagnostics(hass, entry)
    
    # Verify
    assert "entry_data" in diag
    assert "entry_options" in diag
    assert "physics" in diag
    assert diag["physics"]["health_score"] == 95
    assert "schedule" in diag
    assert "state" in diag
    assert diag["state"]["preheat_active"] is True
    assert diag["state"]["outdoor_temp"] == 5.0
    assert diag["state"]["window_open_detected"] is False

    assert diag["state"]["window_open_detected"] is False

    print("Diagnostics structure verified.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_diagnostics_structure())
