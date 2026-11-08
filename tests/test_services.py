"""Service path tests: preheat.reset_model / preheat.recompute dispatched through a
service registry. The HA target helpers are synchronous (@callback) like in real Home
Assistant, so awaiting them fails with "'SelectedEntities' object can't be awaited"."""
import sys
import os
import types
import asyncio
import dataclasses
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

if "homeassistant" not in sys.modules:
    ha = types.ModuleType("homeassistant")
    ha.__path__ = []
    sys.modules["homeassistant"] = ha
    for name in ("core", "config_entries", "const", "util", "util.dt", "helpers",
                 "helpers.event", "helpers.storage", "helpers.issue_registry", "exceptions"):
        sys.modules[f"homeassistant.{name}"] = MagicMock()

import custom_components.preheat as integration
from custom_components.preheat.const import DOMAIN


@dataclasses.dataclass
class SelectedEntities:
    referenced: set = dataclasses.field(default_factory=set)
    indirectly_referenced: set = dataclasses.field(default_factory=set)


class TargetSelection:
    def __init__(self, config):
        self.config = config


class FakeServiceRegistry:
    def __init__(self):
        self.handlers = {}

    def async_register(self, domain, service, handler, *args, **kwargs):
        self.handlers[(domain, service)] = handler

    async def async_call(self, domain, service, data=None, blocking=True):
        call = MagicMock(domain=domain, service=service, data=dict(data or {}))
        await self.handlers[(domain, service)](call)


class TestServices(unittest.TestCase):

    def setUp(self):
        # Two zones + the system entry (house collector: no reset_model / async_refresh)
        self.zones = {}
        entries = []
        for entry_id in ("office", "bath"):
            coord = MagicMock(spec=["reset_model", "async_refresh"])
            coord.reset_model = AsyncMock()
            coord.async_refresh = AsyncMock()
            self.zones[entry_id] = coord
            entries.append(MagicMock(entry_id=entry_id, runtime_data=coord))
        entries.append(MagicMock(entry_id="system", runtime_data=object()))
        by_id = {e.entry_id: e for e in entries}

        self.hass = MagicMock()
        self.hass.services = FakeServiceRegistry()
        self.hass.config_entries.async_entries.return_value = entries
        self.hass.config_entries.async_get_entry.side_effect = by_id.get

        # Entity registry: one status sensor per zone, plus a foreign entity
        registry = {
            "sensor.office_status": MagicMock(platform=DOMAIN, config_entry_id="office"),
            "sensor.bath_status": MagicMock(platform=DOMAIN, config_entry_id="bath"),
            "light.kitchen": MagicMock(platform="hue", config_entry_id="hue1"),
        }
        ent_reg = MagicMock()
        ent_reg.async_get.side_effect = registry.get
        self.entity_registry = MagicMock()
        self.entity_registry.async_get.return_value = ent_reg

        # Device "dev_office" contains the office sensor (indirect reference)
        def extract(hass, selection):  # synchronous like HA's @callback helper
            data = selection.config
            ids = data.get("entity_id", [])
            ids = {ids} if isinstance(ids, str) else set(ids)
            indirect = {"sensor.office_status"} if "dev_office" in str(data.get("device_id")) else set()
            return SelectedEntities(referenced=ids, indirectly_referenced=indirect)

        self.target = types.SimpleNamespace(
            TargetSelection=TargetSelection, async_extract_referenced_entity_ids=extract)

        helpers = sys.modules["homeassistant.helpers"]
        for name, value in (("target", self.target), ("entity_registry", self.entity_registry)):
            p = patch.object(helpers, name, value, create=True)
            p.start()
            self.addCleanup(p.stop)

        asyncio.run(integration.async_setup_services(self.hass))

    def call(self, service, data=None):
        asyncio.run(self.hass.services.async_call(DOMAIN, service, data))

    def reset_calls(self):
        return {k: v.reset_model.await_count for k, v in self.zones.items()}

    def test_reset_model_entity_target(self):
        self.call("reset_model", {"entity_id": ["sensor.office_status"]})
        self.assertEqual(self.reset_calls(), {"office": 1, "bath": 0})

    def test_reset_model_no_target_resets_all_zones_and_skips_system(self):
        self.call("reset_model")
        self.assertEqual(self.reset_calls(), {"office": 1, "bath": 1})

    def test_reset_model_device_target(self):
        self.call("reset_model", {"device_id": "dev_office"})
        self.assertEqual(self.reset_calls(), {"office": 1, "bath": 0})

    def test_target_without_preheat_entity_resets_nothing(self):
        self.call("reset_model", {"entity_id": "light.kitchen"})
        self.assertEqual(self.reset_calls(), {"office": 0, "bath": 0})

    def test_explicit_config_entry_id(self):
        self.call("reset_model", {"config_entry_id": "bath"})
        self.assertEqual(self.reset_calls(), {"office": 0, "bath": 1})

    def test_entity_id_all(self):
        self.call("reset_model", {"entity_id": "all"})
        self.assertEqual(self.reset_calls(), {"office": 1, "bath": 1})

    def test_recompute_refreshes_zones_and_skips_system(self):
        self.call("recompute")
        self.assertEqual({k: v.async_refresh.await_count for k, v in self.zones.items()},
                         {"office": 1, "bath": 1})

    def test_fallback_to_deprecated_service_helper(self):
        """Older HA without helpers.target.async_extract_referenced_entity_ids."""
        legacy = MagicMock()
        legacy.async_extract_referenced_entity_ids.side_effect = (
            lambda hass, call: SelectedEntities(referenced={"sensor.bath_status"}))
        helpers = sys.modules["homeassistant.helpers"]
        with patch.object(helpers, "target", types.SimpleNamespace(TargetSelection=TargetSelection)), \
             patch.object(helpers, "service", legacy, create=True):
            self.call("reset_model", {"entity_id": "sensor.bath_status"})
        self.assertEqual(self.reset_calls(), {"office": 0, "bath": 1})
