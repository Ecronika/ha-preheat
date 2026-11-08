"""Regression tests: runs that miss the target must teach the model a longer heat-up,
deadtime falls back to the profile, and a stuck mass factor raises a repair issue."""
import sys
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import types
if "homeassistant" not in sys.modules:
    ha = types.ModuleType("homeassistant")
    ha.__path__ = []
    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = MagicMock()
    sys.modules["homeassistant.config_entries"] = MagicMock()
    sys.modules["homeassistant.const"] = MagicMock()
    sys.modules["homeassistant.util"] = MagicMock()
    mock_dt = MagicMock()
    mock_dt.utcnow.side_effect = lambda: datetime.now(timezone.utc)
    sys.modules["homeassistant.util.dt"] = mock_dt
    sys.modules["homeassistant.helpers"] = MagicMock()
    sys.modules["homeassistant.helpers.event"] = MagicMock()
    sys.modules["homeassistant.helpers.storage"] = MagicMock()
    sys.modules["homeassistant.helpers.issue_registry"] = MagicMock()
    sys.modules["homeassistant.exceptions"] = MagicMock()

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

from custom_components.preheat.coordinator import PreheatingCoordinator
from custom_components.preheat.diagnostics import DiagnosticsManager
from custom_components.preheat.physics import ThermalPhysics, ThermalModelData
from custom_components.preheat.const import (
    CONF_HEATING_PROFILE,
    HEATING_PROFILES,
    MASS_BOUND_STREAK_LIMIT,
    PROFILE_RADIATOR_NEW,
)

RADIATOR = HEATING_PROFILES[PROFILE_RADIATOR_NEW]


def make_coordinator():
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "zone"
    entry.title = "Office"
    entry.options = {CONF_HEATING_PROFILE: PROFILE_RADIATOR_NEW}
    entry.data = {}
    with patch.object(PreheatingCoordinator, "_setup_listeners"):
        coord = PreheatingCoordinator(hass, entry)
    coord._store = MagicMock()
    coord._store.async_save = AsyncMock()
    return coord


def issue_state_physics():
    """Model state as reported in the issue (mass at profile min, deadtime 0, many samples)."""
    return ThermalPhysics(
        data=ThermalModelData(mass_factor=10.0, loss_factor=2.75, sample_count=50, deadtime=0.0),
        profile_data=RADIATOR, learning_rate=0.3,
    )


class TestExtrapolation(unittest.TestCase):

    def setUp(self):
        self.coord = make_coordinator()
        self.coord.physics = MagicMock(deadtime=15.0)

    def test_linear_after_deadtime(self):
        dur, rise = self.coord._extrapolate_missed_run(90.0, 2.0, 3.0)
        self.assertAlmostEqual(rise, 3.0)
        self.assertAlmostEqual(dur, 15 + 75 * 1.5)

    def test_factor_is_capped(self):
        dur, rise = self.coord._extrapolate_missed_run(60.0, 0.4, 3.0)
        self.assertAlmostEqual(rise, 1.6)
        self.assertAlmostEqual(dur, 15 + 45 * 4)

    def test_too_small_rise_is_not_extrapolated(self):
        self.assertEqual(self.coord._extrapolate_missed_run(60.0, 0.2, 3.0), (60.0, 0.2))

    def test_overshoot_is_not_extrapolated(self):
        self.assertEqual(self.coord._extrapolate_missed_run(60.0, 2.0, 1.5), (60.0, 2.0))

    def test_run_shorter_than_deadtime(self):
        dur, rise = self.coord._extrapolate_missed_run(10.0, 0.5, 1.0)
        self.assertAlmostEqual(dur, 10.0)  # all of it treated as deadtime, nothing to scale
        self.assertAlmostEqual(rise, 1.0)


class TestIssueScenarioConverges(unittest.TestCase):
    """Room needs 15 min deadtime + 62 min/K, 2 K rise at 16 K outdoor delta.

    The issue's model predicts ~59 min and misses the target every day. Learning from the
    achieved rise kept the error ~0; with extrapolation the prediction must converge."""

    TRUE_DEAD, TRUE_RATE, RISE, DOUT = 15.0, 62.0, 2.0, 16.0

    def _simulate(self, days):
        coord = make_coordinator()
        physics = issue_state_physics()
        coord.physics = physics
        true_time = self.TRUE_DEAD + self.TRUE_RATE * self.RISE
        for _ in range(days):
            run = physics.calculate_duration(self.RISE, self.DOUT)
            if run >= true_time:
                dur, rise = true_time, self.RISE
            else:
                achieved = (run - self.TRUE_DEAD) / self.TRUE_RATE
                dur, rise = coord._extrapolate_missed_run(run, achieved, self.RISE)
            physics.update_model(dur, rise, self.DOUT, 80.0)
        return physics.calculate_duration(self.RISE, self.DOUT), true_time

    def test_deadtime_restored_from_profile(self):
        self.assertEqual(issue_state_physics().deadtime, RADIATOR["deadtime"])

    def test_prediction_converges_to_real_heat_up_time(self):
        predicted, true_time = self._simulate(10)
        self.assertGreater(predicted, 0.95 * true_time)
        self.assertLess(predicted, 1.05 * true_time)


