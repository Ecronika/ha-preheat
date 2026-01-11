
import sys
from unittest.mock import MagicMock
from datetime import datetime, date, timedelta, timezone

# Define Mocks
mock_hass = MagicMock()
mock_util = MagicMock()
mock_dt = MagicMock()

# Register in sys.modules
sys.modules['homeassistant'] = mock_hass
sys.modules['homeassistant.util'] = mock_util
sys.modules['homeassistant.util.dt'] = mock_dt

# Configure as_local behavior
def mock_as_local(dt):
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

mock_dt.as_local.side_effect = mock_as_local
mock_dt.UTC = timezone.utc
mock_dt.now.return_value = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

# Setup logging
import logging
logging.basicConfig(level=logging.DEBUG)

# NOW import planner
try:
    from custom_components.preheat.planner import PreheatPlanner
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

def test_debug():
    planner = PreheatPlanner()
    now = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    print(f"Now: {now}, Weekday: {now.weekday()}")
    
    # Add events for Today + 1 (Monday, Jan 2) at 08:00
    # Add 4 points: Jan 2, Jan 9, Jan 16, Jan 23.
    for i in range(4):
        d = datetime(2023, 1, 2 + i*7, 8, 0, tzinfo=timezone.utc)
        print(f"Adding arrival: {d}")
        planner.record_arrival(d)
        
    # Check History
    print("History keys:", planner.history.keys())
    for k, v in planner.history.items():
        print(f"Weekday {k}: {len(v)} entries. Sample: {v[0]}")
        
    # Predict
    print("\n--- Predicting ---")
    
    # Check candidates manually first
    check_date = date(2023, 1, 2)
    print(f"Candidates for {check_date}: {planner._get_candidates_for_date(check_date)}")
    
    next_evt = planner.get_next_scheduled_event(now, allowed_weekdays=None)
    print(f"Prediction Result: {next_evt}")
    
    if next_evt:
        print(f"Found: {next_evt}")
    else:
        print("FAILED to find event.")

if __name__ == "__main__":
    test_debug()
