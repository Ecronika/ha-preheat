"""Regression tests for #9 (session not restored after restart) and #10 (learned comfort
setpoint: never saved, 15-min guard bypassed, not clamped)."""
import sys
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, AsyncMock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import types
if "homeassistant" not in sys.modules:
    ha = types.ModuleType("homeassistant")
    ha.__path__ = []
    sys.modules["homeassistant"] = ha
    for name in ("core", "config_entries", "const", "util", "util.dt", "helpers",
                 "helpers.event", "helpers.storage", "helpers.issue_registry", "exceptions"):
        sys.modules[f"homeassistant.{name}"] = MagicMock()

if "homeassistant.helpers.update_coordinator" not in sys.modules:
    class MockDataUpdateCoordinator:
        def __init__(self, hass, logger, name, update_interval, **kwargs):
            self.hass = hass
            self.data = None
        async def async_refresh(self): pass
        def __class_getitem__(cls, item): return cls

    mock_duc_mod = MagicMock()
    mock_duc_mod.DataUpdateCoordinator = MockDataUpdateCoordinator
    sys.modules["homeassistant.helpers.update_coordinator"] = mock_duc_mod

import custom_components.preheat.coordinator as coordinator_mod
from custom_components.preheat.coordinator import PreheatingCoordinator
from custom_components.preheat.session_manager import SessionManager
from custom_components.preheat.const import (
    CONF_CLIMATE, CONF_OCCUPANCY, DEFAULT_COMFORT_MAX,
)

ON = coordinator_mod.STATE_ON  # whatever the (mocked) HA constant is
T0 = datetime(2026, 11, 10, 7, 17, tzinfo=timezone.utc)
OCC = "binary_sensor.occupied"
CLIMATE = "climate.office"


class Clock:
    def __init__(self, t):
        self.t = t
    def utcnow(self):
        return self.t
    def now(self):
        return self.t
    def advance(self, minutes):
        self.t += timedelta(minutes=minutes)


def st(value, **attrs):
    return MagicMock(state=value, attributes=attrs)


