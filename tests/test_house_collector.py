"""Tests for House Arrival Collector and Hub Integration."""
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timedelta, date, timezone
import sys

# Mock HA util dt
from homeassistant.util import dt as dt_util

from custom_components.preheat.house_collector import HouseArrivalCollector, get_percentile, parse_window
from custom_components.preheat.const import (
    DOMAIN,
    CONF_GLOBAL_PRESENCE,
    CONF_ARRIVAL_COMFORT_BIAS,
    CONF_EVENING_COMFORT_WINDOW,
    CONF_SCHEDULE_ENTITY,
)
from custom_components.preheat import async_setup_entry, async_unload_entry
from custom_components.preheat.coordinator import PreheatingCoordinator, Context, Prediction
from custom_components.preheat.providers import ProviderDecision

class TestHouseCollector(unittest.IsolatedAsyncioTestCase):
    """Test cases for the House Arrival Collector and global entities."""

    def setUp(self):
        """Set up test environment."""
        self.hass = MagicMock()
        self.hass.data = {}
        self.hass.config_entries = MagicMock()
        self.hass.config_entries.async_forward_entry_setups = AsyncMock()
        self.hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        
        # Mock Store
        self.mock_store = MagicMock()
        self.mock_store.async_load = AsyncMock(return_value=None)
        self.mock_store.async_save = AsyncMock()
        
        self.store_patcher = patch("custom_components.preheat.house_collector.Store", return_value=self.mock_store)
        self.store_patcher.start()

        # Mock dt_util locally to avoid shared test mock pollution
        self.dt_patcher = patch("custom_components.preheat.house_collector.dt_util")
        self.mock_dt = self.dt_patcher.start()
        self.mock_dt.now.side_effect = lambda: datetime.now(timezone.utc)
        self.mock_dt.as_local.side_effect = lambda x: x.astimezone() if hasattr(x, "astimezone") else x

    def tearDown(self):
        """Tear down test environment."""
        self.store_patcher.stop()
        self.dt_patcher.stop()

    async def test_h1_single_instance_lifecycle(self):
        """Test H1: Single shared instance creation, reuse, and teardown with Preheat System entry."""
        # Setup entries
        entry1 = MagicMock()
        entry1.entry_id = "zone_1"
        entry1.unique_id = "zone_1"
        entry1.title = "Zone 1"
        entry1.options = {}
        entry1.data = {}
        
        system_entry = MagicMock()
        system_entry.entry_id = "system_entry"
        system_entry.unique_id = "preheat_system"
        system_entry.title = "Preheat System"
        system_entry.options = {}
        system_entry.data = {}
        
        entry2 = MagicMock()
        entry2.entry_id = "zone_2"
        entry2.unique_id = "zone_2"
        entry2.title = "Zone 2"
        entry2.options = {}
        entry2.data = {}

        self.hass.config_entries.async_entries.return_value = [entry1]

        # 1. Zone setup triggers system entry flow creation
        with patch("custom_components.preheat.coordinator.PreheatingCoordinator") as mock_coord_cls, \
             patch("custom_components.preheat.house_collector.HouseArrivalCollector.async_bootstrap") as mock_bootstrap:
            
            mock_coord = MagicMock()
            mock_coord.async_load_data = AsyncMock()
            mock_coord.async_config_entry_first_refresh = AsyncMock()
            mock_coord_cls.return_value = mock_coord
            
            await async_setup_entry(self.hass, entry1)
            
            self.assertIn("house", self.hass.data[DOMAIN])
            house_instance = self.hass.data[DOMAIN]["house"]
            self.assertIsInstance(house_instance, HouseArrivalCollector)
            
            # Assert system flow init called
            self.hass.config_entries.flow.async_init.assert_called_once_with(
                DOMAIN, context={"source": "system"}
            )
            mock_bootstrap.assert_called_once()
            
            # 2. System entry setup
            self.hass.config_entries.async_entries.return_value = [entry1, system_entry]
            await async_setup_entry(self.hass, system_entry)
            self.assertEqual(system_entry.runtime_data, house_instance)
            
            # 3. Second zone setup (should NOT trigger flow creation again since system_entry is in async_entries)
            self.hass.config_entries.flow.async_init.reset_mock()
            self.hass.config_entries.async_entries.return_value = [entry1, system_entry, entry2]
            
            await async_setup_entry(self.hass, entry2)
            self.hass.config_entries.flow.async_init.assert_not_called()
            
            # 4. Unload zone entry 1
            with patch("homeassistant.config_entries.ConfigEntry.async_on_unload"), \
                 patch("homeassistant.config_entries.ConfigEntry.add_update_listener"), \
                 patch("homeassistant.config_entries.ConfigEntry.runtime_data"):
                
                await async_unload_entry(self.hass, entry1)
                # House collector remains
                self.assertIn("house", self.hass.data[DOMAIN])
                
                # 5. Unload system entry
                await async_unload_entry(self.hass, system_entry)
                # House collector is cleaned up/removed
                self.assertNotIn("house", self.hass.data[DOMAIN])

    def test_h3_predictor_math(self):
        """Test H3: Prediction math for workday/weekend morning/evening and comfort bias."""
        house = HouseArrivalCollector(self.hass)
        
        # Populate history with real bootstrap-like data:
        # We need to test the Morning (AM) prediction:
        # Spread = 86 min, P25 = 05:51 (351 min), P75 = 07:17 (437 min)
        house.history[0] = [(date(2026, 6, 8), 351), (date(2026, 6, 15), 351)]
        house.history[1] = [(date(2026, 6, 9), 437), (date(2026, 6, 16), 437)]
        
        am_wd, _ = house.get_pooled_arrivals(is_weekend=False)
        self.assertEqual(am_wd, [351, 351, 437, 437])
        
        p25 = get_percentile(am_wd, 0.25)
        p75 = get_percentile(am_wd, 0.75)
        self.assertEqual(p25, 351)
        self.assertEqual(p75, 437)
        self.assertEqual(p75 - p25, 86)
        
        # Test confidence: 1 - 86/300 = 0.71333...
        conf = max(0.0, 1.0 - (86.0 / 300.0))
        self.assertAlmostEqual(conf, 0.71333, places=4)
        
        # Predict next arrival. Since today is Saturday 2026-06-13, we check predictions.
        # Mon 2026-06-15 is a workday.
        now = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)
        expected_dt, predicted_conf, source = house.get_next_arrival(now)
        
        self.assertIsNotNone(expected_dt)
        self.assertEqual(source, "confident")
        # Use python native timezone-aware conversion to avoid calling mocked dt_util in test body
        expected_local = expected_dt.astimezone()
        self.assertEqual(expected_local.weekday(), 0) # Monday
        self.assertEqual(expected_local.hour, 5)
        self.assertEqual(expected_local.minute, 51)
        self.assertAlmostEqual(predicted_conf, 0.71333, places=4)

        # Test PM evening comfort bias
        # PM list: [1000, 1000, 1300, 1300] (len=4). P25 = 1000, P75 = 1300. Spread = 300.
        house.history[0].extend([(date(2026, 6, 8), 1000), (date(2026, 6, 15), 1000)])
        house.history[1].extend([(date(2026, 6, 9), 1300), (date(2026, 6, 16), 1300)])
        
        _, pm_wd = house.get_pooled_arrivals(is_weekend=False)
        self.assertEqual(pm_wd, [1000, 1000, 1300, 1300])
        
        # Test PM comfort bias:
        # Comfort = P15. Balanced = P25. Economy = P50.
        house.comfort_bias = "comfort"
        p15_val = get_percentile(pm_wd, 0.15) # idx = 0 -> 1000
        house.comfort_bias = "balanced"
        p25_val = get_percentile(pm_wd, 0.25) # idx = 0 -> 1000
        house.comfort_bias = "economy"
        p50_val = get_percentile(pm_wd, 0.50) # idx = 1 -> 1000
        
        # Test fallback evening window if confidence is low (< 0.7)
        # Evening spread is 300, so evening confidence is 0.0.
        house.evening_window_str = "17:30-22:00"
        now_mon_afternoon = datetime(2026, 6, 15, 13, 0, 0, tzinfo=timezone.utc)
        expected_dt, predicted_conf, source = house.get_next_arrival(now_mon_afternoon)
        self.assertIsNotNone(expected_dt)
        self.assertEqual(source, "fallback")
        expected_local = expected_dt.astimezone()
        self.assertEqual(expected_local.weekday(), 0) # Monday
        self.assertEqual(expected_local.hour, 17)
        self.assertEqual(expected_local.minute, 30)
        self.assertEqual(predicted_conf, 0.0)

        # Test no evening window -> source is "none"
        house.evening_window_str = None
        # Clear AM history so AM won't match either
        house.history = {i: [] for i in range(7)}
        house.history[0] = [(date(2026, 6, 8), 1000), (date(2026, 6, 15), 1000)]
        house.history[1] = [(date(2026, 6, 9), 1300), (date(2026, 6, 16), 1300)]
        expected_dt, predicted_conf, source = house.get_next_arrival(now_mon_afternoon)
        self.assertIsNone(expected_dt)
        self.assertEqual(source, "none")
        self.assertEqual(predicted_conf, 0.0)

    async def test_h4_arbitration_logic(self):
        """Test H4: Zone arbitration order: Schedule > House (confident) > Zone Learned > None."""
        # Create a mock coordinator
        entry = MagicMock()
        entry.entry_id = "zone_1"
        entry.options = {CONF_SCHEDULE_ENTITY: "schedule.test"}
        entry.data = {}
        
        with patch("custom_components.preheat.coordinator.PreheatingCoordinator._setup_listeners"), \
             patch("custom_components.preheat.coordinator.PreheatingCoordinator.async_load_data"):
            coord = PreheatingCoordinator(self.hass, entry)
            
        house = HouseArrivalCollector(self.hass)
        coord.house_collector = house
        
        now = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)
        
        # Mock schedule decision (Schedule is valid)
        sched_decision = ProviderDecision(
            should_stop=False,
            session_end=now + timedelta(hours=3),
            is_valid=True,
            is_shadow=False,
            confidence=1.0
        )
        coord.schedule_provider.get_decision = MagicMock(return_value=sched_decision)
        
        ctx = {
            "now": now,
            "operative_temp": 18.0,
            "target_setpoint": 21.0,
            "outdoor_temp": 10.0,
            "forecasts": [],
            "has_confident_house": True,
            "has_house_fallback": False,
            "house_confidence": 0.8,
            "house_source": "confident",
            "house_next_event": now + timedelta(minutes=45),
            "zone_next_event": now + timedelta(minutes=60),
            "next_event": now + timedelta(minutes=45),
        }
        
        pred = {
            "predicted_duration": 50.0,
        }
        
        # 1. Schedule wins over House
        dec = coord._evaluate_start_decision(ctx, pred)
        self.assertEqual(dec["start_source"], "schedule")

        # 2. House wins when Schedule is invalid
        sched_decision = ProviderDecision(
            should_stop=False,
            session_end=now + timedelta(hours=3),
            is_valid=False,
            is_shadow=False,
            confidence=1.0
        )
        coord.schedule_provider.get_decision = MagicMock(return_value=sched_decision)
        dec = coord._evaluate_start_decision(ctx, pred)
        self.assertEqual(dec["start_source"], "house")
        self.assertEqual(dec["should_start"], True)

        # 3. Zone learned wins when House is not confident and no fallback
        ctx["has_confident_house"] = False
        ctx["has_house_fallback"] = False
        ctx["house_confidence"] = 0.5
        ctx["house_source"] = "none"
        ctx["next_event"] = now + timedelta(minutes=60)
        
        # Mock mature zone pattern
        mock_pattern = MagicMock()
        mock_pattern.confidence = 0.8
        coord.planner.last_pattern_result = mock_pattern
        
        # Mock learned decision
        learned_decision = ProviderDecision(
            should_stop=False,
            session_end=None,
            is_valid=True,
            is_shadow=False,
            confidence=0.8
        )
        coord.learned_provider.get_decision = MagicMock(return_value=learned_decision)
        
        dec = coord._evaluate_start_decision(ctx, pred)
        self.assertEqual(dec["start_source"], "learned")

        # 4. None wins when zone pattern is immature
        mock_pattern.confidence = 0.5
        learned_decision = ProviderDecision(
            should_stop=False,
            session_end=None,
            is_valid=False,
            is_shadow=True,
            confidence=0.0
        )
        coord.learned_provider.get_decision = MagicMock(return_value=learned_decision)
        dec = coord._evaluate_start_decision(ctx, pred)
        self.assertEqual(dec["start_source"], "none")

    async def test_h4b_house_fallback_arbitration(self):
        """Test house_fallback arbitration: evening comfort window triggers start without 0.7 gate."""
        entry = MagicMock()
        entry.entry_id = "zone_1"
        entry.options = {CONF_SCHEDULE_ENTITY: "schedule.test"}
        entry.data = {}
        
        with patch("custom_components.preheat.coordinator.PreheatingCoordinator._setup_listeners"), \
             patch("custom_components.preheat.coordinator.PreheatingCoordinator.async_load_data"):
            coord = PreheatingCoordinator(self.hass, entry)
            
        house = HouseArrivalCollector(self.hass)
        coord.house_collector = house
        
        now = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)
        
        # Schedule is invalid (schedule-free zone)
        sched_decision = ProviderDecision(
            should_stop=False,
            session_end=None,
            is_valid=False,
            is_shadow=True,
            confidence=0.0
        )
        coord.schedule_provider.get_decision = MagicMock(return_value=sched_decision)
        
        # Immature learned pattern (no zone-level learned start)
        mock_pattern = MagicMock()
        mock_pattern.confidence = 0.3
        coord.planner.last_pattern_result = mock_pattern
        learned_decision = ProviderDecision(
            should_stop=False, session_end=None,
            is_valid=False, is_shadow=True, confidence=0.0
        )
        coord.learned_provider.get_decision = MagicMock(return_value=learned_decision)
        
        pred = {"predicted_duration": 50.0}
        
        # --- Case 1: Evening fallback active, low confidence -> start_source="house_fallback" ---
        ctx_fallback = {
            "now": now,
            "operative_temp": 18.0,
            "target_setpoint": 21.0,
            "outdoor_temp": 10.0,
            "forecasts": [],
            "has_confident_house": False,
            "has_house_fallback": True,
            "house_confidence": 0.3,
            "house_source": "fallback",
            "house_next_event": now + timedelta(minutes=45),
            "zone_next_event": None,
            "next_event": now + timedelta(minutes=45),
        }
        dec = coord._evaluate_start_decision(ctx_fallback, pred)
        self.assertEqual(dec["start_source"], "house_fallback")
        self.assertTrue(dec["should_start"])
        
        # --- Case 2: No evening window, no fallback -> start_source="none" ---
        ctx_no_fallback = {
            "now": now,
            "operative_temp": 18.0,
            "target_setpoint": 21.0,
            "outdoor_temp": 10.0,
            "forecasts": [],
            "has_confident_house": False,
            "has_house_fallback": False,
            "house_confidence": 0.0,
            "house_source": "none",
            "house_next_event": None,
            "zone_next_event": None,
            "next_event": None,
        }
        dec = coord._evaluate_start_decision(ctx_no_fallback, pred)
        self.assertEqual(dec["start_source"], "none")
        
        # --- Case 3: Schedule valid -> schedule wins over fallback ---
        sched_valid = ProviderDecision(
            should_stop=False, session_end=now + timedelta(hours=3),
            is_valid=True, is_shadow=False, confidence=1.0
        )
        coord.schedule_provider.get_decision = MagicMock(return_value=sched_valid)
        dec = coord._evaluate_start_decision(ctx_fallback, pred)
        self.assertEqual(dec["start_source"], "schedule")
        
        # --- Case 4: Morning confident -> "house" (not "house_fallback") ---
        coord.schedule_provider.get_decision = MagicMock(return_value=sched_decision)
        ctx_morning = {
            "now": now,
            "operative_temp": 18.0,
            "target_setpoint": 21.0,
            "outdoor_temp": 10.0,
            "forecasts": [],
            "has_confident_house": True,
            "has_house_fallback": False,
            "house_confidence": 0.8,
            "house_source": "confident",
            "house_next_event": now + timedelta(minutes=45),
            "zone_next_event": None,
            "next_event": now + timedelta(minutes=45),
        }
        dec = coord._evaluate_start_decision(ctx_morning, pred)
        self.assertEqual(dec["start_source"], "house")

    async def test_h5_bootstrap_aggregation(self):
        """Test H5: Bootstrap pools history from all existing zones and deduplicates correctly."""
        # 1. Setup two existing zone entries
        entry1 = MagicMock()
        entry1.entry_id = "zone_1"
        
        entry2 = MagicMock()
        entry2.entry_id = "zone_2"
        
        self.hass.config_entries.async_entries.return_value = [entry1, entry2]
        
        # 2. Setup mock zone storage data
        zone_1_data = {
            "arrival_history_v2": {
                "999": {
                    "0": [("2026-06-08", 360), ("2026-06-08", 390)]
                }
            }
        }
        zone_2_data = {
            "arrival_history_v2": {
                "999": {
                    "0": [("2026-06-08", 375), ("2026-06-08", 1080)]
                }
            }
        }

        # Mock Store load for each entry
        async def mock_load_store(name):
            if "zone_1" in name:
                return zone_1_data
            if "zone_2" in name:
                return zone_2_data
            return None

        # Helper mock for Store class instantiations
        class MockStoreHelper:
            def __init__(self, hass, version, name):
                self.name = name
            async def async_load(self):
                return await mock_load_store(self.name)
            async def async_save(self, data):
                pass
                
        with patch("custom_components.preheat.house_collector.Store", side_effect=MockStoreHelper):
            house = HouseArrivalCollector(self.hass)
            self.assertFalse(house.bootstrap_done)
            
            await house.async_bootstrap()
            
            self.assertTrue(house.bootstrap_done)
            mon_events = house.history[0]
            self.assertEqual(len(mon_events), 2)
            
            sorted_events = sorted(mon_events, key=lambda x: x[1])
            self.assertEqual(sorted_events[0], (date(2026, 6, 8), 360))
            self.assertEqual(sorted_events[1], (date(2026, 6, 8), 1080))
