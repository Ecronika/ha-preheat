"""Regression tests for issue #5: a schedule helper that is OFF must provide the next
comfort start (its next_event) and take priority over House/learned predictions."""
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
from custom_components.preheat.providers import ScheduleProvider
from custom_components.preheat.const import (
    CONF_BUFFER_MIN,
    CONF_CALENDAR_ENTITY,
    CONF_CLIMATE,
    CONF_SCHEDULE_ENTITY,
    REASON_OFF,
)

TZ = timezone(timedelta(hours=2))
NOW = datetime(2026, 10, 7, 20, 30, tzinfo=TZ)          # schedule switched off at 20:00
NEXT_ON = datetime(2026, 10, 8, 6, 0, tzinfo=TZ)        # next comfort start
SCHED = "schedule.benji_heizung_comfort"


def state(value, **attrs):
    return MagicMock(state=value, attributes=attrs)


def make_hass(states):
    hass = MagicMock()
    hass.states.get.side_effect = lambda eid: states.get(eid)
    return hass


def make_provider(states):
    entry = MagicMock(options={CONF_SCHEDULE_ENTITY: SCHED}, data={})
    return ScheduleProvider(make_hass(states), entry, MagicMock())


class TestScheduleProviderNextStart(unittest.TestCase):

    def test_off_with_future_next_event(self):
        p = make_provider({SCHED: state("off", next_event=NEXT_ON)})
        self.assertEqual(p.get_next_start(NOW), NEXT_ON)

    def test_off_with_iso_string(self):
        p = make_provider({SCHED: state("off", next_event=NEXT_ON.isoformat())})
        self.assertEqual(p.get_next_start(NOW), NEXT_ON)

    def test_on_is_session_end_not_start(self):
        p = make_provider({SCHED: state("on", next_event=NEXT_ON)})
        self.assertIsNone(p.get_next_start(NOW))

    def test_off_invalid_missing_or_past(self):
        for attrs in ({}, {"next_event": None}, {"next_event": "garbage"},
                      {"next_event": NOW - timedelta(minutes=1)},
                      {"next_event": NEXT_ON.replace(tzinfo=None)}):
            p = make_provider({SCHED: state("off", **attrs)})
            self.assertIsNone(p.get_next_start(NOW), attrs)

    def test_unavailable_or_unconfigured(self):
        self.assertIsNone(make_provider({SCHED: state("unavailable", next_event=NEXT_ON)}).get_next_start(NOW))
        self.assertIsNone(make_provider({}).get_next_start(NOW))

    def test_decision_off_is_valid_start_source_only_when_used(self):
        p = make_provider({SCHED: state("off", next_event=NEXT_ON)})
        used = p.get_decision({"now": NOW, "schedule_next_start": NEXT_ON})
        self.assertTrue(used.is_valid)
        self.assertIsNone(used.session_end)
        unused = p.get_decision({"now": NOW, "schedule_next_start": None})
        self.assertFalse(unused.is_valid)
        self.assertEqual(unused.invalid_reason, REASON_OFF)

    def test_decision_on_unchanged_session_end(self):
        end = datetime(2026, 10, 8, 8, 0, tzinfo=TZ)
        p = make_provider({SCHED: state("on", next_event=end.isoformat())})
        with patch("custom_components.preheat.optimal_stop.dt_util.parse_datetime",
                   side_effect=lambda s: datetime.fromisoformat(s)):
            d = p.get_decision({"now": NOW})
        self.assertTrue(d.is_valid)
        self.assertEqual(d.session_end, end)


