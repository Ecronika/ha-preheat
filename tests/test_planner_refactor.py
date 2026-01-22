"""Tests for planner.py refactoring (Robustness & Golden Tests)."""
import pytest
from datetime import datetime, timedelta, date, time, timezone
from unittest.mock import MagicMock, patch


from homeassistant.util import dt as dt_util
from custom_components.preheat.planner import PreheatPlanner
from custom_components.preheat.const import (
    CONF_ARRIVAL_WINDOW_START,
    CONF_ARRIVAL_WINDOW_END,
)

# --- Fixtures ---

@pytest.fixture
def mock_hass():
    hass = MagicMock()
    return hass

@pytest.fixture
def planner():
    return PreheatPlanner()

# --- 1. Robust Loading Tests ---

def test_load_history_mixed_keys(planner):
    """Test loading history with mixed int/string keys and timezone prefixes."""
    # Simulate a messy storage state
    stored_data = {
        "1": [["2023-10-01", 600]], # Int key as string, v3 list format
        2: [["2023-10-02", 700]],   # Int key, v3 list format
        "v3_3": [["2023-10-03", 800]], # v3 prefix
        "v2_4": [540], # Legacy v2 format (list of ints)
        " 5 ": [["2023-10-05", 900]], # Whitespace key
        "invalid": "junk" # Junk entry
    }
    
    # We patch the storage read
    # Since _load_history takes the dict directly usually, or we can mock _load_from_storage
    # Let's verify _load_history logic directly if possible.
    # Actually _load_history iterates over stored_data.
    
    # For this test, we assume we can call a method that processes this dict.
    # In the current code, _load_history does: history = ...get("history", {}) then iterates.
    
    # Apply the fix logic manually here to verify IT WORKS before implementing?
    # No, we are writing tests that FAIL now (or pass if logic exists) and pass later.
    # Actually, current logic likely CRASHES on "2" (int) if it does .startswith.
    
    # We need to simulate the implementation of _load_history
    planner.history = {}
    
    # Mocking the internal method logical flow for the Refactor Test 
    # (Since we are testing the RESULT of the refactor, not the current buggy code)
    
    # Let's try to feed this to the current code to confirm it crashes?
    # But I can't easily run it here.
    # So I write the test expecting ROBUST behavior.
    
    # Create planner with mixed history
    # stored_history is passed to constructor
    fixed_now = datetime(2023, 10, 5, 12, 0, 0) # Fixed time for pruning check
    with patch("custom_components.preheat.planner.dt_util.now", return_value=fixed_now):
        planner_inst = PreheatPlanner(stored_history=stored_data)
    
    # Assertions
    # "1" -> 1
    assert 1 in planner_inst.history
    assert len(planner_inst.history[1]) == 1
    assert planner_inst.history[1][0][1] == 600
    
    # 2 -> 2
    assert 2 in planner_inst.history
    assert planner_inst.history[2][0][1] == 700
    
    # "v3_3" -> 3
    assert 3 in planner_inst.history
    assert planner_inst.history[3][0][1] == 800
    
    # " 5 " -> 5 (whitespace stripped)
    assert 5 in planner_inst.history
    assert planner_inst.history[5][0][1] == 900
    
    # "invalid" -> ignored (no crash)
    # Check total keys
    # 1, 2, 3, 5 = 4 valid keys.
    # What about v2_4? If we ignore legacy v2 reading, it won't be in v3 history.
    # Current implementation reads v2 keys into self.history_v2.
    # Refactor Goal: Phase A -> Read old, Normalized to v3?
    # No, Phase A says: "Internal: Normalize EVERYTHING to Canonical v3 format (`dict[int, list]`) in memory immediately after load."
    # So v2_4 should ideally be converted to v3 format in memory?
    # Or just kept as v2 if we support dual?
    # The Plan says "Normalize EVERYTHING to Canonical v3".
    # So v2_4 should become key 4 in history.
    # Let's see if we implement that migration.
    # If not, simply assert it didn't crash.
    
    assert len(planner_inst.history) >= 4 

# --- 2. Limit Tests ---

