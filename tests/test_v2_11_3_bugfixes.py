"""Tests for ha-preheat v2.11.3 bugfixes and hardening."""
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
from custom_components.preheat.cooling_analyzer import CoolingAnalyzer
from custom_components.preheat.house_collector import HouseArrivalCollector
from custom_components.preheat.const import (
    VALVE_HEATING_THRESHOLD,
    OS_REASON_NO_TEMPERATURE,
)

class TestV2_11_3_Bugfixes(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        self.mock_store = MagicMock()
        self.mock_store.async_load = AsyncMock(return_value=None)
        self.mock_store.async_save = AsyncMock()
        self.store_patcher = patch("custom_components.preheat.house_collector.Store", return_value=self.mock_store)
        self.store_patcher.start()

    def tearDown(self):
        self.store_patcher.stop()

    # ---------------------------------------------------------
    # T1: Ghost Heating Guard & is_heating check
    # ---------------------------------------------------------
    async def test_t1_ghost_heating_guard(self):
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test"
        entry.options = {}
        entry.data = {}
        
        with patch("custom_components.preheat.coordinator.PreheatingCoordinator._setup_listeners"), \
             patch("custom_components.preheat.coordinator.PreheatingCoordinator.async_load_data"):
             coord = PreheatingCoordinator(hass, entry)
             
        coord.cooling_analyzer = MagicMock()
        coord._preheat_active = True
        
        # Scenario 1: Normal preheat active, valve is 100%
        coord._get_valve_position = MagicMock(return_value=100.0)
        ctx = {
            "operative_temp": 20.0,
            "outdoor_temp": 10.0,
            "target_setpoint": 21.0,
            "hvac_action": "heating",
            "now": datetime.now(),
            "is_window_open": False,
            "is_occupied": False
        }
        dec = {"start_time": None}
        pred = {"predicted_duration": 120.0}
        await coord._post_update_tasks(ctx, dec, pred)
        coord.cooling_analyzer.add_data_point.assert_called_with(
            dt=ctx["now"],
            t_in=20.0,
            t_out=10.0,
            is_heating=True,
            window_open=False,
            valid_cooling=False
        )
        
        coord.cooling_analyzer.reset_mock()
        
        # Scenario 2: Ghost Heating (preheat active, but valve < threshold and hvac_action is idle)
        coord._get_valve_position = MagicMock(return_value=0.0)
        ctx["hvac_action"] = "idle"
        await coord._post_update_tasks(ctx, dec, pred)
        coord.cooling_analyzer.add_data_point.assert_called_with(
            dt=ctx["now"],
            t_in=20.0,
            t_out=10.0,
            is_heating=False,
            window_open=False,
            valid_cooling=False
        )

    # ---------------------------------------------------------
    # T2: Reload Revalidation logic
    # ---------------------------------------------------------
    @patch("custom_components.preheat.coordinator._LOGGER")
    async def test_t2_revalidation_loading(self, mock_logger):
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test"
        entry.options = {}
        entry.data = {}
        
        with patch("custom_components.preheat.coordinator.PreheatingCoordinator._setup_listeners"):
             coord = PreheatingCoordinator(hass, entry)
             
        # Case 2.1: Plausible high value (24.0 is within [0.5, 48.0]) -> Keep
        coord._store.async_load = AsyncMock(return_value={
            "model_cooling_tau": 24.0,
            "cooling_confidence": 0.68,
            "tau_revalidated": False,
            "physics_version": 2
        })
        mock_logger.reset_mock()
        await coord.async_load_data()
        self.assertEqual(coord.cooling_analyzer.learned_tau, 24.0)
        self.assertEqual(coord.cooling_analyzer.confidence, 0.68)
        self.assertTrue(coord.tau_revalidated)
        mock_logger.warning.assert_not_called()
        
        # Case 2.2: Implausible high value (55.0 is outside [0.5, 48.0]) -> Clamp to default, halve confidence
        coord.tau_revalidated = False
        coord._store.async_load = AsyncMock(return_value={
            "model_cooling_tau": 55.0,
            "cooling_confidence": 0.68,
            "tau_revalidated": False,
            "physics_version": 2
        })
        mock_logger.reset_mock()
        await coord.async_load_data()
        self.assertEqual(coord.cooling_analyzer.learned_tau, 2.0)  # default_coast
        self.assertEqual(coord.cooling_analyzer.confidence, 0.34)  # 0.68 / 2
        self.assertTrue(coord.tau_revalidated)
        mock_logger.info.assert_called()  # Warning/info revalidation log
        
        # Case 2.3: Fresh configuration -> No log warnings
        coord.tau_revalidated = False
        coord._store.async_load = AsyncMock(return_value={
            "physics_version": 2
        })
        mock_logger.reset_mock()
        await coord.async_load_data()
        self.assertEqual(coord.cooling_analyzer.learned_tau, 2.0)
        self.assertEqual(coord.cooling_analyzer.confidence, 0.0)
        self.assertTrue(coord.tau_revalidated)
        mock_logger.warning.assert_not_called()

    # ---------------------------------------------------------
    # T3: Time-based gates and rate limit cap
    # ---------------------------------------------------------
    def test_t3_cooling_analyzer_time_gates(self):
        analyzer = CoolingAnalyzer()
        start_time = datetime(2024, 1, 1, 12, 0, 0)
        
        # Case 3.1: Spans 90 minutes with 19 points (at 5-min intervals) -> Valid time gate
        for i in range(19):
            dt = start_time + timedelta(minutes=i * 5)
            # Normal cooling drop of 0.01 K per minute
            t_in = 22.0 - (i * 5 * 0.01)
            analyzer.add_data_point(dt, t_in, 10.0, is_heating=False)
            
        stats = analyzer.analyze()
        self.assertIn("tau", stats)
        self.assertGreater(stats["confidence"], 0.0)
        
        # Case 3.2: Too short time spans (< 60 mins), e.g. 5 points at 5-min interval = 20 mins
        analyzer = CoolingAnalyzer()
        for i in range(5):
            dt = start_time + timedelta(minutes=i * 5)
            t_in = 22.0 - (i * 5 * 0.01)
            analyzer.add_data_point(dt, t_in, 10.0, is_heating=False)
        stats = analyzer.analyze()
        self.assertIn(stats.get("status"), ["no_segments", "no_valid_fits", "low_confidence"])

        # Case 3.3: Plausibility rate limit cap (> 0.5 K/min)
        # Drop 0.6K in 1 minute -> rate is 0.6 K/min -> should split/invalidate
        analyzer = CoolingAnalyzer()
        # Segment 1 (50 minutes, not long enough on its own)
        for i in range(11):
            dt = start_time + timedelta(minutes=i * 5)
            t_in = 22.0 - (i * 5 * 0.01)
            analyzer.add_data_point(dt, t_in, 10.0, is_heating=False)
        # Point with huge drop rate
        dt = start_time + timedelta(minutes=51)
        analyzer.add_data_point(dt, 20.0, 10.0, is_heating=False)
        
        # This split prevents the segment from being continuous. Thus it's split into too-short sub-segments.
        stats = analyzer.analyze()
        self.assertIn(stats.get("status"), ["no_segments", "no_valid_fits", "low_confidence"])

    # ---------------------------------------------------------
    # T4: Defective Zone Handling (no_temperature sensor ready errors)
    # ---------------------------------------------------------
    async def test_t4_defective_zone_handling(self):
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test"
        entry.options = {}
        entry.data = {}
        
        with patch("custom_components.preheat.coordinator.PreheatingCoordinator._setup_listeners"), \
             patch("custom_components.preheat.coordinator.PreheatingCoordinator.async_load_data"):
             coord = PreheatingCoordinator(hass, entry)
             
        # Mock dependencies
        coord.diagnostics = MagicMock()
        coord.optimal_stop_manager = MagicMock()
        coord._store = MagicMock()
        coord._store.async_save = AsyncMock()
        coord.physics = MagicMock()
        coord.cooling_analyzer = MagicMock()
        coord.cooling_analyzer.learned_tau = 4.0
        coord.cooling_analyzer.confidence = 0.8
        
        # Mock Context collection causing sensor ready = False
        coord._collect_context = AsyncMock(return_value={
            "is_sensor_ready": False,
            "operative_temp": -273.15,
            "is_occupied": False,
            "now": datetime.now()
        })
        
        # Loop update 3 times to trigger error state
        for _ in range(3):
            data = await coord._async_update_data()
            
        # Verify no_temperature issue is created after 3 errors
        coord.diagnostics._create_issue.assert_called_with("no_temperature")
        self.assertEqual(coord.optimal_stop_manager._reason, OS_REASON_NO_TEMPERATURE)
        
        # Verify no saves or learning
        coord._store.async_save.assert_not_called()
        
        # Verify house aggregation excludes this defective zone
        collector = HouseArrivalCollector(hass)
        
        mock_entry = MagicMock()
        mock_entry.runtime_data = coord
        hass.config_entries.async_entries.return_value = [mock_entry]
        
        # Case A: Normal (errors = 0)
        coord._consecutive_readiness_errors = 0
        coord.data = PreheatData(
            preheat_active=False,
            next_start_time=None,
            operative_temp=20.0,
            target_setpoint=21.0,
            next_arrival=None,
            predicted_duration=200.0,
            mass_factor=0,
            loss_factor=0,
            learning_active=False
        )
        dur = collector.get_max_predicted_duration()
        self.assertEqual(dur, 200.0)
        
        # Case B: Defective (errors = 3)
        coord._consecutive_readiness_errors = 3
        dur = collector.get_max_predicted_duration()
        self.assertEqual(dur, 120.0) # default fallback
        
        # Test floor of tau_hours in optimal stop
        coord.cooling_analyzer.learned_tau = 1.0
        coord.cooling_analyzer.confidence = 0.8
        
        def get_conf_mock(key, default=None):
            if key == "heating_profile":
                return "radiator_new"
            return default
        coord._get_conf = MagicMock(side_effect=get_conf_mock)
        
        # Call the method directly
        is_active, stop_time, stop_reason, savings_total, savings_remaining, tau_hours = \
            coord._update_optimal_stop_and_savings(
                ctx={"operative_temp": 20.0, "target_setpoint": 21.0, "outdoor_temp": 10.0, "forecasts": []},
                now=datetime.now(),
                sched_decision=MagicMock(session_end=datetime.now() + timedelta(hours=1))
            )
            
        # default_coast for radiator_new is 2.0. So tau_hours should be max(1.0, 2.0) = 2.0.
        self.assertEqual(tau_hours, 2.0)
