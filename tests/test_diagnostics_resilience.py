import unittest
import sys
import types
from unittest.mock import MagicMock, patch, AsyncMock, call
from datetime import datetime, timedelta, timezone

# Ensure homeassistant mock modules exist (as in test_resilience.py)
if 'homeassistant' not in sys.modules:
    ha = types.ModuleType("homeassistant")
    ha.__path__ = []
    sys.modules['homeassistant'] = ha
    ha.core = MagicMock()
    sys.modules['homeassistant.core'] = ha.core
    ha.config_entries = MagicMock()
    sys.modules['homeassistant.config_entries'] = ha.config_entries
    ha.const = MagicMock()
    sys.modules['homeassistant.const'] = ha.const
    
    ha.helpers = types.ModuleType("homeassistant.helpers")
    ha.helpers.__path__ = []
    sys.modules['homeassistant.helpers'] = ha.helpers
    ha.helpers.issue_registry = MagicMock()
    sys.modules['homeassistant.helpers.issue_registry'] = ha.helpers.issue_registry
    
    sys.modules['homeassistant.helpers.update_coordinator'] = MagicMock()

# Import the actual classes under test
import custom_components.preheat.coordinator as coord_mod
import custom_components.preheat.diagnostics as diag_mod
from custom_components.preheat.coordinator import PreheatingCoordinator
from custom_components.preheat.diagnostics import DiagnosticsManager
from custom_components.preheat.const import DOMAIN, STARTUP_GRACE_SEC

