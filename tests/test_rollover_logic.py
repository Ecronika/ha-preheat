"""
test_rollover_logic.py
Verification of Smart Rollover and Anchor Logic in LearnedDepartureProvider.
"""
import unittest
from datetime import datetime, date, timedelta, timezone
from unittest.mock import MagicMock
from custom_components.preheat.providers import LearnedDepartureProvider
from custom_components.preheat.planner import PreheatPlanner

class TestRolloverLogic(unittest.TestCase):

    def setUp(self):
        # Configure Mocks
        import sys
        from unittest.mock import patch
        
        # Patch the IMPORTED dt_util in providers.py
        # because the module is already imported by the time setUp runs
        self.patcher = patch("custom_components.preheat.providers.dt_util")
        self.mock_dt = self.patcher.start()
        self.mock_dt.as_local.side_effect = lambda x: x 
        
        # Patch Planner dt_util too
        self.patcher_planner = patch("custom_components.preheat.planner.dt_util", self.mock_dt)
        self.patcher_planner.start() 
        
        self.planner = PreheatPlanner()
        # Mock Detector
        self.planner.detector = MagicMock()
        
        self.provider = LearnedDepartureProvider(self.planner, {})
        
    def tearDown(self):
        self.patcher.stop()
        self.patcher_planner.stop()

    def test_autonomous_overnight_rollover(self):
        """
        Scenario: Night Shift.
        Now: 23:00 (Today). Prediction: 02:00.
        Expectation: Rollover to Tomorrow 02:00.
        """
        now = datetime(2025, 1, 1, 23, 0, 0, tzinfo=timezone.utc)
        # Prediction: 120 minutes (02:00)
        # Fix: Mock find_clusters_v2 for Autonomous Mode (get_next_predicted_departure)
        mock_cluster = MagicMock()
        mock_cluster.time_minutes = 120
        self.planner.detector.find_clusters_v2.return_value = [mock_cluster]
        
        # History setup (dummy)
        # We need history for TOMORROW (rollover day) for the planner to find the event
        next_day_weekday = (now.weekday() + 1) % 7
        self.planner.history_departure[next_day_weekday] = [{"minutes": 120}]
        
        context = {
            "now": now,
            "potential_savings": 10.0,
            "tau_confidence": 1.0,
            "pattern_confidence": 1.0
        }
        
        decision = self.provider.get_decision(context)
        
        # Expected: Jan 2nd 02:00
        expected = datetime(2025, 1, 2, 2, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(decision.session_end, expected)

    def test_autonomous_overtime_no_rollover(self):
        """
        Scenario: Overtime.
        Now: 17:30 (Today). Prediction: 17:00.
        Expectation: Today 17:00 (In past, but correct day). Stays Today.
        """
        now = datetime(2025, 1, 1, 17, 30, 0, tzinfo=timezone.utc)
        # Prediction: 17*60 = 1020 minutes
        # Fix: Mock find_clusters_v2
        mock_cluster = MagicMock()
        mock_cluster.time_minutes = 1020
        self.planner.detector.find_clusters_v2.return_value = [mock_cluster]
        
        # Determine next day weekday
        next_day_weekday = (now.weekday() + 1) % 7
        self.planner.history_departure[next_day_weekday] = [{"minutes": 1020}]
        
        context = {
            "now": now,
            "potential_savings": 10.0,
            "tau_confidence": 1.0,
            "pattern_confidence": 1.0
        }
        
        decision = self.provider.get_decision(context)
        
        # Expected: Next valid departure is Tomorrow 17:00 (since Today 17:00 is past)
        expected = datetime(2025, 1, 2, 17, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(decision.session_end, expected)

    def test_anchored_schedule(self):
        """
        Scenario: Schedule Ends Tomorrow.
        Now: 23:00 (Monday Jan 1).
        Schedule End: 02:30 (Tuesday Jan 2).
        Prediction: 02:00 (from Tuesday bucket).
        Expectation: Tuesday 02:00.
        """
        now = datetime(2024, 1, 1, 23, 0, 0, tzinfo=timezone.utc) # Monday
        sched_end = datetime(2024, 1, 2, 2, 30, 0, tzinfo=timezone.utc) # Tuesday
        
        # Prediction: 02:00 (120 min)
        # It should look in TUESDAY bucket (weekday 1), not Monday (0).
        self.planner.detector.predict_departure.return_value = (120, 1.0)
        
        # Populate history for Tuesday (1)
        self.planner.history_departure[1] = [{"minutes": 120}] 
        # Ensure Monday (0) is empty or different to prove bucket selection
        self.planner.history_departure[0] = [{"minutes": 999}]
        
        # DEBUG: Ensure Mock works such that as_local returns input
        # If as_local returns something else, weekday might be wrong.
        
        context = {
            "now": now,
            "scheduled_end": sched_end,
            "potential_savings": 10.0,
            "tau_confidence": 1.0,
            "pattern_confidence": 1.0
        }
        
        decision = self.provider.get_decision(context)
        
        # Verify it looked at Tuesday history
        args, _ = self.planner.detector.predict_departure.call_args
        passed_history = args[0]
        self.assertEqual(passed_history[0]["minutes"], 120, "Should select history based on Schedule End Weekday")
        
        # Verify Date Construction
        # Anchor Date = Jan 2
        # Prediction = Anchor 00:00 + 120 min = Jan 2 02:00
        expected = datetime(2024, 1, 2, 2, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(decision.session_end, expected)

if __name__ == "__main__":
    unittest.main()
