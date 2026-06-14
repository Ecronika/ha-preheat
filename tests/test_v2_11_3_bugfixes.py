"""Tests for ha-preheat v2.11.3 bugfixes and hardening."""
import sys
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, AsyncMock

# Add parent dir
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# --- MOCK Home Assistant ---
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

# Mock DUC if not done
if "homeassistant.helpers.update_coordinator" not in sys.modules:
    class MockDataUpdateCoordinator:
        def __init__(self, hass, logger, name, update_interval, **kwargs):
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.data = None
        async def _async_update_data(self): pass
        def async_add_listener(self, *args): pass
        async def async_refresh(self): pass
        async def async_request_refresh(self): pass
        def __class_getitem__(cls, item): return cls

    class MockUpdateFailed(Exception): pass

    mock_duc_mod = MagicMock()
    mock_duc_mod.DataUpdateCoordinator = MockDataUpdateCoordinator
    mock_duc_mod.UpdateFailed = MockUpdateFailed
    sys.modules["homeassistant.helpers.update_coordinator"] = mock_duc_mod

from custom_components.preheat.coordinator import PreheatingCoordinator, PreheatData
from custom_components.preheat.cooling_analyzer import CoolingAnalyzer
from custom_components.preheat.house_collector import HouseArrivalCollector
from custom_components.preheat.const import (
    VALVE_HEATING_THRESHOLD,
    OS_REASON_NO_TEMPERATURE,
    NO_TEMP_ERROR_THRESHOLD,
)

