"""Regression tests: comfort buffer (buffer_minutes) must shift the preheat start earlier."""
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
    mock_dt = MagicMock()
    mock_dt.UTC = timezone.utc
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

from custom_components.preheat.coordinator import PreheatingCoordinator, PreheatData
from custom_components.preheat.house_collector import HouseArrivalCollector
from custom_components.preheat.providers import ProviderDecision
from custom_components.preheat.const import (
    CONF_BUFFER_MIN,
    CONF_HEATING_PROFILE,
    CONF_MAX_PREHEAT_HOURS,
    HEATING_PROFILES,
    PROFILE_RADIATOR_NEW,
)

ARRIVAL = datetime(2026, 11, 9, 4, 57, tzinfo=timezone.utc)


def make_coordinator(options):
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "zone"
    entry.title = "Office"
    entry.options = dict(options)
    entry.data = {}
    with patch.object(PreheatingCoordinator, "_setup_listeners"):
        coord = PreheatingCoordinator(hass, entry)
    coord._store = MagicMock()
    coord._store.async_save = AsyncMock()
    coord._store.async_load = AsyncMock(return_value={})

    # Mature learned pattern, no schedule helper, no house hub
    coord.planner = MagicMock()
    coord.planner.last_pattern_result = MagicMock(confidence=0.9)
    coord.planner.get_next_predicted_departure.return_value = None
    coord.schedule_provider.get_decision = MagicMock(
        return_value=ProviderDecision(False, None, False, False, invalid_reason="unavailable"))
    coord.learned_provider.get_decision = MagicMock(
        return_value=ProviderDecision(False, None, False, True))

    coord.physics = MagicMock()
    coord.physics.calculate_duration.return_value = 56.0
    coord.physics.deadtime = 15.0
    return coord


def make_ctx(now, operative=19.0):
    return {
        "now": now, "operative_temp": operative, "outdoor_temp": 5.0, "valve_position": 0.0,
        "is_occupied": False, "is_window_open": False, "target_setpoint": 21.0,
        "next_event": ARRIVAL, "blocked_dates": set(), "is_sensor_ready": True,
        "forecasts": None, "preheat_active": False, "has_confident_house": False,
        "house_confidence": 0.0, "house_next_event": None, "zone_next_event": ARRIVAL,
        "has_house_fallback": False, "house_source": "none",
        "hvac_action": None, "hvac_mode": None,
    }


class TestComfortBuffer(unittest.IsolatedAsyncioTestCase):

    async def _decide(self, coord, now, operative=19.0):
        ctx = make_ctx(now, operative)
        pred = await coord._run_physics_simulation(ctx)
        return pred, coord._evaluate_start_decision(ctx, pred)

    async def test_issue_repro_buffer_shifts_planned_start(self):
        """Duration 56 min, arrival 04:57, buffer 60 -> start 03:01 (was 04:01)."""
        coord = make_coordinator({CONF_BUFFER_MIN: 60})
        now = ARRIVAL - timedelta(hours=3)

        pred, dec = await self._decide(coord, now)

        self.assertEqual(pred["predicted_duration"], 56.0)
        self.assertEqual(pred["lead_time"], 116.0)
        self.assertEqual(dec["planned_start"], ARRIVAL - timedelta(minutes=116))
        self.assertFalse(dec["should_start"])
        data = coord._build_preheat_data(make_ctx(now), pred, dec)
        self.assertEqual(data.next_start_time, ARRIVAL - timedelta(minutes=116))
        self.assertEqual(data.predicted_duration, 56.0)  # duration itself stays pure

    async def test_start_triggers_within_buffer(self):
        now = ARRIVAL - timedelta(minutes=90)  # inside 56+60, outside 56

        _, dec = await self._decide(make_coordinator({CONF_BUFFER_MIN: 60}), now)
        self.assertTrue(dec["should_start"])
        self.assertEqual(dec["applied_buffer"], 60.0)

        _, dec = await self._decide(make_coordinator({CONF_BUFFER_MIN: 0}), now)
        self.assertFalse(dec["should_start"])
        self.assertEqual(dec["planned_start"], ARRIVAL - timedelta(minutes=56))

    async def test_profile_buffer_is_default(self):
        coord = make_coordinator({CONF_HEATING_PROFILE: PROFILE_RADIATOR_NEW})
        pred, _ = await self._decide(coord, ARRIVAL - timedelta(hours=3))
        self.assertEqual(pred["buffer_min"], HEATING_PROFILES[PROFILE_RADIATOR_NEW]["buffer"])
        self.assertEqual(pred["lead_time"], 56.0 + HEATING_PROFILES[PROFILE_RADIATOR_NEW]["buffer"])

    async def test_lead_time_capped_by_max_preheat(self):
        coord = make_coordinator({CONF_BUFFER_MIN: 60, CONF_MAX_PREHEAT_HOURS: 1.5})
        pred, dec = await self._decide(coord, ARRIVAL - timedelta(hours=3))
        self.assertEqual(pred["lead_time"], 90.0)
        self.assertEqual(dec["planned_start"], ARRIVAL - timedelta(minutes=90))

    async def test_no_buffer_when_already_warm(self):
        coord = make_coordinator({CONF_BUFFER_MIN: 60})
        coord.physics.calculate_duration.return_value = 0.0
        pred, dec = await self._decide(coord, ARRIVAL - timedelta(minutes=30), operative=21.5)
        self.assertEqual(pred["lead_time"], 0.0)
        self.assertFalse(dec["should_start"])
        self.assertIsNone(dec["planned_start"])

    async def test_disabled_has_no_planned_start(self):
        coord = make_coordinator({CONF_BUFFER_MIN: 60})
        coord.enable_active = False
        _, dec = await self._decide(coord, ARRIVAL - timedelta(hours=3))
        self.assertIsNone(dec["planned_start"])

    async def test_learning_excludes_buffer(self):
        coord = make_coordinator({CONF_BUFFER_MIN: 60})
        coord.physics.update_model.return_value = False
        coord.deadtime_analyzer.analyze = MagicMock(return_value=None)
        coord.history_buffer.get_average_valve = MagicMock(return_value=80.0)
        coord._outdoor_is_real = True

        clock = MagicMock()
        clock.utcnow.side_effect = lambda: datetime.now(timezone.utc)
        with patch("custom_components.preheat.coordinator.dt_util", clock):
            await coord._start_preheat(19.0, buffer_min=60.0)
            coord._preheat_started_at -= timedelta(minutes=116)
            await coord._stop_preheat(21.0, 21.0, 5.0)

        learned_duration = coord.physics.update_model.call_args.args[0]
        self.assertAlmostEqual(learned_duration, 56.0, delta=0.5)
        self.assertEqual(coord._start_buffer, 0.0)

    async def test_house_incoming_uses_lead_time(self):
        hass = MagicMock()
        with patch("custom_components.preheat.house_collector.Store"):
            collector = HouseArrivalCollector(hass)
        coord = MagicMock(_consecutive_readiness_errors=0)
        coord.data = PreheatData(False, None, 19.0, 21.0, ARRIVAL, 56.0, 0, 0, False, lead_time=116.0)
        hass.config_entries.async_entries.return_value = [MagicMock(runtime_data=coord)]
        self.assertEqual(collector.get_max_predicted_duration(), 116.0)
