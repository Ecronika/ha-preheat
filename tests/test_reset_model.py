"""Regression tests: 'Reset thermal model' button / preheat.reset_model service."""
import sys
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# --- MOCK Home Assistant (same pattern as the other coordinator tests) ---
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

from custom_components.preheat.coordinator import PreheatingCoordinator
from custom_components.preheat.physics import ThermalPhysics, ThermalModelData
from custom_components.preheat.const import (
    CONF_HEATING_PROFILE,
    DEFAULT_LOSS_FACTOR,
    HEATING_PROFILES,
    PROFILE_FLOOR_CONCRETE,
    PROFILE_RADIATOR_NEW,
)


def _mislearned_physics(profile_data):
    return ThermalPhysics(
        data=ThermalModelData(mass_factor=37.5, loss_factor=22.0, sample_count=17,
                              avg_error=42.0, deadtime=88.0),
        profile_data=profile_data,
    )


class TestPhysicsReset(unittest.TestCase):

    def test_reset_restores_initial_profile_defaults(self):
        profile = HEATING_PROFILES[PROFILE_RADIATOR_NEW]
        physics = _mislearned_physics(profile)

        physics.reset()

        self.assertEqual(physics.mass_factor, profile["default_mass"])
        self.assertEqual(physics.loss_factor, DEFAULT_LOSS_FACTOR)
        self.assertEqual(physics.deadtime, profile["deadtime"])
        self.assertEqual(physics.sample_count, 0)
        self.assertEqual(physics.avg_error, 0.0)

    def test_reset_with_new_profile_applies_its_defaults_and_bounds(self):
        physics = _mislearned_physics(HEATING_PROFILES[PROFILE_RADIATOR_NEW])
        concrete = HEATING_PROFILES[PROFILE_FLOOR_CONCRETE]

        physics.reset(concrete)

        self.assertEqual(physics.mass_factor, concrete["default_mass"])
        self.assertEqual(physics.deadtime, concrete["deadtime"])
        self.assertEqual(physics.min_mass, concrete["mass_factor_min"])
        self.assertEqual(physics.max_mass, concrete["mass_factor_max"])

    def test_reset_without_profile_uses_code_defaults(self):
        physics = ThermalPhysics(data=ThermalModelData(50.0, 30.0, 9, 5.0, 40.0))
        physics.reset()
        self.assertEqual(physics.sample_count, 0)
        self.assertEqual(physics.deadtime, 0.0)
        self.assertEqual(physics.loss_factor, DEFAULT_LOSS_FACTOR)


class TestCoordinatorResetModel(unittest.IsolatedAsyncioTestCase):

    def _make_coordinator(self, profile_key):
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "zone1"
        entry.title = "Office"
        entry.options = {CONF_HEATING_PROFILE: profile_key}
        entry.data = {}
        with patch.object(PreheatingCoordinator, "_setup_listeners"):
            coord = PreheatingCoordinator(hass, entry)
        coord._store = MagicMock()
        coord._store.async_save = AsyncMock()
        coord._store.async_load = AsyncMock(return_value={})
        coord.async_refresh = AsyncMock()
        return coord

    async def test_reset_model_resets_persists_and_refreshes(self):
        coord = self._make_coordinator(PROFILE_FLOOR_CONCRETE)
        profile = HEATING_PROFILES[PROFILE_FLOOR_CONCRETE]
        coord.physics = _mislearned_physics(profile)

        await coord.reset_model()  # raised AttributeError before the fix

        self.assertEqual(coord.physics.mass_factor, profile["default_mass"])
        self.assertEqual(coord.physics.deadtime, profile["deadtime"])
        self.assertEqual(coord.physics.sample_count, 0)

        saved = coord._store.async_save.await_args.args[0]
        self.assertEqual(saved["model_mass_factor"], profile["default_mass"])
        self.assertEqual(saved["sample_count"], 0)
        coord.async_refresh.assert_awaited_once()

    async def test_reset_model_uses_current_profile(self):
        """Profile changed after the model was created -> reset uses the configured one."""
        coord = self._make_coordinator(PROFILE_FLOOR_CONCRETE)
        coord.physics = _mislearned_physics(HEATING_PROFILES[PROFILE_RADIATOR_NEW])

        await coord.reset_model()

        self.assertEqual(coord.physics.mass_factor,
                         HEATING_PROFILES[PROFILE_FLOOR_CONCRETE]["default_mass"])

    async def test_reset_gain_legacy_alias(self):
        coord = self._make_coordinator(PROFILE_RADIATOR_NEW)
        coord.physics = _mislearned_physics(HEATING_PROFILES[PROFILE_RADIATOR_NEW])
        await coord.reset_gain()
        self.assertEqual(coord.physics.sample_count, 0)


class TestResetModelService(unittest.IsolatedAsyncioTestCase):

    async def test_service_awaits_reset_and_skips_system_entry(self):
        import custom_components.preheat as integration

        zone_coord = MagicMock()
        zone_coord.reset_model = AsyncMock()
        zone_entry = MagicMock(runtime_data=zone_coord)
        # System entry's runtime_data is the house collector: no reset_model attribute
        system_entry = MagicMock(runtime_data=object())
        entries = {"zone": zone_entry, "system": system_entry}

        hass = MagicMock()
        hass.config_entries.async_get_entry.side_effect = entries.get
        registered = {}
        hass.services.async_register.side_effect = (
            lambda domain, name, handler, *a, **kw: registered.__setitem__(name, handler)
        )

        await integration.async_setup_services(hass)
        with patch.object(integration, "_get_target_entries",
                          MagicMock(return_value=["zone", "system"])):
            await registered["reset_model"](MagicMock())

        zone_coord.reset_model.assert_awaited_once()


class TestFreshInstallUsesProfile(unittest.IsolatedAsyncioTestCase):
    """Without stored data the model must start from the heating profile, not generic defaults."""

    async def test_fresh_install_applies_profile_defaults(self):
        hass = MagicMock()
        hass.loop.call_later = MagicMock()  # bootstrap scan scheduling
        entry = MagicMock()
        entry.entry_id = "zone_new"
        entry.title = "Bath"
        entry.options = {CONF_HEATING_PROFILE: PROFILE_FLOOR_CONCRETE}
        entry.data = {}
        with patch.object(PreheatingCoordinator, "_setup_listeners"):
            coord = PreheatingCoordinator(hass, entry)
        coord._store = MagicMock()
        coord._store.async_load = AsyncMock(return_value=None)
        coord._store.async_save = AsyncMock()

        await coord.async_load_data()

        profile = HEATING_PROFILES[PROFILE_FLOOR_CONCRETE]
        self.assertEqual(coord.physics.mass_factor, profile["default_mass"])
        self.assertEqual(coord.physics.deadtime, profile["deadtime"])
        self.assertEqual(coord.physics.min_mass, profile["mass_factor_min"])
        self.assertEqual(coord.physics.max_mass, profile["mass_factor_max"])
        self.assertEqual(coord.physics.sample_count, 0)
        self.assertEqual(coord.cooling_analyzer.learned_tau, profile["default_coast"])

        # The reset button must also know the profile on a fresh install
        coord.physics.mass_factor = 999.0
        coord.physics.reset()
        self.assertEqual(coord.physics.mass_factor, profile["default_mass"])
