import unittest
import sys
from unittest.mock import MagicMock

# Mock HA modules to allow importing custom_components.preheat package
sys.modules['homeassistant'] = MagicMock()
sys.modules['homeassistant.config_entries'] = MagicMock()
sys.modules['homeassistant.const'] = MagicMock()
sys.modules['homeassistant.core'] = MagicMock()
sys.modules['homeassistant.helpers'] = MagicMock()
sys.modules['homeassistant.util'] = MagicMock()

from datetime import datetime, timedelta, timezone
from custom_components.preheat import math_preheat
from custom_components.preheat.const import RISK_BALANCED, RISK_PESSIMISTIC, RISK_OPTIMISTIC

UTC = timezone.utc

class TestMathPreheat(unittest.TestCase):

    def test_integrate_basic(self):
        """Test simple rectangular integration."""
        start = datetime(2023, 1, 1, 10, 0, tzinfo=UTC)
        end = datetime(2023, 1, 1, 12, 0, tzinfo=UTC)
        
        forecasts = [
            {"datetime": datetime(2023, 1, 1, 9, 0, tzinfo=UTC), "temperature": 10.0},
            {"datetime": datetime(2023, 1, 1, 13, 0, tzinfo=UTC), "temperature": 10.0},
        ]
        
        avg = math_preheat.integrate_forecast(forecasts, start, end)
        self.assertEqual(avg, 10.0)

    def test_integrate_ramp(self):
        """Test integration of a ramp from 0 to 10 over 2 hours."""
        start = datetime(2023, 1, 1, 10, 0, tzinfo=UTC) # Temp 0
        end = datetime(2023, 1, 1, 12, 0, tzinfo=UTC)   # Temp 10
        
        forecasts = [
            {"datetime": datetime(2023, 1, 1, 10, 0, tzinfo=UTC), "temperature": 0.0},
            {"datetime": datetime(2023, 1, 1, 12, 0, tzinfo=UTC), "temperature": 10.0},
        ]
        
        avg = math_preheat.integrate_forecast(forecasts, start, end)
        self.assertAlmostEqual(avg, 5.0, delta=0.1)

    def test_integrate_irregular(self):
        """Test irregular intervals (Trapezoidal logic)."""
        start = datetime(2023, 1, 1, 10, 0, tzinfo=UTC)
        end = datetime(2023, 1, 1, 12, 0, tzinfo=UTC) # 2 Hours
        
        forecasts = [
            {"datetime": datetime(2023, 1, 1, 10, 0, tzinfo=UTC), "temperature": 0.0},
            {"datetime": datetime(2023, 1, 1, 11, 59, tzinfo=UTC), "temperature": 0.0},
            {"datetime": datetime(2023, 1, 1, 12, 0, tzinfo=UTC), "temperature": 100.0}, 
        ]
        
        avg = math_preheat.integrate_forecast(forecasts, start, end)
        # 50/120 = 0.4166
        self.assertAlmostEqual(avg, 0.416, delta=0.01)

    def test_resample_metrics(self):
        """Test P10/P90 logic."""
        start = datetime(2023, 1, 1, 10, 0, tzinfo=UTC)
        end = datetime(2023, 1, 1, 12, 0, tzinfo=UTC)
        
        forecasts = [
            {"datetime": datetime(2023, 1, 1, 10, 0, tzinfo=UTC), "temperature": 0.0},
            {"datetime": datetime(2023, 1, 1, 11, 0, tzinfo=UTC), "temperature": 0.0},
            {"datetime": datetime(2023, 1, 1, 11, 1, tzinfo=UTC), "temperature": 10.0}, 
            {"datetime": datetime(2023, 1, 1, 12, 0, tzinfo=UTC), "temperature": 10.0},
        ]
        
        p10 = math_preheat.calculate_risk_metric(forecasts, start, end, RISK_PESSIMISTIC)
        p90 = math_preheat.calculate_risk_metric(forecasts, start, end, RISK_OPTIMISTIC)
        
        self.assertAlmostEqual(p10, 0.0, delta=1.0)
        self.assertAlmostEqual(p90, 10.0, delta=1.0)

    def test_root_finding_monotonic(self):
        """Test finding duration for simple linear case."""
        eval_func = lambda d: 60 - d 
        root = math_preheat.root_find_duration(eval_func, max_minutes=180)
        self.assertAlmostEqual(root, 60.0, delta=1.0)

    def test_root_finding_non_monotonic(self):
        """Test 'Best Bracket' logic."""
        def eval_func(d):
            if d < 30: return 10 
            if d < 40: return -5 
            if d < 100: return 10 
            return -5 
            
        root = math_preheat.root_find_duration(eval_func, max_minutes=180)
        # Should find 30-40 bracket, converged approx at 30?
        # Grid finds 30 (because eval(30)=-5). So root in 25-30.
        # eval(25)=10, eval(30)=-5. 
        # Bisection(25, 30) -> Approx 26.66...
        self.assertTrue(25.0 <= root <= 30.0, f"Root {root} not in 25-30")

if __name__ == '__main__':
    unittest.main()