class TestCoordinatorUsesScheduleStart(unittest.IsolatedAsyncioTestCase):

    def _make(self, sched_state, options=None, house=(None, 0.0, "none"), zone_event=None, blocked=None):
        states = {SCHED: sched_state, "climate.benjis_heizung": state("heat", temperature=17.0)}
        hass = make_hass(states)
        entry = MagicMock()
        entry.entry_id = "zone"
        entry.title = "Benji"
        entry.options = {CONF_SCHEDULE_ENTITY: SCHED, CONF_CLIMATE: "climate.benjis_heizung",
                         CONF_BUFFER_MIN: 0, **(options or {})}
        entry.data = {}
        with patch.object(PreheatingCoordinator, "_setup_listeners"):
            coord = PreheatingCoordinator(hass, entry)
        coord._get_operative_temperature = AsyncMock(return_value=18.0)
        coord._get_outdoor_temp_current = AsyncMock(return_value=8.0)
        coord._get_blocked_dates_from_calendar = AsyncMock(return_value=blocked or set())
        coord.session_manager.check_debounce = AsyncMock()
        coord.planner = MagicMock()
        coord.planner.get_next_scheduled_event.return_value = zone_event
        coord.planner.get_next_predicted_departure.return_value = None
        coord.planner.last_pattern_result = None
        coord.house_collector = MagicMock()
        coord.house_collector.get_next_arrival.return_value = house
        coord.physics = MagicMock(deadtime=15.0)
        coord.physics.calculate_duration.return_value = 75.0
        return coord

    async def _ctx(self, coord):
        clock = MagicMock()
        clock.now.return_value = NOW
        clock.utcnow.return_value = NOW.astimezone(timezone.utc)
        with patch("custom_components.preheat.coordinator.dt_util", clock):
            return await coord._collect_context()

    async def test_issue_repro_next_event_and_planned_start(self):
        """Schedule OFF since 20:00, next ON 06:00, no learned data -> preheat planned at 04:45."""
        coord = self._make(state("off", next_event=NEXT_ON))
        ctx = await self._ctx(coord)
        self.assertEqual(ctx["next_event"], NEXT_ON)
        self.assertEqual(ctx["next_event_source"], "schedule")

        pred = await coord._run_physics_simulation(ctx)
        dec = coord._evaluate_start_decision(ctx, pred)
        self.assertEqual(dec["start_source"], "schedule")
        self.assertEqual(dec["planned_start"], NEXT_ON - timedelta(minutes=75))
        self.assertFalse(dec["should_start"])
        self.assertEqual(coord.decision_trace["next_event_source"], "schedule")

        # 70 min before 06:00 the preheat starts
        ctx["now"] = NEXT_ON - timedelta(minutes=70)
        dec = coord._evaluate_start_decision(ctx, pred)
        self.assertTrue(dec["should_start"])

    async def test_schedule_beats_confident_house(self):
        house_evt = datetime(2026, 10, 8, 5, 0, tzinfo=TZ)
        coord = self._make(state("off", next_event=NEXT_ON), house=(house_evt, 0.95, "confident"))
        ctx = await self._ctx(coord)
        self.assertEqual(ctx["next_event"], NEXT_ON)

    async def test_schedule_on_keeps_previous_selection(self):
        house_evt = datetime(2026, 10, 8, 17, 30, tzinfo=TZ)
        coord = self._make(state("on", next_event=NEXT_ON), house=(house_evt, 0.95, "confident"))
        ctx = await self._ctx(coord)
        self.assertEqual(ctx["next_event"], house_evt)
        self.assertEqual(ctx["next_event_source"], "house")

    async def test_invalid_schedule_falls_back(self):
        zone_evt = datetime(2026, 10, 8, 7, 0, tzinfo=TZ)
        coord = self._make(state("off"), zone_event=zone_evt)
        ctx = await self._ctx(coord)
        self.assertEqual(ctx["next_event"], zone_evt)
        self.assertEqual(ctx["next_event_source"], "zone")

    async def test_holiday_calendar_excludes_schedule_start(self):
        zone_evt = datetime(2026, 10, 9, 6, 0, tzinfo=TZ)
        coord = self._make(state("off", next_event=NEXT_ON),
                           options={CONF_CALENDAR_ENTITY: "calendar.holidays"},
                           zone_event=zone_evt, blocked={NEXT_ON.date()})
        ctx = await self._ctx(coord)
        self.assertIsNone(ctx["schedule_next_start"])
        self.assertEqual(ctx["next_event"], zone_evt)
