"""Regression tests: a preheat run is opened once and learned from its heat-up time."""
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
    sys.modules["homeassistant.core"] = MagicMock()
    sys.modules["homeassistant.config_entries"] = MagicMock()
    sys.modules["homeassistant.const"] = MagicMock()
    sys.modules["homeassistant.util"] = MagicMock()
    sys.modules["homeassistant.util.dt"] = MagicMock()
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
from custom_components.preheat.physics import ThermalPhysics, ThermalModelData
from custom_components.preheat.const import CONF_HEATING_PROFILE, PROFILE_RADIATOR_NEW

T0 = datetime(2026, 11, 9, 4, 0, tzinfo=timezone.utc)


class FakeClock:
    """Controllable replacement for homeassistant.util.dt inside the coordinator."""
    def __init__(self, start):
        self.t = start
    def utcnow(self):
        return self.t
    def now(self):
        return self.t
    def advance(self, minutes):
        self.t += timedelta(minutes=minutes)


class TestPreheatRun(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.clock = FakeClock(T0)
        patcher = patch("custom_components.preheat.coordinator.dt_util", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "zone"
        entry.title = "Office"
        entry.options = {CONF_HEATING_PROFILE: PROFILE_RADIATOR_NEW}
        entry.data = {}
        with patch.object(PreheatingCoordinator, "_setup_listeners"):
            self.coord = PreheatingCoordinator(hass, entry)
        self.coord._store = MagicMock()
        self.coord._store.async_save = AsyncMock()
        self.coord._store.async_load = AsyncMock(return_value={})
        self.coord._outdoor_is_real = True
        self.coord.deadtime_analyzer.analyze = MagicMock(return_value=None)
        self.coord.history_buffer.get_average_valve = MagicMock(return_value=80.0)
        self.hass = hass

    def _ctx(self, temp, target=21.0, outdoor=5.0):
        return {"operative_temp": temp, "target_setpoint": target, "outdoor_temp": outdoor}

    async def _cycle(self, temp, should_start, outdoor=5.0):
        dec = {"should_start": should_start, "frost_override": False}
        await self.coord._execute_control_actions(self._ctx(temp, outdoor=outdoor), dec)

    def _started_events(self):
        return [c for c in self.hass.bus.async_fire.call_args_list if c.args[0] == "preheat_started"]

    async def test_run_is_opened_only_once(self):
        await self._cycle(19.0, True)
        for _ in range(10):
            self.clock.advance(1)
            await self._cycle(19.3, True)

        self.assertEqual(self.coord._preheat_started_at, T0)
        self.assertEqual(self.coord._start_temp, 19.0)
        self.assertEqual(len(self._started_events()), 1)

    async def test_learns_time_to_target_not_time_to_arrival(self):
        self.coord.physics = MagicMock()
        self.coord.physics.update_model.return_value = False

        await self._cycle(19.0, True)
        self.clock.advance(20)
        await self._cycle(20.0, True)
        self.clock.advance(20)
        await self._cycle(20.9, True)   # within tolerance -> target reached at +40 min
        self.clock.advance(76)
        await self._cycle(21.0, True)   # holding until arrival (incl. buffer)
        await self._cycle(21.0, False)  # arrival -> stop at +116 min

        args = self.coord.physics.update_model.call_args.args
        self.assertAlmostEqual(args[0], 40.0)          # heat-up time
        self.assertAlmostEqual(args[1], 1.9)           # 19.0 -> 20.9
        self.assertAlmostEqual(args[2], 16.0)          # 21 - 5
        self.coord.history_buffer.get_average_valve.assert_called_with(
            T0.timestamp(), (T0 + timedelta(minutes=40)).timestamp())
        self.assertFalse(self.coord._preheat_active)
        self.assertIsNone(self.coord._target_reached_at)

    async def test_target_not_reached_learns_extrapolated_full_rise(self):
        self.coord.physics = MagicMock()
        self.coord.physics.deadtime = 15.0
        self.coord.physics.update_model.return_value = False

        await self._cycle(18.0, True)
        self.clock.advance(90)
        await self._cycle(20.0, True)
        await self._cycle(20.0, False)   # arrival 1 K below target

        args = self.coord.physics.update_model.call_args.args
        # 15 min deadtime + 75 min for 2 K -> 15 + 75 * 3/2 for the full 3 K
        self.assertAlmostEqual(args[0], 127.5)
        self.assertAlmostEqual(args[1], 3.0)

    async def test_zero_degrees_outdoor_is_not_replaced_by_fallback(self):
        self.coord.physics = MagicMock()
        self.coord.physics.update_model.return_value = False

        await self._cycle(19.0, True, outdoor=0.0)
        self.clock.advance(60)
        await self._cycle(21.0, True, outdoor=0.0)
        await self._cycle(21.0, False, outdoor=0.0)

        self.assertAlmostEqual(self.coord.physics.update_model.call_args.args[2], 21.0)

    async def test_force_preheat_on_does_not_restart_running_run(self):
        self.coord._get_operative_temperature = AsyncMock(return_value=20.5)
        self.coord.async_update_listeners = MagicMock()
        await self._cycle(19.0, True)
        self.clock.advance(30)
        await self.coord.force_preheat_on()
        self.assertEqual(self.coord._preheat_started_at, T0)
        self.assertEqual(self.coord._start_temp, 19.0)

    async def test_model_learns_downward_when_room_heats_faster(self):
        """Overestimated duration must shrink the mass factor (was impossible before)."""
        physics = ThermalPhysics(
            data=ThermalModelData(mass_factor=40.0, loss_factor=2.0, sample_count=5, deadtime=10.0),
            profile_data={"mass_factor_min": 10, "mass_factor_max": 60, "default_mass": 20},
        )
        self.coord.physics = physics
        predicted = physics.calculate_duration(2.0, 16.0)  # 10 + 80 + 32 = 122 min

        await self._cycle(19.0, True)
        self.clock.advance(50)
        await self._cycle(21.0, True)        # reached after 50 min
        self.clock.advance(predicted - 50)
        await self._cycle(21.0, False)       # arrival

        self.assertLess(physics.mass_factor, 40.0)
        self.assertEqual(physics.sample_count, 6)
