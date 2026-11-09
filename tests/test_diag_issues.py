"""Repair issues must reflect the current state: stale_sensor uses last_reported, every
issue clears itself when its condition is gone, and legacy issue IDs are removed."""
import sys
import os
import re
import types
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

if "homeassistant" not in sys.modules:
    ha = types.ModuleType("homeassistant")
    ha.__path__ = []
    sys.modules["homeassistant"] = ha
    for name in ("core", "config_entries", "const", "util", "util.dt", "helpers",
                 "helpers.event", "helpers.storage", "helpers.issue_registry", "exceptions"):
        sys.modules[f"homeassistant.{name}"] = MagicMock()

from custom_components.preheat.diagnostics import DiagnosticsManager
from custom_components.preheat.const import (
    CONF_CLIMATE, CONF_OCCUPANCY, CONF_SCHEDULE_ENTITY, CONF_STOP_TOLERANCE, CONF_TEMPERATURE,
)

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
COMPONENT = os.path.join(os.path.dirname(__file__), "..", "custom_components", "preheat")


def state(value, age_h=0.0, reported_age_h=None, **attrs):
    st = MagicMock()
    st.state = value
    st.attributes = attrs
    st.last_updated = NOW - timedelta(hours=age_h)
    st.last_changed = st.last_updated
    st.last_reported = NOW - timedelta(hours=reported_age_h if reported_age_h is not None else age_h)
    return st


class Base(unittest.TestCase):

    def setUp(self):
        self.states = {}
        self.options = {}
        hass = MagicMock()
        hass.states.get.side_effect = self.states.get
        entry = MagicMock(entry_id="zone", title="Office", options=self.options, data={})
        coord = MagicMock(_external_inhibit=False, _window_open_detected=False)
        coord._get_conf.side_effect = lambda key, default=None: self.options.get(key, default)
        self.diag = DiagnosticsManager(hass, entry, coord)
        self.diag._create_issue = MagicMock()
        self.diag._delete_issue = MagicMock()
        clock = MagicMock()
        clock.utcnow.return_value = NOW
        p = patch("custom_components.preheat.diagnostics.dt_util", clock)
        p.start()
        self.addCleanup(p.stop)

    def ctx(self, **kw):
        base = {"operative_temp": 20.0, "target_setpoint": 21.0, "outdoor_temp": 5.0,
                "forecasts": [], "preheat_active": False, "valve_position": 0.0}
        base.update(kw)
        return base

    def run_sensors(self, **kw):
        asyncio.run(self.diag._diag_sensors(self.ctx(**kw), MagicMock(), None, {}))

    def run_config(self, **kw):
        asyncio.run(self.diag._diag_config(self.ctx(**kw), MagicMock(mass_factor=50.0), None, {}))

    def created(self, issue_id):
        return [c for c in self.diag._create_issue.call_args_list if c.args[0] == issue_id]

    def deleted(self, issue_id):
        return any(c.args[0] == issue_id for c in self.diag._delete_issue.call_args_list)