class TestV2_11_3_Bugfixes(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        self.mock_store = MagicMock()
        self.mock_store.async_load = AsyncMock(return_value=None)
        self.mock_store.async_save = AsyncMock()
        self.store_patcher = patch("custom_components.preheat.house_collector.Store", return_value=self.mock_store)
        self.store_patcher.start()

    def tearDown(self):
        self.store_patcher.stop()

    # ---------------------------------------------------------
    # T1: Ghost Heating Guard & is_heating check
    # ---------------------------------------------------------
    async def test_t1_ghost_heating_guard(self):
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test"
        entry.options = {}
        entry.data = {}
        
        with patch("custom_components.preheat.coordinator.PreheatingCoordinator._setup_listeners"), \
             patch("custom_components.preheat.coordinator.PreheatingCoordinator.async_load_data"):
             coord = PreheatingCoordinator(hass, entry)
             
        coord.cooling_analyzer = MagicMock()
        coord._preheat_active = True
        coord._outdoor_is_real = True
        
        # Scenario 1: Normal preheat active, valve is 100%
        coord._get_valve_position = MagicMock(return_value=100.0)
        ctx = {
            "operative_temp": 20.0,
            "outdoor_temp": 10.0,
            "target_setpoint": 21.0,
            "hvac_action": "heating",
            "now": datetime.now(),
            "is_window_open": False,
            "is_occupied": False
        }
        dec = {"start_time": None}
        pred = {"predicted_duration": 120.0}
        await coord._post_update_tasks(ctx, dec, pred)
        coord.cooling_analyzer.add_data_point.assert_called_with(
            dt=ctx["now"],
            t_in=20.0,
            t_out=10.0,
            is_heating=True,
            window_open=False,
            valid_cooling=False
        )
        
        coord.cooling_analyzer.reset_mock()
        
        # Scenario 2: Ghost Heating (preheat active, but valve < threshold and hvac_action is idle)
        coord._get_valve_position = MagicMock(return_value=0.0)
        ctx["hvac_action"] = "idle"
        await coord._post_update_tasks(ctx, dec, pred)
        coord.cooling_analyzer.add_data_point.assert_called_with(
            dt=ctx["now"],
            t_in=20.0,
            t_out=10.0,
            is_heating=False,
            window_open=False,
            valid_cooling=False
        )

    # ---------------------------------------------------------
    # T2: Reload Revalidation logic
    # ---------------------------------------------------------
    @patch("custom_components.preheat.coordinator._LOGGER")
    async def test_t2_revalidation_loading(self, mock_logger):
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test"
        entry.options = {}
        entry.data = {}
        
        with patch("custom_components.preheat.coordinator.PreheatingCoordinator._setup_listeners"):
             coord = PreheatingCoordinator(hass, entry)
             
        # Case 2.1: Plausible high value (24.0 is within [0.5, 48.0]) -> Keep
        coord._store.async_load = AsyncMock(return_value={
            "model_cooling_tau": 24.0,
            "cooling_confidence": 0.68,
            "tau_revalidated": False,
            "physics_version": 2
        })
        mock_logger.reset_mock()
        await coord.async_load_data()
        self.assertEqual(coord.cooling_analyzer.learned_tau, 24.0)
        self.assertEqual(coord.cooling_analyzer.confidence, 0.68)
        self.assertTrue(coord.tau_revalidated)
        mock_logger.warning.assert_not_called()
        
        # Case 2.2: Implausible high value (55.0 is outside [0.5, 48.0]) -> Clamp to default, halve confidence
        coord.tau_revalidated = False
        coord._store.async_load = AsyncMock(return_value={
            "model_cooling_tau": 55.0,
            "cooling_confidence": 0.68,
            "tau_revalidated": False,
            "physics_version": 2
        })
        mock_logger.reset_mock()
        await coord.async_load_data()
        self.assertEqual(coord.cooling_analyzer.learned_tau, 2.0)  # default_coast
        self.assertEqual(coord.cooling_analyzer.confidence, 0.34)  # 0.68 / 2
        self.assertTrue(coord.tau_revalidated)
        mock_logger.info.assert_called()  # Warning/info revalidation log
        
        # Case 2.3: Fresh configuration -> No log warnings
        coord.tau_revalidated = False
        coord._store.async_load = AsyncMock(return_value={
            "physics_version": 2
        })
        mock_logger.reset_mock()
        await coord.async_load_data()
        self.assertEqual(coord.cooling_analyzer.learned_tau, 2.0)
        self.assertEqual(coord.cooling_analyzer.confidence, 0.0)
        self.assertTrue(coord.tau_revalidated)
        mock_logger.warning.assert_not_called()

    # ---------------------------------------------------------
    # T3: Time-based gates and rate limit cap
    # ---------------------------------------------------------
    def test_t3_cooling_analyzer_time_gates(self):
        analyzer = CoolingAnalyzer()
        start_time = datetime(2024, 1, 1, 12, 0, 0)
        
        # Case 3.1: Spans 90 minutes with 19 points (at 5-min intervals) -> Valid time gate
        for i in range(19):
            dt = start_time + timedelta(minutes=i * 5)
            # Normal cooling drop of 0.01 K per minute
            t_in = 22.0 - (i * 5 * 0.01)
            analyzer.add_data_point(dt, t_in, 10.0, is_heating=False)
            
        stats = analyzer.analyze()
        self.assertIn("tau", stats)
        self.assertGreater(stats["confidence"], 0.0)
        
        # Case 3.2: Too short time spans (< 60 mins), e.g. 5 points at 5-min interval = 20 mins
        analyzer = CoolingAnalyzer()
        for i in range(5):
            dt = start_time + timedelta(minutes=i * 5)
            t_in = 22.0 - (i * 5 * 0.01)
            analyzer.add_data_point(dt, t_in, 10.0, is_heating=False)
        stats = analyzer.analyze()
        self.assertIn(stats.get("status"), ["no_segments", "no_valid_fits", "low_confidence"])

        # Case 3.3: Plausibility rate limit cap (> 0.5 K/min)
        # Drop 0.6K in 1 minute -> rate is 0.6 K/min -> should split/invalidate
        analyzer = CoolingAnalyzer()
        # Segment 1 (50 minutes, not long enough on its own)
        for i in range(11):
            dt = start_time + timedelta(minutes=i * 5)
            t_in = 22.0 - (i * 5 * 0.01)
            analyzer.add_data_point(dt, t_in, 10.0, is_heating=False)
        # Point with huge drop rate
        dt = start_time + timedelta(minutes=51)
        analyzer.add_data_point(dt, 20.0, 10.0, is_heating=False)
        
        # This split prevents the segment from being continuous. Thus it's split into too-short sub-segments.
        stats = analyzer.analyze()
        self.assertIn(stats.get("status"), ["no_segments", "no_valid_fits", "low_confidence"])

    # ---------------------------------------------------------
    # T4: Defective Zone Handling (no_temperature sensor ready errors)
    # ---------------------------------------------------------
    async def test_t4_defective_zone_handling(self):
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test"
        entry.options = {}
        entry.data = {}
        
        with patch("custom_components.preheat.coordinator.PreheatingCoordinator._setup_listeners"), \
             patch("custom_components.preheat.coordinator.PreheatingCoordinator.async_load_data"):
             coord = PreheatingCoordinator(hass, entry)
             
        # Mock dependencies
        coord.diagnostics = MagicMock()
        coord.optimal_stop_manager = MagicMock()
        coord._store = MagicMock()
        coord._store.async_save = AsyncMock()
        coord.physics = MagicMock()
        coord.cooling_analyzer = MagicMock()
        coord.cooling_analyzer.learned_tau = 4.0
        coord.cooling_analyzer.confidence = 0.8
        
        # Mock Context collection causing sensor ready = False
        coord._collect_context = AsyncMock(return_value={
            "is_sensor_ready": False,
            "operative_temp": -273.15,
            "is_occupied": False,
            "now": datetime.now()
        })
        
        # Loop update to trigger error state
        for _ in range(NO_TEMP_ERROR_THRESHOLD):
            data = await coord._async_update_data()
            
        # Verify no_temperature issue is created after 3 errors
        coord.diagnostics._create_issue.assert_called_with("no_temperature")
        self.assertEqual(coord.optimal_stop_manager._reason, OS_REASON_NO_TEMPERATURE)
        
        # Verify no saves or learning
        coord._store.async_save.assert_not_called()
        
        # Verify house aggregation excludes this defective zone
        collector = HouseArrivalCollector(hass)
        
        mock_entry = MagicMock()
        mock_entry.runtime_data = coord
        hass.config_entries.async_entries.return_value = [mock_entry]
        
        # Case A: Normal (errors = 0)
        coord._consecutive_readiness_errors = 0
        coord.data = PreheatData(
            preheat_active=False,
            next_start_time=None,
            operative_temp=20.0,
            target_setpoint=21.0,
            next_arrival=None,
            predicted_duration=200.0,
            mass_factor=0,
            loss_factor=0,
            learning_active=False
        )
        dur = collector.get_max_predicted_duration()
        self.assertEqual(dur, 200.0)
        
        # Case B: Defective (errors = NO_TEMP_ERROR_THRESHOLD)
        coord._consecutive_readiness_errors = NO_TEMP_ERROR_THRESHOLD
        dur = collector.get_max_predicted_duration()
        self.assertEqual(dur, 120.0) # default fallback
        
        # Test floor of tau_hours in optimal stop
        coord.cooling_analyzer.learned_tau = 1.0
        coord.cooling_analyzer.confidence = 0.8
        
        def get_conf_mock(key, default=None):
            if key == "heating_profile":
                return "radiator_new"
            return default
        coord._get_conf = MagicMock(side_effect=get_conf_mock)
        
        # Call the method directly
        is_active, stop_time, stop_reason, savings_total, savings_remaining, tau_hours = \
            coord._update_optimal_stop_and_savings(
                ctx={"operative_temp": 20.0, "target_setpoint": 21.0, "outdoor_temp": 10.0, "forecasts": []},
                now=datetime.now(),
                sched_decision=MagicMock(session_end=datetime.now() + timedelta(hours=1))
            )
            
        # default_coast for radiator_new is 2.0. So tau_hours should be max(1.0, 2.0) = 2.0.
        self.assertEqual(tau_hours, 2.0)

    # ---------------------------------------------------------
    # N1: Used tau uncapped
    # ---------------------------------------------------------
    async def test_n1_uncapped_tau(self):
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test"
        entry.options = {}
        entry.data = {}
        
        with patch("custom_components.preheat.coordinator.PreheatingCoordinator._setup_listeners"), \
             patch("custom_components.preheat.coordinator.PreheatingCoordinator.async_load_data"):
             coord = PreheatingCoordinator(hass, entry)
             
        coord.cooling_analyzer = MagicMock()
        coord.cooling_analyzer.learned_tau = 24.0
        coord.cooling_analyzer.confidence = 0.8
        
        def get_conf_mock(key, default=None):
            if key == "heating_profile":
                return "radiator_new"
            return default
        coord._get_conf = MagicMock(side_effect=get_conf_mock)
        coord.optimal_stop_manager = MagicMock()
        
        # Call the optimal stop update
        is_active, stop_time, stop_reason, savings_total, savings_remaining, tau_hours = \
            coord._update_optimal_stop_and_savings(
                ctx={"operative_temp": 20.0, "target_setpoint": 21.0, "outdoor_temp": 10.0, "forecasts": []},
                now=datetime.now(),
                sched_decision=MagicMock(session_end=datetime.now() + timedelta(hours=1))
            )
            
        # Verify that tau_hours is 24.0, which is uncapped (12h cap removed)
        self.assertEqual(tau_hours, 24.0)

    # ---------------------------------------------------------
    # N2: Defective zone partial save (non-thermal only)
    # ---------------------------------------------------------
    async def test_n2_partial_save_no_temperature(self):
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test"
        entry.options = {}
        entry.data = {}
        
        with patch("custom_components.preheat.coordinator.PreheatingCoordinator._setup_listeners"), \
             patch("custom_components.preheat.coordinator.PreheatingCoordinator.async_load_data"):
             coord = PreheatingCoordinator(hass, entry)
             
        # Mock pre-existing data in storage
        mock_stored_data = {
            "schema_version": 1,
            "physics_version": 2,
            "model_cooling_tau": 24.0,
            "cooling_confidence": 0.8,
            "tau_revalidated": True,
            "model_mass_factor": 15.0,
            "model_loss_factor": 4.5,
            "sample_count": 5,
            "avg_error": 0.1,
            "last_comfort_setpoint": 21.0,
            "arrival_history_v2": {"1": []},
            "bootstrap_done": False,
            "enable_active": False,
            "diagnostics": {"old_diag": 1},
            "cumulative_shadow_savings": 1.2
        }
        coord._store.async_load = AsyncMock(return_value=mock_stored_data)
        coord._store.async_save = AsyncMock()
        
        # Simulate defective state
        coord._consecutive_readiness_errors = NO_TEMP_ERROR_THRESHOLD
        
        # Update current in-memory non-thermal states
        coord.planner.to_dict = MagicMock(return_value={"updated_history": True})
        coord.bootstrap_done = True
        coord.enable_active = True
        coord.diagnostics.data = {"new_diag": 2}
        coord._shadow_metrics = {"cumulative_shadow_savings": 5.5}
        
        # Call the save
        await coord._async_save_data()
        
        # Check that async_save was called
        coord._store.async_save.assert_called_once()
        saved_dict = coord._store.async_save.call_args[0][0]
        
        # Thermal fields must remain exactly as loaded
        self.assertEqual(saved_dict["model_cooling_tau"], 24.0)
        self.assertEqual(saved_dict["cooling_confidence"], 0.8)
        self.assertTrue(saved_dict["tau_revalidated"])
        self.assertEqual(saved_dict["model_mass_factor"], 15.0)
        self.assertEqual(saved_dict["model_loss_factor"], 4.5)
        self.assertEqual(saved_dict["sample_count"], 5)
        self.assertEqual(saved_dict["avg_error"], 0.1)
        self.assertEqual(saved_dict["last_comfort_setpoint"], 21.0)
        
        # Non-thermal fields must be updated
        self.assertEqual(saved_dict["arrival_history_v2"], {"updated_history": True})
        self.assertTrue(saved_dict["bootstrap_done"])
        self.assertTrue(saved_dict["enable_active"])
        self.assertEqual(saved_dict["diagnostics"], {"new_diag": 2})
        self.assertEqual(saved_dict["cumulative_shadow_savings"], 5.5)

    # ---------------------------------------------------------
    # UI link attributes on PreheatStatusSensor
    # ---------------------------------------------------------
    async def test_ui_link_attributes(self):
        from custom_components.preheat.sensor import PreheatStatusSensor
        from custom_components.preheat.const import (
            CONF_CLIMATE,
            CONF_TEMPERATURE,
            CONF_OUTDOOR_TEMP,
            VERSION,
        )

        coordinator = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_entry"
        entry.title = "Test Zone"

        # Mock coordinator data and physics
        data = MagicMock()
        data.target_setpoint = 21.0
        data.operative_temp = 20.0
        data.predicted_duration = 15.5
        data.window_open = False
        data.last_comfort_setpoint = 21.5
        data.deadtime = 10.0
        data.decision_trace = "trace"
        data.detected_modes = {}
        data.next_start_time = None
        data.next_arrival = None
        data.next_departure = None
        data.optimal_stop_time = None

        physics = MagicMock()
        physics.get_confidence = MagicMock(return_value=0.85)
        physics.avg_error = 0.25
        physics.sample_count = 10
        physics.health_score = 90

        coordinator.data = data
        coordinator.physics = physics

        # Mock _get_conf to return test entities
        conf_map = {
            CONF_CLIMATE: "climate.living_room",
            CONF_TEMPERATURE: "sensor.living_room_temp",
            CONF_OUTDOOR_TEMP: "sensor.outdoor_temp",
        }
        coordinator._get_conf = MagicMock(side_effect=lambda key, default=None: conf_map.get(key, default))

        # Instantiate sensor
        sensor = PreheatStatusSensor(coordinator, entry)

        # Retrieve attributes
        attrs = sensor.extra_state_attributes

        # Verify added UI link attributes
        self.assertEqual(attrs["climate_entity"], "climate.living_room")
        self.assertEqual(attrs["operative_sensor"], "sensor.living_room_temp")
        self.assertEqual(attrs["integration_version"], VERSION)

        # Verify other attributes remain correct
        self.assertEqual(attrs["target_temp"], 21.0)
        self.assertEqual(attrs["current_temp"], 20.0)
        self.assertEqual(attrs["predicted_duration"], 15.5)
        self.assertEqual(attrs["confidence"], 0.85)
        self.assertEqual(attrs["avg_error"], 0.25)
        self.assertEqual(attrs["sample_count"], 10)
        self.assertEqual(attrs["window_open"], False)
        self.assertEqual(attrs["learned_setpoint"], 21.5)
        self.assertEqual(attrs["deadtime_min"], 10.0)
        self.assertEqual(attrs["health_score"], 90)

    # ---------------------------------------------------------
    # Robust Outdoor Temperature Tests
    # ---------------------------------------------------------
    async def test_config_flow_outdoor_temp(self):
        from custom_components.preheat.config_flow import PreheatingConfigFlow
        from custom_components.preheat.const import CONF_OUTDOOR_TEMP, CONF_CLIMATE, CONF_OCCUPANCY
        
        flow = PreheatingConfigFlow()
        flow.hass = MagicMock()
        
        # Test validation success when outdoor temp is present
        user_input = {
            CONF_CLIMATE: "climate.living_room",
            CONF_OCCUPANCY: "binary_sensor.occ",
            CONF_OUTDOOR_TEMP: "sensor.outdoor_temp",
        }
        
        # Mock validation
        flow._validate_entity_ids = MagicMock(return_value={})
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()
        flow.async_create_entry = MagicMock(return_value="success")
        
        res = await flow.async_step_user(user_input)
        self.assertEqual(res, "success")
        
        # Verify custom entry data saves CONF_OUTDOOR_TEMP
        data_arg = flow.async_create_entry.call_args[1]["data"]
        self.assertEqual(data_arg[CONF_OUTDOOR_TEMP], "sensor.outdoor_temp")

    async def test_outdoor_precedence_and_fallback(self):
        from custom_components.preheat.const import CONF_OUTDOOR_TEMP, CONF_WEATHER_ENTITY
        
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test"
        entry.options = {}
        entry.data = {}
        
        with patch("custom_components.preheat.coordinator.PreheatingCoordinator._setup_listeners"), \
             patch("custom_components.preheat.coordinator.PreheatingCoordinator.async_load_data"):
             coord = PreheatingCoordinator(hass, entry)
        
        # Mock _get_conf to return sensor and weather
        conf_map = {
            CONF_OUTDOOR_TEMP: "sensor.outdoor_temp",
            CONF_WEATHER_ENTITY: "weather.forecast",
        }
        coord._get_conf = MagicMock(side_effect=lambda key, default=None: conf_map.get(key, default))
        
        # Setup states
        mock_sensor_state = MagicMock()
        mock_sensor_state.state = "15.5"
        mock_weather_state = MagicMock()
        mock_weather_state.attributes = {"temperature": 18.0}
        
        def mock_get_state(entity_id):
            if entity_id == "sensor.outdoor_temp":
                return mock_sensor_state
            if entity_id == "weather.forecast":
                return mock_weather_state
            return None
        hass.states.get = MagicMock(side_effect=mock_get_state)
        
        # 1. Sensor takes precedence -> should get 15.5
        temp = await coord._get_outdoor_temp_current()
        self.assertEqual(temp, 15.5)
        self.assertTrue(coord._outdoor_is_real)
        
        # 2. Sensor unavailable -> fallback to Weather -> should get 18.0
        mock_sensor_state.state = "unavailable"
        coord._last_weather_check = None # Clear cache
        temp = await coord._get_outdoor_temp_current()
        self.assertEqual(temp, 18.0)
        self.assertTrue(coord._outdoor_is_real)
        
        # 3. Both unavailable -> should return fallback 10.0 and set real=False
        mock_weather_state.attributes = {}
        coord._last_weather_check = None # Clear cache
        temp = await coord._get_outdoor_temp_current()
        self.assertEqual(temp, 10.0)
        self.assertFalse(coord._outdoor_is_real)

    async def test_physics_learning_gating(self):
        from custom_components.preheat.physics import ThermalPhysics
        
        physics = ThermalPhysics()
        physics.mass_factor = 10.0
        physics.loss_factor = 2.0
        physics.learning_rate = 0.5
        physics.avg_error = 0.0
        
        # Case A: outdoor_valid=False -> mass factor should update, loss factor remains unchanged
        success = physics.update_model(
            actual_duration=35.0,
            delta_t_in=1.0,
            delta_t_out=1.0,
            valve_position=None,
            outdoor_valid=False
        )
        self.assertTrue(success)
        self.assertNotEqual(physics.mass_factor, 10.0)
        self.assertEqual(physics.loss_factor, 2.0)
        
        # Case B: outdoor_valid=True -> loss factor should update
        physics.mass_factor = 10.0 # reset
        success = physics.update_model(
            actual_duration=35.0,
            delta_t_in=1.0,
            delta_t_out=1.0,
            valve_position=None,
            outdoor_valid=True
        )
        self.assertTrue(success)
        self.assertNotEqual(physics.loss_factor, 2.0)

    async def test_cooling_analyzer_gating(self):
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test"
        entry.options = {}
        entry.data = {}
        
        with patch("custom_components.preheat.coordinator.PreheatingCoordinator._setup_listeners"), \
             patch("custom_components.preheat.coordinator.PreheatingCoordinator.async_load_data"):
             coord = PreheatingCoordinator(hass, entry)
             
        coord.cooling_analyzer = MagicMock()
        
        # Test Case 1: _outdoor_is_real is True -> add_data_point called
        coord._outdoor_is_real = True
        ctx = {
            "now": datetime.now(),
            "operative_temp": 20.0,
            "outdoor_temp": 10.0,
            "is_window_open": False,
            "is_occupied": False,
            "target_setpoint": 21.0,
        }
        dec = {"start_time": None}
        pred = {"predicted_duration": 0}
        await coord._post_update_tasks(ctx, dec, pred)
        coord.cooling_analyzer.add_data_point.assert_called_once()
        
        # Test Case 2: _outdoor_is_real is False -> add_data_point not called
        coord.cooling_analyzer.reset_mock()
        coord._outdoor_is_real = False
        await coord._post_update_tasks(ctx, dec, pred)
        coord.cooling_analyzer.add_data_point.assert_not_called()

    async def test_outdoor_availability_issue(self):
        from custom_components.preheat.const import CONF_OUTDOOR_TEMP
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test"
        entry.options = {}
        entry.data = {}
        
        with patch("custom_components.preheat.coordinator.PreheatingCoordinator._setup_listeners"), \
             patch("custom_components.preheat.coordinator.PreheatingCoordinator.async_load_data"):
             coord = PreheatingCoordinator(hass, entry)
             
        coord.diagnostics = MagicMock()
        coord._get_conf = MagicMock(return_value="sensor.outdoor_temp")
        
        # Scenario A: Real is True -> delete issue
        coord._outdoor_is_real = True
        coord._update_outdoor_availability_issue(datetime.now())
        coord.diagnostics._delete_issue.assert_called_with("outdoor_source_unavailable")
        
        # Scenario B: Real is False, but 30 min has not elapsed -> no issue created yet
        coord.diagnostics.reset_mock()
        coord._outdoor_is_real = False
        now = datetime.now()
        coord._last_real_outdoor_ts = now - timedelta(minutes=15)
        coord._update_outdoor_availability_issue(now)
        coord.diagnostics._create_issue.assert_not_called()
        
        # Scenario C: Real is False, 30 min has elapsed -> create issue
        coord.diagnostics.reset_mock()
        coord._last_real_outdoor_ts = now - timedelta(minutes=31)
        coord._update_outdoor_availability_issue(now)
        coord.diagnostics._create_issue.assert_called_with("outdoor_source_unavailable")