class Base(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.clock = Clock(T0)
        p = patch.object(coordinator_mod, "dt_util", self.clock)
        p.start()
        self.addCleanup(p.stop)
        self.states = {OCC: st(ON), CLIMATE: st("heat", temperature=22.1)}
        hass = MagicMock()
        hass.states.get.side_effect = self.states.get
        hass.states.is_state.side_effect = lambda e, v: e in self.states and self.states[e].state == v
        entry = MagicMock(entry_id="zone", title="Office", data={},
                          options={CONF_OCCUPANCY: OCC, CONF_CLIMATE: CLIMATE})
        with patch.object(PreheatingCoordinator, "_setup_listeners"):
            self.coord = PreheatingCoordinator(hass, entry)
        self.coord._store = MagicMock()
        self.coord._store.async_save = AsyncMock()
        self.coord.planner = MagicMock()
        self.hass = hass

    def transition(self, old, new):
        # The @callback listener only extracts the states and delegates to this method
        self.coord._on_occupancy_state(old, new)


class TestSessionRestore(Base):
    """#9"""

    def test_resume_session_has_no_arrival_side_effects(self):
        sm = SessionManager(15, self.coord)
        self.assertTrue(sm.resume_session(T0))
        self.assertTrue(sm.is_occupied)
        self.assertFalse(sm.resume_session(T0))  # already running
        self.coord.planner.record_arrival.assert_not_called()

    def test_startup_with_sensor_on_resumes_session(self):
        self.assertFalse(self.coord.session_manager.is_occupied)
        self.coord._restore_session_if_occupied()
        self.assertTrue(self.coord.session_manager.is_occupied)
        self.coord.planner.record_arrival.assert_not_called()
        self.hass.async_create_task.assert_not_called()  # no _learn_arrival_event

    def test_startup_waits_for_unavailable_sensor(self):
        self.states[OCC] = st("unavailable")
        self.coord._restore_session_if_occupied()
        self.assertFalse(self.coord.session_manager.is_occupied)
        self.states[OCC] = st(ON)
        self.coord._restore_session_if_occupied()
        self.assertTrue(self.coord.session_manager.is_occupied)

    def test_startup_with_sensor_off(self):
        self.states[OCC] = st("off")
        self.coord._restore_session_if_occupied()
        self.assertFalse(self.coord.session_manager.is_occupied)
        self.states[OCC] = st(ON)       # later on without event: no second restore
        self.coord._restore_session_if_occupied()
        self.assertFalse(self.coord.session_manager.is_occupied)

    def test_unavailable_or_initial_to_on_is_resume_not_arrival(self):
        for old in (None, "unavailable", "unknown"):
            self.coord.session_manager = SessionManager(15, self.coord)
            self.hass.async_create_task.reset_mock()
            self.transition(old, ON)
            self.assertTrue(self.coord.session_manager.is_occupied, old)
            self.hass.async_create_task.assert_not_called()

    def test_real_arrival_still_learned(self):
        self.transition("off", ON)
        self.assertTrue(self.coord.session_manager.is_occupied)
        self.hass.async_create_task.assert_called_once()

    def test_unavailable_does_not_start_departure(self):
        self.transition("off", ON)
        self.transition(ON, "unavailable")
        self.assertFalse(self.coord.session_manager._is_debouncing)
        self.transition("unavailable", ON)
        self.assertTrue(self.coord.session_manager.is_occupied)

    async def test_issue_scenario_departure_recorded_after_restart(self):
        """Restart while on -> evening off -> departure committed to the planner."""
        self.coord._restore_session_if_occupied()
        self.clock.advance(12 * 60)
        self.transition(ON, "off")
        self.clock.advance(30)
        await self.coord.session_manager.check_debounce(self.clock.utcnow())
        self.coord.planner.record_departure.assert_called_once()


class TestComfortLearning(Base):
    """#10"""

    def setUp(self):
        super().setUp()
        self.coord.session_manager.resume_session(T0)

    async def run_minutes(self, minutes, setpoint, step=1):
        for _ in range(0, minutes, step):
            self.states[CLIMATE] = st("heat", temperature=setpoint)
            await self.coord._update_comfort_learning(True)
            self.clock.advance(step)

    async def test_target_setpoint_is_side_effect_free(self):
        self.coord._last_comfort_setpoint = 21.0
        self.states[CLIMATE] = st("heat", temperature=22.4)
        self.assertEqual(await self.coord._get_target_setpoint(), 22.4)
        self.assertEqual(self.coord._last_comfort_setpoint, 21.0)

    async def test_guard_15_min_then_learned_and_saved(self):
        self.coord._last_comfort_setpoint = 21.0
        await self.run_minutes(14, 22.4)
        self.assertEqual(self.coord._last_comfort_setpoint, 21.0)
        self.coord._store.async_delay_save.assert_not_called()
        await self.run_minutes(3, 22.4)
        self.assertEqual(self.coord._last_comfort_setpoint, 22.4)
        self.coord._store.async_delay_save.assert_called()

    async def test_issue_scenario_boost_does_not_stick(self):
        """Boost to 23.6 for 20 min, then 22.6 for 100 min -> learns 22.6."""
        await self.run_minutes(20, 23.6)
        self.assertEqual(self.coord._last_comfort_setpoint, DEFAULT_COMFORT_MAX)  # clamped
        await self.run_minutes(100, 22.6)
        self.assertEqual(self.coord._last_comfort_setpoint, 22.6)
        saved = self.coord._get_data_for_storage()
        self.assertEqual(saved["last_comfort_setpoint"], 22.6)

    async def test_setback_values_are_not_learned(self):
        await self.run_minutes(30, 17.0)   # eco setpoint <= comfort_min
        self.assertIsNone(self.coord._last_comfort_setpoint)

    async def test_unoccupied_resets_window(self):
        await self.run_minutes(10, 22.4)
        await self.coord._update_comfort_learning(False)
        self.assertEqual(self.coord.comfort_learning_info["comfort_tracked_min"], 0)
        await self.run_minutes(10, 22.4)
        self.assertIsNone(self.coord._last_comfort_setpoint)  # needs 15 min in one session

    async def test_downtime_gap_not_counted(self):
        await self.run_minutes(10, 22.4)
        self.clock.advance(120)            # HA down for 2 h
        await self.run_minutes(2, 22.4)
        self.assertLess(self.coord.comfort_learning_info["comfort_tracked_min"], 15)
        self.assertIsNone(self.coord._last_comfort_setpoint)

    def test_loaded_value_is_clamped(self):
        self.assertEqual(self.coord._clamp_comfort(23.6), DEFAULT_COMFORT_MAX)
        self.assertEqual(self.coord._clamp_comfort(22.0), 22.0)
        self.assertIsNone(self.coord._clamp_comfort(None))

    async def test_physics_simulation_does_not_seed_learned_value(self):
        ctx = {"target_setpoint": 21.0, "operative_temp": 19.0, "outdoor_temp": 5.0, "forecasts": None}
        self.coord.physics = MagicMock()
        self.coord.physics.calculate_duration.return_value = 60.0
        await self.coord._run_physics_simulation(ctx)
        self.assertIsNone(self.coord._last_comfort_setpoint)

    async def test_reset_comfort_setpoint(self):
        await self.run_minutes(20, 22.4)
        self.coord.async_refresh = AsyncMock()
        await self.coord.reset_comfort_setpoint()
        self.assertIsNone(self.coord._last_comfort_setpoint)
        self.assertEqual(self.coord.comfort_learning_info["comfort_tracked_min"], 0)
        self.coord._store.async_save.assert_awaited()
