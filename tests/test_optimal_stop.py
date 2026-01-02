import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import sys

# Mock HA modules
sys.modules['homeassistant'] = MagicMock()
sys.modules['homeassistant.config_entries'] = MagicMock()
sys.modules['homeassistant.const'] = MagicMock()
sys.modules['homeassistant.core'] = MagicMock()
sys.modules['homeassistant.helpers'] = MagicMock()
sys.modules['homeassistant.util'] = MagicMock()
# Explicitly mock dt_util since it is imported
# sys.modules["homeassistant.util.dt"] = MagicMock()
from datetime import timezone
mock_dt = MagicMock()
mock_dt.UTC = timezone.utc
sys.modules["homeassistant.util.dt"] = mock_dt

# from homeassistant.util import dt as dt_util

from custom_components.preheat.optimal_stop import OptimalStopManager, CONF_STOP_TOLERANCE, CONF_MAX_COAST_HOURS
from custom_components.preheat.const import DEFAULT_STOP_TOLERANCE, DEFAULT_MAX_COAST_HOURS

class FakeDT:
    def __init__(self, now_val):
        self._now = now_val
    def utcnow(self):
        return self._now

class TestOptimalStop(unittest.TestCase):
    
    def setUp(self):
        self.hass = MagicMock()
        self.manager = OptimalStopManager(self.hass)
        self.config = {
            CONF_STOP_TOLERANCE: 0.5,
            CONF_MAX_COAST_HOURS: 4.0
        }
        # Use simple fixed time
        self.now = datetime(2023, 1, 1, 12, 0, 0)
        
        # Patch local dt_util used in module
        # Note: We need to patch where it is IMPORTED
        patcher = patch("custom_components.preheat.optimal_stop.dt_util")
        self.mock_dt_util = patcher.start()
        self.mock_dt_util.utcnow.side_effect = lambda: self.now
        self.addCleanup(patcher.stop)

        
    def test_safety_break_too_cold(self):
        # Target 21.0, Tolerance 0.5 -> Floor 20.5
        # Current 20.2 -> Below Floor - 0.2 (20.3) -> Too Cold
        
        # Setup active state
        self.manager._active = True
        
        self.manager.update(
            current_temp=20.2,
            target_temp=21.0,
            schedule_end=self.now + timedelta(minutes=60),
            forecast_provider=lambda s,e: 0.0,
            tau_hours=4.0,
            config=self.config
        )
        
        self.assertFalse(self.manager.is_active)
        self.assertEqual(self.manager.debug_info["reason"], "too_cold_safety")

    def test_activation(self):
        # Target 21, Floor 20.5. Current 21.0. 
        # T_out 10. Tau 4h (~240 min).
        # Need to cool 0.5K from 21.
        # Temp Diff Start = 11. Diff End = 10.5. Ratio 0.95.
        # t = -240 * ln(0.954) ~ 11 mins.
        
        sched_end = self.now + timedelta(minutes=10) # 10 mins away
        
        # Should activate if calc duration > 10 min?
        # Actually calc duration ~11 mins.
        # Savings > 10 min threshold? 11 > 10.
        # Stop Time = End - 11 mins = Now - 1 min.
        # Now >= Stop Time? Yes.
        
        # Mock calculate_coast_duration to control value precisely
        with patch("custom_components.preheat.optimal_stop.calculate_coast_duration", return_value=15.0):
             self.manager.update(
                current_temp=21.0,
                target_temp=21.0,
                schedule_end=sched_end,
                forecast_provider=lambda s,e: 10.0,
                tau_hours=4.0,
                config=self.config
            )
            
        self.assertTrue(self.manager.is_active)
        self.assertEqual(self.manager.debug_info["reason"], "coasting")
        self.assertEqual(self.manager._savings_total, 15.0) # 15 min savings
        # Remaining savings: sched_end - now = 10 min.
        self.assertAlmostEqual(self.manager._savings_remaining, 10.0, delta=1.0)

    def test_latch_reset_setpoint(self):
        # Activate
        self.manager._active = True
        self.manager._last_target_temp = 21.0
        
        # Change target
        self.manager.update(
            current_temp=21.5, # Boost current temp to avoid "Too Cold" safety break (21.5 > 21.3)
            target_temp=22.0, # Changed
            schedule_end=self.now + timedelta(minutes=60),
            forecast_provider=lambda s,e: 0.0,
            tau_hours=4.0,
            config=self.config
        )
        
        self.assertFalse(self.manager.is_active)
        self.assertEqual(self.manager.debug_info["reason"], "setpoint_increase")

    def test_latch_reset_schedule_off_debounce(self):
        self.manager._active = True
        
        # Schedule OFF (None)
        # First call: Debounce start
        self.manager.update(21, 21, None, None, 4.0, self.config)
        self.assertTrue(self.manager.is_active) # Still active (debouncing)
        
        # Wait 130s (Simulated via patching dt_util.utcnow?) or manipulate property
        # self.manager._schedule_off_since set internally.
        # We manually shift internal time tracker?
        # Better: create a mock for dt_util.utcnow() but imported inside module
        # Or just manipulate _schedule_off_since in test
        
        self.manager._schedule_off_since -= timedelta(seconds=130)
        
        # Next call
        self.manager.update(21, 21, None, None, 4.0, self.config)
        self.assertFalse(self.manager.is_active)
        self.assertEqual(self.manager.debug_info["reason"], "no_session")