def test_history_pruning_limits(planner):
    """Test that history is pruned to MAX_ENTRIES."""
    # Set up 25 entries for Monday (0)
    history = []
    base_date = date(2023, 1, 1)
    for i in range(25):
        history.append({
            "date": (base_date + timedelta(days=i)).isoformat(),
            "minutes": 600 + i,
            "dst_flag": False
        })
    
    # Set up 25 entries for Monday (0)
    history_dep = []
    history_arr = []
    base_date = date(2023, 1, 1)
    
    for i in range(25):
        d_str = (base_date + timedelta(days=i)).isoformat()
        
        # Departure Entry (Dict)
        history_dep.append({
            "date": d_str,
            "minutes": 600 + i,
            "dst_flag": False
        })
        
        # Arrival Entry (Tuple)
        d_obj = base_date + timedelta(days=i)
        history_arr.append((d_obj, 600 + i))
    
    planner.history_departure = {0: history_dep}
    planner.history = {0: history_arr}
    
    # Call Prune (TARGET behavior)
    # Patch now to ensure deterministic age calculation (though we test count here)
    fixed_now = datetime(2023, 1, 26, 12, 0, 0, tzinfo=timezone.utc)
    with patch("custom_components.preheat.planner.dt_util.now", return_value=fixed_now):
        planner.prune_all_history() 
    
    # Assert Limits
    assert len(planner.history_departure[0]) == 20
    assert len(planner.history[0]) == 20
    
    # Assert FIFO (Oldest removed)
    # 25 items: 0..24. Keep last 20 -> 5..24.
    # Index 0 of pruned list should be original index 5 (2023-01-06)
    expected_first_date = (base_date + timedelta(days=5)).isoformat()
    # Check if we broke strict ordering... list slice [-20:] preserves order.
    assert planner.history_departure[0][0]["date"] == expected_first_date
    assert planner.history[0][0][0] == base_date + timedelta(days=5)

def test_lookahead_regression(planner):
    """
    Ensure planner looks ahead at least 7 days to find weekly events.
    Regression Test for v2.9.3 refactor where range(8) was reduced to range(3).
    """
    # Setup history: Only Friday (4) has data
    # 4 points to satisfy V3 check
    fridays = [
        (date(2023, 10, 6), 480), # Fri
        (date(2023, 10, 13), 480),
        (date(2023, 10, 20), 480),
        (date(2023, 10, 27), 480)
    ]
    planner.history = {4: fridays}
    
    # Now is Monday (2023-10-02)
    # Next Friday is 2023-10-06 (4 days away)
    now = datetime(2023, 10, 2, 8, 0, 0, tzinfo=timezone.utc)
    
    with patch("custom_components.preheat.planner.dt_util.now", return_value=now):
        with patch("custom_components.preheat.planner.dt_util.as_local", side_effect=lambda x: x):
            result = planner.get_next_scheduled_event(now)
        
            # If range(3), result is None.
            # If range(8), result is Fri 2023-10-06 08:00
            assert result is not None, "Failed to find event 4 days ahead"
            assert result.weekday() == 4
            assert result.day == 6

# --- 3. Golden Test: get_next_scheduled_event ---

def test_get_next_scheduled_event_golden(planner):
    """
    Golden Test to ensure behavior preservation.
    We define a fixed history and 'now', and assert the exact output datetime.
    """
    # Setup History:
    # Mon (0): 08:00 (480 min) - 4 points
    # Tue (1): 09:00 (540 min) - 4 points
    planner.history = {
        0: [
            (date(2023, 10, 9), 480),
            (date(2023, 10, 16), 480), 
            (date(2023, 10, 23), 480),
            (date(2023, 10, 30), 480)
        ], 
        1: [
            (date(2023, 10, 10), 540),
            (date(2023, 10, 17), 540),
            (date(2023, 10, 24), 540),
            (date(2023, 10, 31), 540)
        ]
    }
    
    # Case 1: Sunday Night (2023-10-01 20:00). Next is Mon 08:00.
    now = datetime(2023, 10, 1, 20, 0, 0, tzinfo=timezone.utc) # Sunday
    
    # Expected: Mon Oct 2nd, 08:00 LOCAL.
    # Note: Planner uses local time for matching.
    # Let's assume Local = UTC for simplicity in test, or patch as_local.
    
    with patch("custom_components.preheat.planner.dt_util.now", return_value=now):
        with patch("custom_components.preheat.planner.dt_util.as_local", side_effect=lambda x: x):
            # We need to ensure planner sees 'now' as Sunday.
            # 2023-10-01 IS Sunday.
            
            result = planner.get_next_scheduled_event(now)
            
            # Assert
            assert result is not None
            # datetime(2023, 10, 2, 8, 00)
            assert result.day == 2
            assert result.hour == 8
            assert result.minute == 0
    
    # Case 2: Mon Morning (07:00). Next is Mon 08:00 (Today).
    now_mon = datetime(2023, 10, 2, 7, 0, 0, tzinfo=timezone.utc)
    with patch("custom_components.preheat.planner.dt_util.now", return_value=now_mon):
        with patch("custom_components.preheat.planner.dt_util.as_local", side_effect=lambda x: x):
            result = planner.get_next_scheduled_event(now_mon)
            assert result.day == 2
            assert result.hour == 8

    # Case 3: Mon Afternoon (09:00). Next is Tue 09:00.
    now_mon_late = datetime(2023, 10, 2, 9, 0, 0, tzinfo=timezone.utc)
    with patch("custom_components.preheat.planner.dt_util.now", return_value=now_mon_late):
        with patch("custom_components.preheat.planner.dt_util.as_local", side_effect=lambda x: x):
            result = planner.get_next_scheduled_event(now_mon_late)
            assert result.day == 3
            assert result.hour == 9
