"""Test Coordinator Logic v2.2 (Window Detection)."""
import sys
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock

# Add parent dir
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Mock HA
sys.modules["homeassistant"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock()
sys.modules["homeassistant.const"] = MagicMock()
sys.modules["homeassistant.helpers"] = MagicMock()
# Mock DataUpdateCoordinator as a real class to avoid MagicMock property inheritance issues
class MockDataUpdateCoordinator:
    def __init__(self, hass, logger, name, update_interval, **kwargs):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
    async def _async_update_data(self): pass
    def __class_getitem__(cls, item): return cls

# Inject Mock
mock_update_coordinator = MagicMock()
mock_update_coordinator.DataUpdateCoordinator = MockDataUpdateCoordinator
sys.modules["homeassistant.helpers.update_coordinator"] = mock_update_coordinator

sys.modules["homeassistant.helpers.event"] = MagicMock()
sys.modules["homeassistant.helpers.storage"] = MagicMock()
sys.modules["homeassistant.helpers.issue_registry"] = MagicMock()
sys.modules["homeassistant.util"] = MagicMock()
sys.modules["homeassistant.util.dt"] = MagicMock()

from custom_components.preheat.coordinator import PreheatingCoordinator, PreheatData

def test_window_detection():
    # Setup
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test"
    entry.options = {}
    entry.data = {}
    
    coord = PreheatingCoordinator(hass, entry)
    
    # Mock Time
    now = datetime(2023, 1, 1, 12, 0, 0)
    
    # 1. Initialization
    # Temp 20.0
    # Temp 20.0
    coord._track_temperature_gradient(20.0, now)
    print(f"DEBUG: window_open_detected = {coord.window_open_detected}")
    assert coord.window_open_detected is False
    assert coord._prev_temp == 20.0
    
    # 2. Stable Temp (5 mins later)
    now += timedelta(minutes=5)
    coord._track_temperature_gradient(20.0, now)
    assert coord.window_open_detected is False
    
    # 3. Slow Drop (-0.1K in 5 mins) -> OK
    now += timedelta(minutes=5)
    coord._track_temperature_gradient(19.9, now)
    assert coord.window_open_detected is False
    
    # 4. FAST DROP (-0.6K in 5 mins) -> DETECT!
    now += timedelta(minutes=5)
    coord._track_temperature_gradient(19.3, now) 
    assert coord.window_open_detected is True
    assert coord._window_cooldown_counter == 30
    print("Window Detected on fast drop.")
    
    # 5. Cooldown Logic
    # 10 mins later, temp recovers?
    now += timedelta(minutes=10)
    coord._track_temperature_gradient(19.5, now)
    assert coord.window_open_detected is True # Still in cooldown
    assert coord._window_cooldown_counter == 20 # 30 - 10
    
    # 25 mins later (total 35), cooldown done
    now += timedelta(minutes=25)
    coord._track_temperature_gradient(19.5, now)
    assert coord.window_open_detected is False
    print("Cooldown expired correctly.")

if __name__ == "__main__":
    test_window_detection()
