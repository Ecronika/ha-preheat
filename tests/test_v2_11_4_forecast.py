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

class TestV2_11_4_Forecast(unittest.IsolatedAsyncioTestCase):

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

        # Case 2: during active preheating -> should show the frozen started_at time
        trigger_time = datetime(2026, 6, 16, 13, 50, 0, tzinfo=timezone.utc)
        self.coord._preheat_active = True
        self.coord._preheat_started_at = trigger_time
        data = self.coord._build_preheat_data(ctx, pred, dec)
        self.assertEqual(data.next_start_time, trigger_time)
        self.coord._preheat_active = False # Reset

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

    async def test_start_preheat_reentry_guard(self):
        """Verify that calling _start_preheat twice does not overwrite starting variables."""
        self.coord._preheat_active = False
        self.coord._preheat_started_at = None
        self.coord._start_temp = None

        # First call
        now_dt = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
        with patch("custom_components.preheat.coordinator.dt_util.utcnow", return_value=now_dt):
            self.hass.async_create_task = MagicMock()
            self.coord.hass = self.hass
            self.coord.device_name = "Test Zone"
            await self.coord._start_preheat(20.0)

        self.assertTrue(self.coord._preheat_active)
        self.assertEqual(self.coord._preheat_started_at, now_dt)
        self.assertEqual(self.coord._start_temp, 20.0)

        # Second call with different temp and time
        later_dt = datetime(2026, 6, 17, 12, 5, 0, tzinfo=timezone.utc)
        with patch("custom_components.preheat.coordinator.dt_util.utcnow", return_value=later_dt):
            await self.coord._start_preheat(22.0)

        # Values must remain unchanged
        self.assertEqual(self.coord._preheat_started_at, now_dt)
        self.assertEqual(self.coord._start_temp, 20.0)

    async def test_outcome_scoring_on_preheat_stop(self):
        """Verify that ending a preheat session correctly calculates outcome scoring."""
        self.coord._preheat_active = False
        self.coord.diagnostics.data = {}
        self.coord.device_name = "Test Zone"

        next_event = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
        self.coord._last_predicted_duration = 30.0

        ctx = {
            "operative_temp": 18.0,
            "next_event": next_event,
            "outdoor_temp": 10.0,
            "target_setpoint": 21.0,
            "is_window_open": False,
        }
        dec = {
            "should_start": True,
            "frost_override": False,
            "start_time": None,
            "effective_departure": None,
            "start_source": "house",
        }

        # Mock start
        await self.coord._execute_control_actions(ctx, dec)

        self.assertEqual(self.coord._preheat_target_event, next_event)
        self.assertEqual(self.coord._preheat_predicted_duration, 30.0)

        # Mock start time 45 minutes ago (duration = 45 mins)
        start_time = next_event - timedelta(minutes=45)
        self.coord._preheat_started_at = start_time

        # Mock points in history buffer
        from custom_components.preheat.history_buffer import HistoryPoint
        self.coord.history_buffer._buffer = [
            HistoryPoint(start_time.timestamp(), 18.0, 100.0, True),
            HistoryPoint((start_time + timedelta(minutes=25)).timestamp(), 21.0, 100.0, True), # Crossed 21.0 target at 11:40 (-20 mins timing error)
            HistoryPoint((start_time + timedelta(minutes=45)).timestamp(), 21.5, 0.0, False)
        ]

        # Stop preheat
        self.coord.physics.update_model = MagicMock(return_value=True)
        self.coord._outdoor_is_real = True
        self.coord._get_valve_position = MagicMock(return_value=0.0)

        with patch("custom_components.preheat.coordinator.dt_util.utcnow", return_value=next_event):
            await self.coord._stop_preheat(end_temp=21.5, target=21.0, outdoor=10.0, aborted=False)

        outcome = self.coord.diagnostics.data.get("last_outcome")
        self.assertIsNotNone(outcome)
        self.assertTrue(outcome["comfort_hit"])
        self.assertEqual(outcome["temp_gap_k"], 0.5)
        self.assertEqual(outcome["overshoot_k"], 0.5)
        # Crossed at 11:40 (20 mins before 12:00) -> timing error = -20.0
        self.assertEqual(outcome["timing_error_min"], -20.0)
        # Duration error: actual duration 45 mins - predicted 30 mins = 15.0 mins
        self.assertEqual(outcome["duration_error_min"], 15.0)
