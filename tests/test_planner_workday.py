"""Tests for Planner Workday Logic."""
import sys
import types
from unittest.mock import MagicMock

# 1. Root Packages (ModuleType to allow sub-imports)
ha = types.ModuleType("homeassistant")
sys.modules["homeassistant"] = ha

ha_helpers = types.ModuleType("homeassistant.helpers")
ha.helpers = ha_helpers
sys.modules["homeassistant.helpers"] = ha_helpers

ha_util = types.ModuleType("homeassistant.util")
ha.util = ha_util
sys.modules["homeassistant.util"] = ha_util

# 2. Leaf Modules (MagicMock to allow any attribute access)
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock()
sys.modules["homeassistant.const"] = MagicMock()
sys.modules["homeassistant.helpers.config_validation"] = MagicMock()
sys.modules["homeassistant.helpers.entity_platform"] = MagicMock()
sys.modules["homeassistant.helpers.typing"] = MagicMock()
sys.modules["homeassistant.util.dt"] = MagicMock()

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from custom_components.preheat.planner import PreheatPlanner
from homeassistant.util import dt as dt_util

# Mock dt_util behavior
dt_util.now.side_effect = lambda: datetime.now()
dt_util.UTC = None # minimal mock


from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from custom_components.preheat.planner import PreheatPlanner
from homeassistant.util import dt as dt_util

# Mock dt_util behavior
dt_util.now = MagicMock(side_effect=lambda: datetime.now())
dt_util.UTC = None # minimal mock

@pytest.fixture
def planner():
    return PreheatPlanner()

def dt(day_offset, hour, minute):
    """Helper to create test datetime from today."""
    now = dt_util.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
    return now + timedelta(days=day_offset)

def test_planner_all_days_allowed(planner):
    """Test standard behavior (no restriction)."""
    now = dt(0, 12, 0) # Today 12:00
    
    # Add events for Today + 1 (Tomorrow) at 08:00
    planner.record_arrival(dt(1, 8, 0))
    
    # Expect Tomorrow 08:00
    next_evt = planner.get_next_scheduled_event(now, allowed_weekdays=None)
    assert next_evt is not None
    assert next_evt.hour == 8
    assert next_evt.day == dt(1, 8, 0).day
    
def test_planner_weekend_skip(planner):
    """Test skipping weekend (Sat/Sun) when restricted."""
    # Setup: Now is Friday 12:00
    # Events every day at 08:00
    # We want to skip Sat, Sun and find Mon.
    
    # We cheat a bit: we don't control "Today" weekday in the class easily without mocking datetime.
    # But get_next_scheduled_event takes 'now'.
    
    # Let's find a Friday in 2024. Dec 13, 2024 is Friday.
    fixed_now = datetime(2024, 12, 13, 12, 0, 0, tzinfo=dt_util.UTC) # Friday
    
    # Add events for Sat(14), Sun(15), Mon(16)
    # Planner stores by weekday: Fri=4, Sat=5, Sun=6, Mon=0
    planner.history[5].append(8*60) # Sat 08:00
    planner.history[6].append(8*60) # Sun 08:00
    planner.history[0].append(8*60) # Mon 08:00
    
    # 1. Without restriction -> Sat 08:00
    res = planner.get_next_scheduled_event(fixed_now, allowed_weekdays=None)
    assert res is not None
    assert res.weekday() == 5 # Sat
    
    # 2. With Mon-Fri restriction ([0,1,2,3,4]) -> Expect Mon
    res = planner.get_next_scheduled_event(fixed_now, allowed_weekdays=[0,1,2,3,4])
    assert res is not None
    assert res.weekday() == 0 # Mon
    assert res.day == 16 # Dec 16

def test_planner_custom_workdays(planner):
    """Test custom workday set (e.g. Fri + Sat active)."""
    # Now = Thur (Dec 12, 2024)
    fixed_now = datetime(2024, 12, 12, 12, 0, 0, tzinfo=dt_util.UTC)
    
    # Events on Fri(4), Sat(5), Sun(6), Mon(0)
    planner.history[4].append(8*60)
    planner.history[5].append(8*60)
    planner.history[6].append(8*60)
    
    # Allowed: Fri(4), Sat(5). Sun(6) excluded.
    allowed = [4, 5]
    
    # Ask -> Expect Fri
    res = planner.get_next_scheduled_event(fixed_now, allowed_weekdays=allowed)
    assert res.weekday() == 4
    
    # Ask from Fri Evening (20:00) -> Expect Sat
    friday_night = datetime(2024, 12, 13, 20, 0, 0, tzinfo=dt_util.UTC)
    res = planner.get_next_scheduled_event(friday_night, allowed_weekdays=allowed)
    assert res.weekday() == 5 # Sat
    
    # Ask from Sat Evening (20:00) -> Expect Fri (Next week)?
    # Or None if we didn't populate Mon-Thu?
    # Our loop goes 7 days.
    # Next allowed day is Fri. (Sun, Mon, Tue, Wed, Thu skipped).
    # 6 days later.
    sat_night = datetime(2024, 12, 14, 20, 0, 0, tzinfo=dt_util.UTC)
    res = planner.get_next_scheduled_event(sat_night, allowed_weekdays=allowed)
    assert res is not None
    assert res.weekday() == 4
    
def test_no_events_found(planner):
    """Test returns None if restricted and no events fit."""
    fixed_now = datetime(2024, 12, 13, 12, 0, 0, tzinfo=dt_util.UTC) # Fri
    
    # Event on Sat only
    planner.history[5].append(8*60)
    
    # Restrict to Mon-Fri
    allowed = [0,1,2,3,4]
    
    res = planner.get_next_scheduled_event(fixed_now, allowed_weekdays=allowed)
    assert res is None
