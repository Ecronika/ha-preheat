"""Tests for ha-preheat v2.11.4 next_start_time forecast."""
import sys
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, AsyncMock

# Add parent dir
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# --- MOCK Home Assistant ---
import types
if "homeassistant" not in sys.modules:
    ha = types.ModuleType("homeassistant")
    ha.__path__ = []
    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = MagicMock()
    sys.modules["homeassistant.config_entries"] = MagicMock()
    sys.modules["homeassistant.const"] = MagicMock()
    sys.modules["homeassistant.util"] = MagicMock()
    
    mock_dt = MagicMock()
    mock_dt.UTC = timezone.utc
    mock_dt.utcnow.side_effect = lambda: datetime.now(timezone.utc)
    sys.modules["homeassistant.util.dt"] = mock_dt
    sys.modules["homeassistant.helpers"] = MagicMock()
    sys.modules["homeassistant.helpers.event"] = MagicMock()
    sys.modules["homeassistant.helpers.storage"] = MagicMock()
    sys.modules["homeassistant.helpers.issue_registry"] = MagicMock()
    sys.modules["homeassistant.exceptions"] = MagicMock()

# Mock DUC if not done
if "homeassistant.helpers.update_coordinator" not in sys.modules:
    class MockDataUpdateCoordinator:
        def __init__(self, hass, logger, name, update_interval, **kwargs):
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.data = None
        async def _async_update_data(self): pass
        def async_add_listener(self, *args): pass
        async def async_refresh(self): pass
        async def async_request_refresh(self): pass
        def __class_getitem__(cls, item): return cls

    class MockUpdateFailed(Exception): pass

    mock_duc_mod = MagicMock()
    mock_duc_mod.DataUpdateCoordinator = MockDataUpdateCoordinator
    mock_duc_mod.UpdateFailed = MockUpdateFailed
    sys.modules["homeassistant.helpers.update_coordinator"] = mock_duc_mod

from custom_components.preheat.coordinator import PreheatingCoordinator, PreheatData
from custom_components.preheat.const import VERSION
import json

class TestV2_11_4_Forecast(unittest.TestCase):

    def setUp(self):
        self.hass = MagicMock()
        self.entry = MagicMock()
        self.entry.entry_id = "test_entry"
        self.entry.title = "Test Zone"
        self.entry.options = {}
        self.entry.data = {}

        with patch("custom_components.preheat.coordinator.PreheatingCoordinator._setup_listeners"), \
             patch("custom_components.preheat.coordinator.PreheatingCoordinator.async_load_data"):
             self.coord = PreheatingCoordinator(self.hass, self.entry)

    def test_forecast_calculation_rules(self):
        """Test calculation of display forecast in _build_preheat_data."""
        next_event = datetime(2026, 6, 16, 15, 0, 0, tzinfo=timezone.utc)

        # Context mock
        ctx = {
            "operative_temp": 18.0,
            "target_setpoint": 21.0,
            "next_event": next_event,
            "is_window_open": False,
            "outdoor_temp": 5.0,
            "valve_position": 0.0,
            "hvac_action": "idle",
            "hvac_mode": "heat",
        }

        # Case 1: forecast_start has a value in advance (dec["start_time"] is None)
        # arrival at 15:00, predicted_duration = 60 mins -> start at 14:00
        pred = {"predicted_duration": 60.0}
        dec = {
            "start_time": None,
            "effective_departure": None,
            "start_source": "house",
        }
        data = self.coord._build_preheat_data(ctx, pred, dec)
        self.assertEqual(data.next_start_time, next_event - timedelta(minutes=60))

        # Case 2: dec["start_time"] is already set (real trigger fired) -> should take precedence
        trigger_time = datetime(2026, 6, 16, 13, 50, 0, tzinfo=timezone.utc)
        dec["start_time"] = trigger_time
        data = self.coord._build_preheat_data(ctx, pred, dec)
        self.assertEqual(data.next_start_time, trigger_time)

        # Case 3: predicted_duration is 0 (already warm) -> next_start_time is None
        pred["predicted_duration"] = 0.0
        dec["start_time"] = None
        data = self.coord._build_preheat_data(ctx, pred, dec)
        self.assertIsNone(data.next_start_time)

        # Case 4: start_source is "none" -> next_start_time is None
        pred["predicted_duration"] = 60.0
        dec["start_source"] = "none"
        data = self.coord._build_preheat_data(ctx, pred, dec)
        self.assertIsNone(data.next_start_time)

        # Case 5: next_event is None -> next_start_time is None
        dec["start_source"] = "house"
        ctx["next_event"] = None
        data = self.coord._build_preheat_data(ctx, pred, dec)
        self.assertIsNone(data.next_start_time)

    def test_version_bump(self):
        """Verify the integration version is correctly bumped to 2.11.4."""
        self.assertEqual(VERSION, "2.11.4")

        # Read manifest.json
        manifest_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "custom_components",
            "preheat",
            "manifest.json"
        )
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["version"], "2.11.4")