class TestDiagnosticsResilience(unittest.TestCase):

    @patch("custom_components.preheat.coordinator._LOGGER")
    def test_startup_grace_suppression(self, mock_logger):
        """Test that Sensor Timeout errors are logged as DEBUG within grace period or low failure counts."""
        async def run_test():
            hass = MagicMock()
            entry = MagicMock()
            entry.entry_id = "test_resilience_entry"
            entry.title = "Test Zone"
            entry.options = {}
            entry.data = {}
            
            coord = PreheatingCoordinator(hass, entry)
            
            # Start at startup time
            startup_time = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)
            coord._startup_time = startup_time
            
            # Mock collect_context to return is_sensor_ready = False
            coord._collect_context = AsyncMock(return_value={
                "is_sensor_ready": False
            })
            
            # 1. First failure inside grace period -> should log DEBUG
            coord_mod.dt_util.utcnow.return_value = startup_time + timedelta(seconds=10)
            await coord._async_update_data()
            mock_logger.debug.assert_called_with("Update Cycle Error [Test Zone]: Sensor Timeout / Unavailable")
            mock_logger.warning.assert_not_called()
            mock_logger.error.assert_not_called()
            mock_logger.debug.reset_mock()
                
            # Move time to outside startup grace (e.g. 2000 seconds)
            outside_grace_time = startup_time + timedelta(seconds=2000)
            coord_mod.dt_util.utcnow.return_value = outside_grace_time
            
            # Reset error counter to 0 for controlled testing
            coord._consecutive_readiness_errors = 0
            
            # 2. First failure outside grace period -> should log DEBUG (since count < 3)
            await coord._async_update_data()
            self.assertEqual(coord._consecutive_readiness_errors, 1)
            mock_logger.debug.assert_called_with("Update Cycle Error [Test Zone]: Sensor Timeout / Unavailable")
            mock_logger.warning.assert_not_called()
            mock_logger.debug.reset_mock()
            
            # 3. Second failure outside grace period -> should log DEBUG (count = 2 < 3)
            await coord._async_update_data()
            self.assertEqual(coord._consecutive_readiness_errors, 2)
            mock_logger.debug.assert_called_with("Update Cycle Error [Test Zone]: Sensor Timeout / Unavailable")
            mock_logger.warning.assert_not_called()
            mock_logger.debug.reset_mock()
            
            # 4. Third failure outside grace period -> should log WARNING (count = 3 >= 3)
            await coord._async_update_data()
            self.assertEqual(coord._consecutive_readiness_errors, 3)
            mock_logger.debug.assert_not_called()
            mock_logger.warning.assert_called_with("Update Cycle Error [Test Zone]: Sensor Timeout / Unavailable")
            mock_logger.warning.reset_mock()
            
            # 5. Success reset check
            coord._collect_context.return_value = {
                "is_sensor_ready": True,
                "forecasts": None
            }
            # Mock simulation, decision, actions, post tasks so it doesn't crash on True branch
            coord._run_physics_simulation = AsyncMock(return_value={
                "predicted_duration": 0.0, "uncapped_duration": 0.0,
                "delta_in": 0.0, "delta_out": 0.0, "prognosis": "ok", "weather_available": False,
                "limit_exceeded": False
            })
            coord._evaluate_start_decision = MagicMock()
            coord._execute_control_actions = AsyncMock()
            coord._post_update_tasks = AsyncMock()
            coord._build_preheat_data = MagicMock()
            
            await coord._async_update_data()
            self.assertEqual(coord._consecutive_readiness_errors, 0)
                
        import asyncio
        asyncio.run(run_test())

    @patch("custom_components.preheat.diagnostics.DiagnosticsManager._create_issue")
    @patch("custom_components.preheat.diagnostics.DiagnosticsManager._delete_issue")
    def test_learning_stalled_off_season(self, mock_delete, mock_create):
        """Test that learning_stalled is only raised if a learning attempt has occurred since last sample and is recent."""
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_diagnostics_entry"
        entry.title = "Test Zone"
        
        # Instantiate coordinator & manager
        coord = PreheatingCoordinator(hass, entry)
        manager = DiagnosticsManager(hass, entry, coord)
        
        # Setup physics model mock with samples
        physics = MagicMock()
        physics.sample_count = 10
        
        # 1. No learning attempt since last sample change (e.g. last_learning_attempt_ts <= last_sample_change)
        now = 2000000000.0
        dt_now = datetime.fromtimestamp(now, tz=timezone.utc)
        diag_mod.dt_util.utcnow.return_value = dt_now
        
        manager.data["last_sample_count"] = 10
        manager.data["last_sample_change"] = now - 800000.0 # > 7 days ago (604800s)
        manager.data["last_learning_attempt_ts"] = now - 900000.0 # Before last sample change
        
        physics.mass_factor = 20.0
        physics.loss_factor = 5.0
        pred = {"limit_exceeded": False, "uncapped_duration": 0.0}
        
        import asyncio
        asyncio.run(manager._diag_physics(MagicMock(), physics, MagicMock(), pred))
        
        # Issue should NOT be created and delete should be called
        self.assertNotIn(call("learning_stalled"), mock_create.call_args_list)
        mock_delete.assert_any_call("learning_stalled")
        mock_delete.reset_mock()
        mock_create.reset_mock()
        
        # 2. A learning attempt occurred since last sample change (last_learning_attempt_ts > last_sample_change) and is recent (e.g., 5 days ago < 14 days)
        manager.data["last_learning_attempt_ts"] = now - 432000.0 # 5 days ago (after now - 800000)
        
        asyncio.run(manager._diag_physics(MagicMock(), physics, MagicMock(), pred))
        
        # Issue should be created
        mock_create.assert_any_call("learning_stalled")
        self.assertNotIn(call("learning_stalled"), mock_delete.call_args_list)
        mock_delete.reset_mock()
        mock_create.reset_mock()
        
        # 3. A learning attempt occurred since last sample change, but is veraltet/expired (e.g., 15 days ago > 14 days)
        manager.data["last_sample_change"] = now - 1728000.0 # 20 days ago
        manager.data["last_learning_attempt_ts"] = now - 1296000.0 # 15 days ago (after last sample change, but > 14 days ago)
        
        asyncio.run(manager._diag_physics(MagicMock(), physics, MagicMock(), pred))
        
        # Issue should NOT be created and delete should be called
        self.assertNotIn(call("learning_stalled"), mock_create.call_args_list)
        mock_delete.assert_any_call("learning_stalled")

if __name__ == "__main__":
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    unittest.main()

