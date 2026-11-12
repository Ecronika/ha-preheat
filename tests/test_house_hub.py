"""House Arrival Hub: rolling window (finding 4), workday-aware pooling, zone day
exclusions and the per-zone opt-out (finding 3)."""
import sys
import os
import asyncio
import unittest
from datetime import date, datetime, timedelta, timezone
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

import custom_components.preheat.house_collector as hc
from custom_components.preheat.house_collector import HouseArrivalCollector, HOUSE_ARRIVAL_MAX_AGE_DAYS
from custom_components.preheat.coordinator import PreheatingCoordinator
from custom_components.preheat.const import (
    CONF_CALENDAR_ENTITY, CONF_USE_HOUSE_ARRIVALS, CONF_WORKDAY,
)

TZ = timezone.utc
NOW = datetime(2026, 11, 12, 10, 0, tzinfo=TZ)   # Thursday
WD = "binary_sensor.workday_sensor"


def clock(now):
    c = MagicMock()
    c.now.side_effect = lambda: now
    c.utcnow.side_effect = lambda: now
    c.as_local.side_effect = lambda x: x
    return c


class HouseBase(unittest.TestCase):

    def setUp(self):
        self.states = {}
        self.hass = MagicMock()
        self.hass.states.get.side_effect = self.states.get
        self.hass.config_entries.async_entries.return_value = []
        self.store = MagicMock()
        self.store.async_load = AsyncMock(return_value=None)
        self.store.async_save = AsyncMock()
        for target, value in (("Store", MagicMock(return_value=self.store)), ("dt_util", clock(NOW))):
            p = patch.object(hc, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.house = HouseArrivalCollector(self.hass)

    def workday(self, state="on", days=("mon", "tue", "wed", "thu", "fri")):
        self.states[WD] = MagicMock(state=state, attributes={"workdays": list(days)})

    def add(self, day: date, minutes: int, flag=None):
        self.house.history[day.weekday()].append((day, minutes, flag))


class TestRollingWindow(HouseBase):
    """Finding 4"""

    def test_old_arrivals_ignored_and_pruned(self):
        old = NOW.date() - timedelta(days=HOUSE_ARRIVAL_MAX_AGE_DAYS + 5)
        recent = NOW.date() - timedelta(days=7)
        self.add(old, 300)
        self.add(recent, 400)
        am, _ = self.house.get_pooled_arrivals(False, NOW.date())
        self.assertEqual(am, [400])
        self.assertTrue(self.house._prune(NOW.date()))
        self.assertEqual([e[0] for e in self.house.history[old.weekday()]], [recent])  # same weekday

    def test_record_prunes_and_saves(self):
        old = NOW.date() - timedelta(days=60)
        self.add(old, 300)
        asyncio.run(self.house.async_record_arrival(NOW))
        all_dates = [e[0] for v in self.house.history.values() for e in v]
        self.assertNotIn(old, all_dates)
        self.store.async_save.assert_awaited()

    def test_load_prunes_and_accepts_both_entry_forms(self):
        old = (NOW.date() - timedelta(days=90)).isoformat()
        recent = (NOW.date() - timedelta(days=3)).isoformat()
        self.store.async_load = AsyncMock(return_value={
            "bootstrap_done": True,
            "arrival_history_v2": {"999": {"0": [(old, 300), (recent, 400, False)]}},
        })
        asyncio.run(self.house.async_load())
        self.assertEqual(self.house.history[0], [(date.fromisoformat(recent), 400, False)])
        self.store.async_save.assert_awaited()  # pruned data written back

    def test_save_roundtrip_keeps_flag(self):
        self.add(NOW.date(), 400, False)
        self.add(NOW.date() - timedelta(days=1), 380)
        asyncio.run(self.house.async_save())
        saved = self.store.async_save.await_args.args[0]["arrival_history_v2"]["999"]
        entries = sorted(e for v in saved.values() for e in v)
        self.assertEqual(entries, sorted([(NOW.date().isoformat(), 400, False),
                                          ((NOW.date() - timedelta(days=1)).isoformat(), 380)]))


class TestWorkdayPooling(HouseBase):
    """Finding 3: workday sensor instead of fixed Sat/Sun."""

    def test_record_tags_holiday_from_sensor(self):
        self.workday(state="off")                  # public holiday on a Thursday
        asyncio.run(self.house.async_record_arrival(NOW))
        self.assertEqual(self.house.history[NOW.weekday()][-1][2], False)
        am_work, _ = self.house.get_pooled_arrivals(False, NOW.date())
        am_free, _ = self.house.get_pooled_arrivals(True, NOW.date())
        self.assertEqual((am_work, am_free), ([], [600]))

    def test_configured_workdays_used(self):
        self.workday(days=("mon", "tue", "wed", "thu"))   # 4-day week: Friday is free
        workdays, _ = self.house._workday_info()
        friday = NOW.date() - timedelta(days=6)
        self.add(friday, 540)
        self.assertEqual(self.house.get_pooled_arrivals(True, NOW.date(), workdays)[0], [540])
        self.assertEqual(self.house.get_pooled_arrivals(False, NOW.date(), workdays)[0], [])

    def test_today_holiday_uses_free_day_pool(self):
        self.workday(state="off")
        for days_ago, minutes in ((1, 420), (8, 425)):          # workday arrivals (Wed)
            self.add(NOW.date() - timedelta(days=days_ago), minutes)
        for days_ago, minutes in ((4, 660), (11, 665)):         # Sunday arrivals
            self.add(NOW.date() - timedelta(days=days_ago), minutes)
        evt, conf, _ = self.house.get_next_arrival(NOW)
        self.assertEqual((evt.date(), evt.hour), (NOW.date(), 11))   # free-day pattern today

    def test_without_sensor_falls_back_to_mon_fri(self):
        workdays, today = self.house._workday_info()
        self.assertEqual((set(workdays), today), (set(range(5)), None))


class TestExclusions(HouseBase):

    def test_excluded_days_are_skipped(self):
        for days_ago in (1, 2, 7, 8):
            self.add(NOW.date() - timedelta(days=days_ago), 420)
        tomorrow = NOW.date() + timedelta(days=1)
        evt, _, _ = self.house.get_next_arrival(NOW, is_excluded=lambda d: d == tomorrow)
        self.assertEqual(evt.date(), tomorrow + timedelta(days=3))   # Fri skipped, weekend free -> Mon


class TestCoordinatorIntegration(unittest.IsolatedAsyncioTestCase):

    def _coord(self, options):
        hass = MagicMock()
        hass.states.get.return_value = None
        entry = MagicMock(entry_id="zone", title="Bedroom", data={}, options=dict(options))
        with patch.object(PreheatingCoordinator, "_setup_listeners"):
            coord = PreheatingCoordinator(hass, entry)
        coord._get_operative_temperature = AsyncMock(return_value=19.0)
        coord._get_outdoor_temp_current = AsyncMock(return_value=5.0)
        coord._get_target_setpoint = AsyncMock(return_value=21.0)
        coord.session_manager.check_debounce = AsyncMock()
        coord.schedule_provider.get_next_start = MagicMock(return_value=None)
        coord.planner = MagicMock()
        self.zone_evt = NOW + timedelta(hours=12)
        coord.planner.get_next_scheduled_event.return_value = self.zone_evt
        coord.house_collector = MagicMock()
        self.house_evt = NOW + timedelta(hours=2)
        coord.house_collector.get_next_arrival.return_value = (self.house_evt, 0.9, "confident")
        return coord

    async def _ctx(self, coord, blocked=frozenset()):
        coord._get_blocked_dates_from_calendar = AsyncMock(return_value=set(blocked))
        import custom_components.preheat.coordinator as cm
        with patch.object(cm, "dt_util", clock(NOW)):
            return await coord._collect_context()

    async def test_house_gets_zone_exclusions(self):
        blocked = {NOW.date() + timedelta(days=2)}
        coord = self._coord({CONF_CALENDAR_ENTITY: "calendar.holidays"})
        await self._ctx(coord, blocked)
        is_excluded = coord.house_collector.get_next_arrival.call_args.kwargs["is_excluded"]
        self.assertTrue(is_excluded(NOW.date() + timedelta(days=2)))
        self.assertFalse(is_excluded(NOW.date() + timedelta(days=1)))

    async def test_default_uses_house(self):
        ctx = await self._ctx(self._coord({}))
        self.assertEqual((ctx["next_event"], ctx["next_event_source"]), (self.house_evt, "house"))
        self.assertTrue(ctx["has_confident_house"])

    async def test_zone_opt_out_uses_own_pattern(self):
        ctx = await self._ctx(self._coord({CONF_USE_HOUSE_ARRIVALS: False}))
        self.assertEqual((ctx["next_event"], ctx["next_event_source"]), (self.zone_evt, "zone"))
        self.assertFalse(ctx["has_confident_house"])
        self.assertEqual(ctx["house_next_event"], self.house_evt)   # still in the trace
