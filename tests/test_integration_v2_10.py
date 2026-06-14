"""Unit tests for ha-preheat v2.10.0 minor release features (Optimal Stop, Tau Learning, Shadow Savings, Schedule-Free Start)."""
import sys
import os
import unittest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, AsyncMock

# Add parent dir
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Mock HA
import types
ha = types.ModuleType("homeassistant")
ha.__path__ = []
sys.modules["homeassistant"] = ha
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock()
sys.modules["homeassistant.const"] = MagicMock()
sys.modules["homeassistant.util"] = MagicMock()

from datetime import timezone
mock_dt = MagicMock()
mock_dt.UTC = timezone.utc
mock_dt.utcnow.side_effect = lambda: datetime.now(timezone.utc)
mock_dt.now.side_effect = lambda: datetime.now(timezone.utc)
mock_dt.as_local = MagicMock(side_effect=lambda x: x)
sys.modules["homeassistant.util.dt"] = mock_dt
sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.helpers.event"] = MagicMock()
sys.modules["homeassistant.helpers.storage"] = MagicMock()
sys.modules["homeassistant.helpers.issue_registry"] = MagicMock()
sys.modules["homeassistant.exceptions"] = MagicMock()

# Mock DUC
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

mock_duc_mod = MagicMock()
mock_duc_mod.DataUpdateCoordinator = MockDataUpdateCoordinator
mock_duc_mod.UpdateFailed = Exception
sys.modules["homeassistant.helpers.update_coordinator"] = mock_duc_mod

from custom_components.preheat.coordinator import PreheatingCoordinator, PreheatData
from custom_components.preheat.providers import ProviderDecision
from custom_components.preheat.const import (
    CONF_CLIMATE, CONF_TEMPERATURE, CONF_OCCUPANCY, CONF_OUTDOOR_TEMP,
    CONF_STOP_TOLERANCE, CONF_MAX_COAST_HOURS, CONF_PHYSICS_MODE,
    PHYSICS_STANDARD, CONF_ENABLE_OPTIMAL_STOP, CONF_SCHEDULE_ENTITY
)

