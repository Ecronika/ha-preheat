
import unittest
import sys
import os

import importlib.util

# Load history_buffer directly to avoid triggering __init__.py of the package
spec = importlib.util.spec_from_file_location(
    "history_buffer", 
    os.path.abspath(os.path.join(os.path.dirname(__file__), '../custom_components/preheat/history_buffer.py'))
)
history_buffer = importlib.util.module_from_spec(spec)
sys.modules["history_buffer"] = history_buffer
spec.loader.exec_module(history_buffer)

DeadtimeAnalyzer = history_buffer.DeadtimeAnalyzer
HistoryPoint = history_buffer.HistoryPoint

class TestDeadtimeLogic(unittest.TestCase):

    def create_curve(self, deadtime_min, slope_k_min, duration_min):
        """Create a synthetic heating curve."""
        data = []
        start_ts = 100000.0
        base_temp = 20.0
        
        # 60 mins before start (Steady)
        for i in range(60):
            data.append(HistoryPoint(start_ts, base_temp, 0.0, False))
            start_ts += 60.0
            
        # Start Event at index 60
        t0 = start_ts
        
        # Deadtime phase (active but no rise)
        for i in range(int(deadtime_min)):
            data.append(HistoryPoint(start_ts, base_temp, 100.0, True))
            start_ts += 60.0
            
        # Heating phase (linear rise for simplicity, approximating the max slope area)
        current_temp = base_temp
        for i in range(int(duration_min - deadtime_min)):
            current_temp += slope_k_min # Linear rise
            data.append(HistoryPoint(start_ts, current_temp, 100.0, True))
            start_ts += 60.0
            
        return data, t0

    def test_deadtime_detection_ideal(self):
        analyzer = DeadtimeAnalyzer()
        
        # Case 1: Ideal 30 min deadtime, fast heating (0.1K/min)
        data, t0 = self.create_curve(30, 0.1, 90)
        
        deadtime = analyzer.analyze(data)
        
        print(f"Detected Ideal: {deadtime}")
        self.assertIsNotNone(deadtime)
        self.assertTrue(25.0 <= deadtime <= 35.0)

    def test_deadtime_detection_slow_floor(self):
        analyzer = DeadtimeAnalyzer()
        
        # Case 2: 120 min deadtime, slow heating (0.02K/min)
        data, t0 = self.create_curve(120, 0.02, 240) # 4 hours total
        
        deadtime = analyzer.analyze(data)
        
        print(f"Detected Slow: {deadtime}")
        self.assertIsNotNone(deadtime)
        self.assertTrue(110.0 <= deadtime <= 130.0)

    def test_no_start_event(self):
        analyzer = DeadtimeAnalyzer()
        data = [HistoryPoint(100.0 + i*60, 20.0, 0.0, False) for i in range(100)]
        self.assertIsNone(analyzer.analyze(data))

    def test_insufficient_data(self):
        analyzer = DeadtimeAnalyzer()
        data = [HistoryPoint(100.0, 20.0, 0.0, True)] # One point
        self.assertIsNone(analyzer.analyze(data))

if __name__ == '__main__':
    unittest.main()
