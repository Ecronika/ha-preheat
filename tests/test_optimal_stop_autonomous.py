"""Tests for Optimal Stop Manager in Autonomous Mode (no schedule)."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import sys

# Mock HA modules
sys.modules['homeassistant'] = MagicMock()
sys.modules['homeassistant.config_entries'] = MagicMock()
sys.modules['homeassistant.const'] = MagicMock()
sys.modules['homeassistant.core'] = MagicMock()
sys.modules['homeassistant.helpers'] = MagicMock()
sys.modules['homeassistant.util'] = MagicMock()

from datetime import timezone
mock_dt = MagicMock()
mock_dt.UTC = timezone.utc
sys.modules["homeassistant.util.dt"] = mock_dt

from custom_components.preheat.optimal_stop import (
    OptimalStopManager, CONF_STOP_TOLERANCE, CONF_MAX_COAST_HOURS
)
from custom_components.preheat.const import (
    OS_REASON_INIT,
    OS_REASON_WAITING,
    OS_REASON_COASTING,
    OS_REASON_NO_SESSION,
    OS_REASON_TOO_COLD,
    OS_REASON_NO_TEMPERATURE,
)

class TestOptimalStopAutonomous(unittest.TestCase):
    
    def setUp(self):
        self.hass = MagicMock()
        self.manager = OptimalStopManager(self.hass)
        self.config = {
            CONF_STOP_TOLERANCE: 0.5,
            CONF_MAX_COAST_HOURS: 4.0
        }
        self.now = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        
        # Patch dt_util in optimal_stop module
        patcher = patch("custom_components.preheat.optimal_stop.dt_util")
        self.mock_dt_util = patcher.start()
        self.mock_dt_util.utcnow.side_effect = lambda: self.now
        self.addCleanup(patcher.stop)

    def test_n5_autonomous_scenarios_abc(self):
        """Test N5: A/B/C: schedule_end=None, predicted_end=now+3h, warm -> transitions out of initial reasons."""
        initial_reasons = [OS_REASON_INIT, OS_REASON_NO_TEMPERATURE, OS_REASON_TOO_COLD]
        
        for start_reason in initial_reasons:
            self.manager._reason = start_reason
            self.manager._active = False
            self.manager._savings_total = 0.0
            self.manager._stop_time = None
            
            # Mock calculations to return 15 min coasting
            with patch("custom_components.preheat.optimal_stop.calculate_coast_duration", return_value=15.0):
                self.manager.update(
                    current_temp=21.0,
                    target_temp=21.0,
                    schedule_end=None,
                    forecast_provider=lambda s, e: 10.0,
                    tau_hours=4.0,
                    config=self.config,
                    predicted_end=self.now + timedelta(hours=3)
                )
            
            # The manager should transition to waiting (or coasting depending on stop time wrapping)
            self.assertIn(self.manager._reason, [OS_REASON_WAITING, OS_REASON_COASTING])
            self.assertIsNotNone(self.manager._stop_time)
            self.assertGreater(self.manager._savings_total, 0.0)

    def test_n5_gegenprobe_d_with_schedule(self):
        """Test N5 Gegenprobe D: schedule_end=now+3h, predicted_end=None, warm -> waiting/coasting (regression)."""
        self.manager._reason = OS_REASON_INIT
        self.manager._active = False
        
        with patch("custom_components.preheat.optimal_stop.calculate_coast_duration", return_value=15.0):
            self.manager.update(
                current_temp=21.0,
                target_temp=21.0,
                schedule_end=self.now + timedelta(hours=3),
                forecast_provider=lambda s, e: 10.0,
                tau_hours=4.0,
                config=self.config,
                predicted_end=None
            )
            
        self.assertIn(self.manager._reason, [OS_REASON_WAITING, OS_REASON_COASTING])
        self.assertIsNotNone(self.manager._stop_time)

    def test_n5_gegenprobe_e_no_session(self):
        """Test N5 Gegenprobe E: schedule_end=None, predicted_end=None, warm -> no_session."""
        self.manager._reason = OS_REASON_INIT
        self.manager._active = False
        
        self.manager.update(
            current_temp=21.0,
            target_temp=21.0,
            schedule_end=None,
            forecast_provider=lambda s, e: 10.0,
            tau_hours=4.0,
            config=self.config,
            predicted_end=None
        )
        
        self.assertEqual(self.manager._reason, OS_REASON_NO_SESSION)
        self.assertFalse(self.manager.is_active)

    def test_n5_safety_remains(self):
        """Test N5 Safety remains: schedule_end=None, predicted_end=now+3h, cold -> too_cold."""
        self.manager._reason = OS_REASON_INIT
        self.manager._active = False
        
        # Target 21.0, stop tolerance 0.5 -> floor = 20.5.
        # current_temp = 20.2 -> < floor - 0.2 (20.3) -> should trigger safety break and set OS_REASON_TOO_COLD
        self.manager.update(
            current_temp=20.2,
            target_temp=21.0,
            schedule_end=None,
            forecast_provider=lambda s, e: 10.0,
            tau_hours=4.0,
            config=self.config,
            predicted_end=self.now + timedelta(hours=3)
        )
        
        self.assertEqual(self.manager._reason, OS_REASON_TOO_COLD)
        self.assertFalse(self.manager.is_active)