class TestIntegrationV210(unittest.IsolatedAsyncioTestCase):
    
    async def asyncSetUp(self):
        self.hass = MagicMock()
        self.hass.states = MagicMock()
        self.hass.bus = MagicMock()
        
        self.entry = MagicMock()
        self.entry.entry_id = "test_zone_entry"
        self.entry.title = "Test Zone"
        self.entry.data = {}
        self.entry.options = {
            CONF_ENABLE_OPTIMAL_STOP: True,
            CONF_SCHEDULE_ENTITY: "schedule.test"
        }
        
        # Patch dependencies to avoid side effects
        patchers = [
            patch("custom_components.preheat.coordinator.PreheatPlanner"),
            patch("custom_components.preheat.coordinator.Store"),
            patch("custom_components.preheat.coordinator.async_track_state_change_event"),
            patch("custom_components.preheat.diagnostics.async_create_issue"),
            patch("custom_components.preheat.diagnostics.async_delete_issue"),
            patch("custom_components.preheat.coordinator.dt_util", mock_dt),
            patch("custom_components.preheat.diagnostics.dt_util", mock_dt),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
            
        self.coordinator = PreheatingCoordinator(self.hass, self.entry)
        
        # Configure Planner Mock
        self.coordinator.planner.get_next_scheduled_event = MagicMock(return_value=None)
        self.coordinator.planner.get_next_predicted_departure = MagicMock(return_value=None)
        self.coordinator.planner.last_pattern_result = None
        
        # Setup basic mock states
        self.coordinator._startup_time = mock_dt.utcnow() - timedelta(hours=2)
        self.coordinator.physics = MagicMock()
        self.coordinator.physics.calculate_duration.return_value = 60.0
        self.coordinator.physics.mass_factor = 20.0
        self.coordinator.physics.loss_factor = 5.0
        self.coordinator.physics.deadtime = 10.0
        
        self.coordinator._get_operative_temperature = AsyncMock(return_value=20.0)
        self.coordinator._get_target_setpoint = AsyncMock(return_value=21.0)
        self.coordinator._get_outdoor_temp_current = AsyncMock(return_value=10.0)
        
        # Mock weather
        self.coordinator.weather_service = MagicMock()
        self.coordinator.weather_service.get_forecasts = AsyncMock(return_value=[])

        # Mock optimal stop manager
        self.coordinator.optimal_stop_manager = MagicMock()
        self.coordinator.optimal_stop_manager.is_active = False
        self.coordinator.optimal_stop_manager.stop_time = None
        self.coordinator.optimal_stop_manager._reason = "mock"
        self.coordinator.optimal_stop_manager._savings_total = 0.0
        self.coordinator.optimal_stop_manager._savings_remaining = 0.0
        
        # Mock schedule/learned providers
        self.coordinator.schedule_provider = MagicMock()
        self.coordinator.schedule_provider.get_decision.return_value = ProviderDecision(
            should_stop=False, session_end=None, is_valid=False, is_shadow=False
        )
        self.coordinator.learned_provider = MagicMock()
        self.coordinator.learned_provider.get_decision.return_value = ProviderDecision(
            should_stop=False, session_end=None, is_valid=False, is_shadow=True
        )

    async def test_optimal_stop_clamping_and_gating(self):
        """Test M1: Clamp tau to 12h and apply confidence gate."""
        # Enable optimal stop
        self.coordinator.entry.options[CONF_ENABLE_OPTIMAL_STOP] = True
        
        # Scenario A: High tau, high confidence
        self.coordinator.cooling_analyzer.learned_tau = 15.0
        self.coordinator.cooling_analyzer.confidence = 0.8
        
        now = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)
        ctx = await self.coordinator._collect_context()
        ctx["now"] = now
        pred = await self.coordinator._run_physics_simulation(ctx)
        
        # Run _evaluate_start_decision
        self.coordinator._evaluate_start_decision(ctx, pred)
        
        # Verify clamped tau (12.0) was used
        self.coordinator.optimal_stop_manager.update.assert_called_with(
            current_temp=20.0,
            target_temp=21.0,
            schedule_end=None,
            forecast_provider=unittest.mock.ANY,
            tau_hours=12.0, # Clamped from 15.0 to 12.0
            config=unittest.mock.ANY,
            predicted_end=unittest.mock.ANY
        )
        
        # Scenario B: Under confidence gate threshold (confidence < 0.6)
        self.coordinator.cooling_analyzer.learned_tau = 8.0
        self.coordinator.cooling_analyzer.confidence = 0.5 # Under gate 0.6
        
        self.coordinator.optimal_stop_manager.update.reset_mock()
        self.coordinator._evaluate_start_decision(ctx, pred)
        
        # Verify tau_hours is 0.0 (no coasting) due to confidence gate
        self.coordinator.optimal_stop_manager.update.assert_called_with(
            current_temp=20.0,
            target_temp=21.0,
            schedule_end=None,
            forecast_provider=unittest.mock.ANY,
            tau_hours=0.0, # Confidence gate triggered
            config=unittest.mock.ANY,
            predicted_end=unittest.mock.ANY
        )

    async def test_alt_tau_revalidation(self):
        """Test M2: Revalidate alt-tau on load and reset if implausible."""
        # Scenario A: Load implausible high alt-tau (e.g. 55.0) with confidence 0.68
        mock_stored_data = {
            "model_cooling_tau": 55.0,
            "cooling_confidence": 0.68,
            "tau_revalidated": False
        }
        self.coordinator._store.async_load = AsyncMock(return_value=mock_stored_data)
        
        await self.coordinator.async_load_data()
        
        # Should be reset to profile's default_coast (2.0 for default profile) and confidence halved (0.34)
        self.assertEqual(self.coordinator.cooling_analyzer.learned_tau, 2.0)
        self.assertEqual(self.coordinator.cooling_analyzer.confidence, 0.34)
        self.assertTrue(self.coordinator.tau_revalidated)
        
        # Scenario B: Load plausible high alt-tau (e.g. 24.0) with confidence 0.68
        mock_stored_data_plausible = {
            "model_cooling_tau": 24.0,
            "cooling_confidence": 0.68,
            "tau_revalidated": False
        }
        self.coordinator._store.async_load = AsyncMock(return_value=mock_stored_data_plausible)
        
        await self.coordinator.async_load_data()
        
        # Should not reset since 24.0 is within [0.5, 48.0]
        self.assertEqual(self.coordinator.cooling_analyzer.learned_tau, 24.0)
        self.assertEqual(self.coordinator.cooling_analyzer.confidence, 0.68)
        self.assertTrue(self.coordinator.tau_revalidated)

        # Scenario C: Stored data is already revalidated
        mock_stored_data_reval = {
            "model_cooling_tau": 15.0,
            "cooling_confidence": 0.8,
            "tau_revalidated": True
        }
        self.coordinator._store.async_load = AsyncMock(return_value=mock_stored_data_reval)
        
        await self.coordinator.async_load_data()
        
        # Should NOT reset because tau_revalidated is True
        self.assertEqual(self.coordinator.cooling_analyzer.learned_tau, 15.0)
        self.assertEqual(self.coordinator.cooling_analyzer.confidence, 0.8)

    async def test_shadow_savings_accumulation_and_persistence(self):
        """Test M3: Accumulate shadow savings over time and persist them."""
        self.coordinator.optimal_stop_manager.is_active = True
        self.coordinator._shadow_metrics["cumulative_shadow_savings"] = 10.0
        
        # Run update at t = 0
        now = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)
        ctx = await self.coordinator._collect_context()
        ctx["now"] = now
        pred = await self.coordinator._run_physics_simulation(ctx)
        
        self.coordinator._evaluate_start_decision(ctx, pred)
        
        # Run update at t = 5 minutes
        now_plus_5 = now + timedelta(minutes=5)
        ctx_plus_5 = dict(ctx)
        ctx_plus_5["now"] = now_plus_5
        
        self.coordinator._evaluate_start_decision(ctx_plus_5, pred)
        
        # Savings should grow by 5 minutes
        self.assertAlmostEqual(
            self.coordinator._shadow_metrics["cumulative_shadow_savings"],
            15.0,
            places=1
        )
        
        # Verify persistence
        storage_data = self.coordinator._get_data_for_storage()
        self.assertAlmostEqual(storage_data["cumulative_shadow_savings"], 15.0, places=1)

    async def test_schedule_free_autonomous_start(self):
        """Test M4: Start autonomouly in schedule-free zone with mature pattern."""
        self.coordinator.entry.options[CONF_SCHEDULE_ENTITY] = None # Schedule-free
        
        # Scenario A: Mature arrival pattern (confidence 0.85 >= 0.7)
        mock_pattern = MagicMock()
        mock_pattern.confidence = 0.85
        self.coordinator.planner.last_pattern_result = mock_pattern
        
        now = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)
        ctx = await self.coordinator._collect_context()
        ctx["now"] = now
        # Mock next event in 30 minutes
        ctx["next_event"] = now + timedelta(minutes=30)
        pred = await self.coordinator._run_physics_simulation(ctx)
        pred["predicted_duration"] = 45.0 # Lead time is 45 min, so now (30 min to event) is within lead time!
        
        dec = self.coordinator._evaluate_start_decision(ctx, pred)
        
        self.assertEqual(dec["start_source"], "learned")
        self.assertTrue(dec["should_start"])
        self.assertEqual(dec["start_time"], now)
        
        # Scenario B: Immature arrival pattern (confidence 0.5 < 0.7)
        mock_pattern.confidence = 0.5
        dec_immature = self.coordinator._evaluate_start_decision(ctx, pred)
        
        self.assertEqual(dec_immature["start_source"], "none")
        self.assertFalse(dec_immature["should_start"])

    async def test_blocked_semantics(self):
        """Test M5: 'none' source does not mean blocked."""
        self.coordinator.entry.options[CONF_SCHEDULE_ENTITY] = None # Schedule-free
        
        # Immature pattern -> source "none"
        mock_pattern = MagicMock()
        mock_pattern.confidence = 0.5
        self.coordinator.planner.last_pattern_result = mock_pattern
        
        now = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)
        ctx = await self.coordinator._collect_context()
        ctx["now"] = now
        ctx["next_event"] = now + timedelta(minutes=30)
        pred = await self.coordinator._run_physics_simulation(ctx)
        pred["predicted_duration"] = 45.0
        
        dec = self.coordinator._evaluate_start_decision(ctx, pred)
        
        # Check start source
        self.assertEqual(dec["start_source"], "none")
        
        # Trace should have blocked=False because there are no active blockers
        trace = self.coordinator.decision_trace
        self.assertFalse(trace["blocked"])
        self.assertEqual(trace["start_source"], "none")