class TestStaleSensor(Base):

    def setUp(self):
        super().setUp()
        self.options[CONF_TEMPERATURE] = "sensor.office_temp"

    def test_unchanged_value_but_recent_report_is_not_stale(self):
        """KNX cyclic sending: value unchanged for 9 h, last report 5 min ago."""
        self.states["sensor.office_temp"] = state("20.5", age_h=9, reported_age_h=0.1)
        self.run_sensors()
        self.run_sensors()
        self.assertEqual(self.created("stale_sensor"), [])
        self.assertTrue(self.deleted("stale_sensor"))
        self.assertEqual(self.diag.data["stale_sensor_counter"], 0)

    def test_stale_confirmed_then_cleared_and_counter_reset(self):
        self.states["sensor.office_temp"] = state("20.5", age_h=7)
        self.run_sensors()
        self.assertEqual(self.created("stale_sensor"), [])
        self.run_sensors()
        call = self.created("stale_sensor")[-1]
        self.assertEqual(call.kwargs["translation_placeholders"]["entity"], "sensor.office_temp")
        self.assertNotIn("is_persistent", call.kwargs)  # re-evaluated after restart

        self.diag._delete_issue.reset_mock()
        self.states["sensor.office_temp"] = state("20.6", age_h=0)
        self.run_sensors()
        self.assertTrue(self.deleted("stale_sensor"))
        self.assertEqual(self.diag.data["stale_sensor_counter"], 0)

        # A later single stale check must not raise immediately
        self.diag._create_issue.reset_mock()
        self.states["sensor.office_temp"] = state("20.6", age_h=7)
        self.run_sensors()
        self.assertEqual(self.created("stale_sensor"), [])

    def test_persisted_counter_from_old_version_is_reset_on_load(self):
        self.diag.load_data({"stale_sensor_counter": 57})
        self.states["sensor.office_temp"] = state("20.5", age_h=7)
        self.run_sensors()
        self.assertEqual(self.created("stale_sensor"), [])

    def test_unavailable_sensor_uses_climate_fallback(self):
        self.options[CONF_CLIMATE] = "climate.office"
        self.states["sensor.office_temp"] = state("unavailable", age_h=20)
        self.states["climate.office"] = state("heat", age_h=8)
        self.run_sensors()
        self.run_sensors()
        self.assertEqual(self.created("stale_sensor")[-1].kwargs["translation_placeholders"]["entity"],
                         "climate.office")

    def test_all_unavailable_is_not_stale(self):
        self.states["sensor.office_temp"] = state("unavailable", age_h=20)
        self.run_sensors()
        self.run_sensors()
        self.assertEqual(self.created("stale_sensor"), [])
        self.assertTrue(self.deleted("stale_sensor"))

    def test_without_last_reported_attribute(self):
        """Older cores: fall back to last_updated."""
        st = state("20.5", age_h=7)
        del st.last_reported
        self.states["sensor.office_temp"] = st
        self.run_sensors()
        self.run_sensors()
        self.assertEqual(len(self.created("stale_sensor")), 1)


class TestIssuesClearThemselves(Base):

    def test_sanity_temp(self):
        self.run_sensors(operative_temp=50.0)
        self.assertEqual(len(self.created("sanity_temp")), 1)
        self.run_sensors(operative_temp=21.0)
        self.assertTrue(self.deleted("sanity_temp"))

    def test_occupancy_stale(self):
        self.options[CONF_OCCUPANCY] = "binary_sensor.office"
        self.states["binary_sensor.office"] = state("off", age_h=24 * 4)
        self.run_sensors()
        self.assertEqual(len(self.created("occupancy_stale")), 1)
        self.states["binary_sensor.office"] = state("on", age_h=1)
        self.run_sensors()
        self.assertTrue(self.deleted("occupancy_stale"))

    def test_valve_saturation(self):
        self.run_sensors(preheat_active=True, valve_position=100.0, operative_temp=17.0)
        self.assertEqual(len(self.created("valve_saturation")), 1)
        self.run_sensors(preheat_active=True, valve_position=40.0, operative_temp=17.0)
        self.assertTrue(self.deleted("valve_saturation"))

    def test_config_checks(self):
        self.options[CONF_SCHEDULE_ENTITY] = "schedule.office"
        self.options[CONF_STOP_TOLERANCE] = 5.0
        self.states["schedule.office"] = state("on")
        self.run_config(target_setpoint=40.0)
        for issue in ("zombie_schedule", "config_sanity", "tolerance_sanity"):
            self.assertEqual(len(self.created(issue)), 1, issue)

        self.options[CONF_STOP_TOLERANCE] = 0.5
        self.states["schedule.office"] = state("on", next_event=NOW + timedelta(hours=1))
        self.run_config(target_setpoint=21.0)
        for issue in ("zombie_schedule", "config_sanity", "tolerance_sanity",
                      "sensor_unit_mismatch", "hold_stuck", "coast_capped"):
            self.assertTrue(self.deleted(issue), issue)


class TestStructural(unittest.TestCase):

    def test_every_created_issue_has_a_delete_path(self):
        src = ""
        for name in ("diagnostics.py", "coordinator.py"):
            with open(os.path.join(COMPONENT, name), encoding="utf-8") as f:
                src += f.read()
        created = set(re.findall(r'_create_issue\(\s*"([a-z_]+)"', src))
        deleted = set(re.findall(r'_delete_issue\(\s*"([a-z_]+)"', src))
        self.assertEqual(created - deleted, set())

    def test_legacy_issue_cleanup(self):
        diag = DiagnosticsManager(MagicMock(), MagicMock(entry_id="zone"), MagicMock())
        diag._delete_issue = MagicMock()
        diag.cleanup_legacy_issues()
        removed = {c.args[0] for c in diag._delete_issue.call_args_list}
        self.assertTrue({"physics_limit", "physics_railing", "physics_railing_mass",
                         "limit_exceeded", "sensor_unit"} <= removed)
