"""Integration tests for V2.7 Arbitration & Trace."""
import sys
import os
import unittest
import asyncio
from datetime import datetime, timedelta, date
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
sys.modules["homeassistant.util.dt"] = MagicMock()
sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.helpers.event"] = MagicMock()
sys.modules["homeassistant.helpers.storage"] = MagicMock()
sys.modules["homeassistant.helpers.issue_registry"] = MagicMock()
sys.modules["homeassistant.exceptions"] = MagicMock() # Added mock
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

class MockUpdateFailed(Exception): pass

mock_duc_mod = MagicMock()
mock_duc_mod.DataUpdateCoordinator = MockDataUpdateCoordinator
mock_duc_mod.UpdateFailed = MockUpdateFailed
sys.modules["homeassistant.helpers.update_coordinator"] = mock_duc_mod

# Import classes
from custom_components.preheat.coordinator import PreheatingCoordinator, PreheatData
from custom_components.preheat.providers import ProviderDecision
from custom_components.preheat.const import (
    GATE_FAIL_MANUAL, ATTR_DECISION_TRACE, SCHEMA_VERSION,
    KEY_PROVIDER_SELECTED, KEY_GATES_FAILED,
    PROVIDER_MANUAL, PROVIDER_SCHEDULE, PROVIDER_LEARNED, PROVIDER_NONE
)

class TestCoordinatorV27(unittest.TestCase):
    def setUp(self):
        self.hass = MagicMock()
        self.entry = MagicMock()
        self.entry.entry_id = "test_entry"
        self.entry.options = {}
        self.entry.data = {}
        
        # Patch init to avoid heavy loading
        with patch("custom_components.preheat.coordinator.PreheatingCoordinator._setup_listeners"), \
             patch("custom_components.preheat.coordinator.PreheatingCoordinator.async_load_data"):
             
            self.coord = PreheatingCoordinator(self.hass, self.entry)
        
        # Mock Providers
        self.coord.schedule_provider = MagicMock()
        self.coord.learned_provider = MagicMock()
        
        # Mock internal deps
        self.coord.cooling_analyzer = MagicMock()
        self.coord.cooling_analyzer.learned_tau = 3.0
        self.coord.cooling_analyzer.confidence = 0.5
        self.coord.physics = MagicMock()
        self.coord.physics.deadtime = 15.0
        self.coord.physics.mass_factor = 20.0
        self.coord.physics.calculate_duration.return_value = 30.0 # Return float
        
        # Mock Helper methods used in update
        self.coord._check_entity_availability = AsyncMock()
        self.coord._get_operative_temperature = AsyncMock(return_value=20.0)
        self.coord._get_valve_position = MagicMock(return_value=0.0)
        self.coord._get_target_setpoint = AsyncMock(return_value=21.0)
        self.coord._get_outdoor_temp_current = AsyncMock(return_value=10.0)
        
        # Mock Session Resolver (Legacy checks)
        self.coord.session_resolver = MagicMock()
        self.coord.session_resolver.get_current_session_end.return_value = None
        
        # Mock Planner Summary
        self.coord.planner.get_schedule_summary = MagicMock(return_value={})

    def run_async(self, coro):
        return asyncio.run(coro)

    def test_arbitration_hierarchy_hold(self):
        """Test Hold overrides everything."""
        self.coord.hold_active = True
        
        # Schedule says Valid
        self.coord.schedule_provider.get_decision.return_value = ProviderDecision(
            should_stop=True, session_end=None, is_valid=True, is_shadow=False
        )
        # Learned says Valid
        self.coord.learned_provider.get_decision.return_value = ProviderDecision(
            should_stop=True, session_end=None, is_valid=True, is_shadow=True
        ) # Currently Learned is always shadow

        data = self.run_async(self.coord._async_update_data())
        
        trace = data.decision_trace
        self.assertEqual(trace[KEY_PROVIDER_SELECTED], PROVIDER_MANUAL)
        self.assertIn(GATE_FAIL_MANUAL, trace[KEY_GATES_FAILED])

    def test_arbitration_hierarchy_schedule(self):
        """Test Schedule overrides Learned."""
        self.coord.hold_active = False
        
        # Schedule Valid
        sched_decision = ProviderDecision(
            should_stop=True, session_end=datetime.now(), is_valid=True, is_shadow=False, predicted_savings=10.0
        )
        self.coord.schedule_provider.get_decision.return_value = sched_decision
        
        # Learned Valid
        self.coord.learned_provider.get_decision.return_value = ProviderDecision(
            should_stop=True, session_end=None, is_valid=True, is_shadow=True
        )

        data = self.run_async(self.coord._async_update_data())
        
        trace = data.decision_trace
        self.assertEqual(trace[KEY_PROVIDER_SELECTED], PROVIDER_SCHEDULE)
        # Verify legacy output mapping
        # optimal_stop_active should come from Schedule decision (if enabled in config, usually)
        # Here default enabled=False, so opt_active=False. But let's verify selected.

    def test_arbitration_learned_shadow(self):
        """Test Learned is selected if Schedule Invalid? (Actually Learned is Shadow)"""
        self.coord.hold_active = False
        
        # Schedule Invalid
        self.coord.schedule_provider.get_decision.return_value = ProviderDecision(
            should_stop=False, session_end=None, is_valid=False, is_shadow=False, invalid_reason="unavailable"
        )
        
        # Learned Valid
        self.coord.learned_provider.get_decision.return_value = ProviderDecision(
            should_stop=True, session_end=None, is_valid=True, is_shadow=True
        )
        
        data = self.run_async(self.coord._async_update_data())
        
        trace = data.decision_trace
        # Learned is VALID, but is_shadow=True.
        # Logic: elif learned_decision.is_valid and not learned_decision.is_shadow: selected = LEARNED
        # Since is_shadow=True, selected matches nothing -> NONE
        # This confirms Shadow Safety (Learned does not control).
        
        self.assertEqual(trace[KEY_PROVIDER_SELECTED], PROVIDER_NONE)
        self.assertTrue(PROVIDER_LEARNED in trace["provider_candidates"])

    def test_trace_schema(self):
        """Verify trace schema keys."""
        self.coord.hold_active = False
        self.coord.schedule_provider.get_decision.return_value = ProviderDecision(False, None, False, False)
        self.coord.learned_provider.get_decision.return_value = ProviderDecision(False, None, False, True)
        
        data = self.run_async(self.coord._async_update_data())
        trace = data.decision_trace
        
        self.assertEqual(trace["schema_version"], 1)
        self.assertIn("evaluated_at", trace)
        self.assertIn("providers", trace)

    def test_shadow_safety_metrics(self):
        """Test that safety violations are counted in Shadow Mode."""
        self.coord.hold_active = False
        
        # Scenario: 
        # Schedule says Run (should_stop=False)
        # Learned says Stop (should_stop=True)
        # Actual Temp is VERY Low (Safety Violation)
        
        self.coord.schedule_provider.get_decision.return_value = ProviderDecision(False, None, True, False)
        self.coord.learned_provider.get_decision.return_value = ProviderDecision(True, None, True, True)
        
        # Temp 15, Target 21. Tolerance 0.5. Floor = 20.3. 
        # 15 < 20.3 -> Violation.
        self.coord._get_operative_temperature.return_value = 15.0
        
        data = self.run_async(self.coord._async_update_data())
        
        metrics = data.decision_trace["metrics"]
        self.assertEqual(metrics["safety_violations"], 1)

if __name__ == "__main__":
    unittest.main()
