"""Tests for Cooling Analyzer."""
import sys
import unittest
from datetime import datetime, timedelta
import math
from unittest.mock import MagicMock

# --- MOCK Home Assistant ---
import types
ha = types.ModuleType("homeassistant")
ha.__path__ = []
sys.modules["homeassistant"] = ha
sys.modules["homeassistant.util"] = MagicMock()

# Mock dt_util for import
mock_dt = MagicMock()
sys.modules["homeassistant.util.dt"] = mock_dt

from custom_components.preheat.cooling_analyzer import CoolingAnalyzer

class TestCoolingAnalyzer(unittest.TestCase):
    
    def setUp(self):
        self.analyzer = CoolingAnalyzer()
        self.start_dt = datetime(2024, 1, 1, 12, 0, 0)
        
    def test_add_data_filtering(self):
        # Heating shouldn't be valid
        self.analyzer.add_data_point(self.start_dt, 20.0, 10.0, is_heating=True)
        self.assertFalse(self.analyzer._buffer[-1]["valid"])
        
        # Window Open shouldn't be valid
        self.analyzer.add_data_point(self.start_dt, 20.0, 10.0, is_heating=False, window_open=True)
        self.assertFalse(self.analyzer._buffer[-1]["valid"])
        
        # Idle + Closed = Valid
        self.analyzer.add_data_point(self.start_dt, 20.0, 10.0, is_heating=False, window_open=False)
        self.assertTrue(self.analyzer._buffer[-1]["valid"])

    def test_analyze_ideal_cooling(self):
        """Test with perfect exponential decay data."""
        # Tau = 4.0 hours
        true_tau = 4.0
        t_out = 10.0
        t_start = 22.0
        
        # Generate 2 hours of data
        for i in range(120): # 120 minutes
            dt = self.start_dt + timedelta(minutes=i)
            hours = i / 60.0
            
            # Physics: T(t) = Tout + (Start-Tout)*exp(-t/tau)
            t_in = t_out + (t_start - t_out) * math.exp(-hours/true_tau)
            
            self.analyzer.add_data_point(dt, t_in, t_out, is_heating=False)
            
        stats = self.analyzer.analyze()
        
        # Check Tau
        self.assertIn("tau", stats)
        learned = stats["tau"]
        self.assertAlmostEqual(learned, true_tau, delta=0.2) # Allow some regression noise/rounding
        
        # Check Confidence
        self.assertGreater(stats["confidence"], 0.8) # Should be high for perfect data
        
    def test_analyze_rising_temp_rejection(self):
        """Test rejection of rising temperature (Solar Gain)."""
        t_out = 10.0
        for i in range(120):
            dt = self.start_dt + timedelta(minutes=i)
            # Rising temp
            t_in = 20.0 + (i * 0.01) 
            self.analyzer.add_data_point(dt, t_in, t_out, is_heating=False)
            
        stats = self.analyzer.analyze()
        # Should reject segment
        self.assertEqual(stats["status"], "no_valid_fits") 

    def test_analyze_short_segment(self):
        """Test short segment rejection."""
        # Clean buffers
        self.analyzer = CoolingAnalyzer()
        
        for i in range(30): # 30 mins (threshold is 60)
            dt = self.start_dt + timedelta(minutes=i)
            t_in = 22.0 - (i * 0.01)
            self.analyzer.add_data_point(dt, t_in, 10.0, is_heating=False)
            
        # Break segment with heating
        self.analyzer.add_data_point(self.start_dt+timedelta(minutes=31), 21.0, 10.0, is_heating=True)
            
        stats = self.analyzer.analyze()
        if "segments" in stats:
             self.assertEqual(stats.get("segments", 0), 0)
        else:
             self.assertIn(stats["status"], ["no_segments", "no_valid_fits"])