class TestDeadtimeFallback(unittest.TestCase):

    def test_learned_deadtime_is_kept(self):
        p = ThermalPhysics(ThermalModelData(20.0, 3.0, 50, 0.0, 22.5), RADIATOR)
        self.assertEqual(p.deadtime, 22.5)

    def test_without_profile_zero_stays(self):
        p = ThermalPhysics(ThermalModelData(20.0, 3.0, 50, 0.0, 0.0))
        self.assertEqual(p.deadtime, 0.0)


class TestMassBoundWarning(unittest.TestCase):

    def setUp(self):
        self.manager = DiagnosticsManager(MagicMock(), MagicMock(entry_id="zone", title="Office"), MagicMock())
        self.manager._create_issue = MagicMock()
        self.manager._delete_issue = MagicMock()

    def _physics_pushed(self, side):
        p = ThermalPhysics(profile_data=RADIATOR)
        p.mass_factor = RADIATOR["mass_factor_max"] if side == "upper" else RADIATOR["mass_factor_min"]
        p.last_mass_clamped = side
        return p

    def _run_diag(self, physics):
        import asyncio
        pred = {"limit_exceeded": False, "uncapped_duration": 60.0}
        asyncio.run(self.manager._diag_physics({}, physics, None, pred))

    def _created(self):
        return [c for c in self.manager._create_issue.call_args_list if c.args[0] == "mass_at_bound"]

    def test_update_clamped_at_bound_is_tracked(self):
        physics = ThermalPhysics(ThermalModelData(10.5, 2.0, 30, 0.0, 15.0), RADIATOR, learning_rate=0.3)
        physics.update_model(10.0, 2.0, 16.0, 80.0)   # far shorter than predicted -> pushes below 10
        self.assertEqual(physics.last_mass_clamped, "lower")
        self.assertEqual(physics.mass_factor, RADIATOR["mass_factor_min"])
        physics.update_model(physics.calculate_duration(2.0, 16.0), 2.0, 16.0, 80.0)  # no error
        self.assertIsNone(physics.last_mass_clamped)

    def test_warning_after_streak_upper(self):
        physics = self._physics_pushed("upper")
        for _ in range(MASS_BOUND_STREAK_LIMIT - 1):
            self.manager.note_model_update(physics)
        self._run_diag(physics)
        self.assertEqual(self._created(), [])

        self.manager.note_model_update(physics)
        self._run_diag(physics)
        call = self._created()[-1]
        self.assertEqual(call.kwargs["translation_key"], "mass_at_upper_bound")
        self.assertEqual(call.kwargs["translation_placeholders"]["count"], str(MASS_BOUND_STREAK_LIMIT))

    def test_warning_lower_and_reset_by_normal_update(self):
        pushed = self._physics_pushed("lower")
        for _ in range(MASS_BOUND_STREAK_LIMIT):
            self.manager.note_model_update(pushed)
        self._run_diag(pushed)
        self.assertEqual(self._created()[-1].kwargs["translation_key"], "mass_at_lower_bound")

        normal = self._physics_pushed("lower")
        normal.last_mass_clamped = None   # at the bound, but the fit no longer pushes past it
        self.manager.note_model_update(normal)
        self._run_diag(normal)
        self.manager._delete_issue.assert_any_call("mass_at_bound")
        self.assertEqual(self.manager.data["mass_bound_streak"], 0)

    def test_side_change_restarts_streak(self):
        for _ in range(MASS_BOUND_STREAK_LIMIT - 1):
            self.manager.note_model_update(self._physics_pushed("lower"))
        self.manager.note_model_update(self._physics_pushed("upper"))
        self.assertEqual(self.manager.data["mass_bound_streak"], 1)
        self.assertEqual(self.manager.data["mass_bound_side"], "upper")
