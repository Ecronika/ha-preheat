"""
Consolidated Unit Tests for Preheat Physics Model.
Includes tests for v2.0 logic, v2.7.1 stability fixes, and v3.0 profile constraints.
"""
import sys
import os
import unittest
import logging
from unittest.mock import MagicMock

# Add parent dir to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# --- MOCK Home Assistant ---
mock_ha = MagicMock()
sys.modules["homeassistant"] = mock_ha
sys.modules["homeassistant.config_entries"] = MagicMock()
sys.modules["homeassistant.const"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.helpers.update_coordinator"] = MagicMock()
sys.modules["homeassistant.helpers.event"] = MagicMock()
sys.modules["homeassistant.helpers.storage"] = MagicMock()
sys.modules["homeassistant.helpers.issue_registry"] = MagicMock()
sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.exceptions"] = MagicMock()
sys.modules["homeassistant.util"] = MagicMock()
sys.modules["homeassistant.util.dt"] = MagicMock()

from custom_components.preheat.physics import ThermalPhysics, ThermalModelData
from custom_components.preheat.const import (
    DEFAULT_MASS_FACTOR, 
    DEFAULT_LOSS_FACTOR,
    PROFILE_RADIATOR_NEW, 
    HEATING_PROFILES
)

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
_LOGGER = logging.getLogger(__name__)

class TestPhysics(unittest.TestCase):
    """Main Physics Test Suite."""

    def setUp(self):
        self.p_data = ThermalModelData(
            mass_factor=10.0,
            loss_factor=5.0,
            sample_count=10,
            avg_error=1.0,
            deadtime=0.0
        )
        self.physics = ThermalPhysics(data=self.p_data)

    def test_initialization(self):
        """Verify default values."""
        p = ThermalPhysics()
        self.assertEqual(p.mass_factor, DEFAULT_MASS_FACTOR)
        self.assertEqual(p.loss_factor, DEFAULT_LOSS_FACTOR)
        self.assertEqual(p.sample_count, 0)

    def test_calculation_basics(self):
        """Verify basic Formula: Duration = Deadtime + Mass*dIn + Loss*dOut."""
        p = ThermalPhysics()
        # Assume 10 min/K, 5 min/K loss
        # Case A: 2K rise, 0K loss -> 20 mins
        dur = p.calculate_duration(2.0, 0.0)
        self.assertAlmostEqual(dur, 20.0, delta=0.1)
        
        # Case B: 2K rise, 10K outdoor diff -> 20 + 50 = 70 mins
        dur = p.calculate_duration(2.0, 10.0)
        self.assertAlmostEqual(dur, 70.0, delta=0.1)

    def test_learning_perfect_match(self):
        """Verify no change if prediction matches actual."""
        p = ThermalPhysics()
        # Predicted: 20 mins (2K * 10). Actual: 20 mins.
        updated = p.update_model(20.0, 2.0, 0.0)
        self.assertTrue(updated)
        self.assertAlmostEqual(p.mass_factor, 10.0, delta=0.01)

    def test_learning_too_slow(self):
        """Verify adaptation when room heats slower than expected."""
        p = ThermalPhysics()
        initial_mass = p.mass_factor
        # Predicted 20, Actual 40 -> Undershot -> Increase Mass
        p.update_model(40.0, 2.0, 0.0)
        self.assertGreater(p.mass_factor, initial_mass)

    def test_learning_high_loss(self):
        """Verify adaptation when outdoor loss is high."""
        p = ThermalPhysics()
        initial_loss = p.loss_factor
        # Predicted 120, Actual 150 -> Undershot -> Increase Loss
        p.update_model(150.0, 2.0, 20.0)
        self.assertGreater(p.loss_factor, initial_loss)

    def test_noise_filtering(self):
        """Verify filters for small deltas and valve positions."""
        p = ThermalPhysics()
        start_samples = p.sample_count
        
        # Tiny delta (0.1K) -> Should be ignored
        updated = p.update_model(100.0, 0.1, 0.0)
        self.assertFalse(updated)
        self.assertEqual(p.sample_count, start_samples)

        # Valve closed (<10%) -> Should be ignored if Delta is large
        updated = p.update_model(100.0, 5.0, 0.0, valve_position=5.0)
        self.assertFalse(updated)

        # Smart Valve Logic: Low valve (5%) OK if Delta is small (1.0K)
        updated = p.update_model(10.0, 1.0, 0.0, valve_position=5.0)
        self.assertTrue(updated)

    def test_linear_scaling_small_lift(self):
        """Test that loss scaling is LINEAR (v2.7.1 update)."""
        # Scenario: Delta In = 0.5K (Small). Delta Out = 10K (Cold).
        # Old V2.6: Loss Scaler = 0.5 / 2.0 = 0.25 -> 17.5 min
        # New V2.7: Linear = Mass*0.5 + Loss*10 = 5 + 50 = 55.0 min
        # The scaler artifact was removed for physical correctness.
        p = ThermalPhysics() 
        # Defaults: Mass 10, Loss 5
        duration = p.calculate_duration(0.5, 10.0)
        self.assertAlmostEqual(duration, 55.0, delta=0.5)

    def test_null_input_resilience(self):
        """Test that None values in data explicitly fall back to defaults."""
        corrupted_data = unittest.mock.MagicMock()
        corrupted_data.mass_factor = None
        corrupted_data.loss_factor = None
        corrupted_data.sample_count = 0
        corrupted_data.avg_error = None
        corrupted_data.deadtime = None
        
        p = ThermalPhysics(data=corrupted_data)
        
        self.assertEqual(p.mass_factor, 10.0)
        self.assertEqual(p.loss_factor, 5.0)
        self.assertEqual(p.avg_error, 0.0)
        self.assertEqual(p.deadtime, 0.0)

    def test_profile_constraints_clamping(self):
        """Verify V3 Profile constraints."""
        profile = HEATING_PROFILES[PROFILE_RADIATOR_NEW]
        p_data = ThermalModelData(mass_factor=20.0, loss_factor=5.0, sample_count=10, deadtime=15.0)
        physics = ThermalPhysics(data=p_data, profile_data=profile)
        
        # Force huge mass
        physics.mass_factor = 100.0 
        physics.update_model(100, 1.0, 1.0)
        self.assertEqual(physics.mass_factor, 40.0) # Max for Radiator New
        
        # Force tiny mass
        physics.mass_factor = 1.0 
        physics.update_model(100, 1.0, 1.0)
        self.assertEqual(physics.mass_factor, 10.0) # Min for Radiator New

    def test_stability_hotfix_v271(self):
        """Verify v2.7.1 stability fixes (Dual Clipping & Weak Signal)."""
        # Test 1: Small delta_t_in doesn't explode
        phys = ThermalPhysics()
        phys.mass_factor = 20.0
        phys.loss_factor = 5.0
        
        # Simulate maintenance heating (small delta, noisy)
        for _ in range(50):
            phys.update_model(
                actual_duration=15.0,
                delta_t_in=0.6,  # Just above 0.5 threshold
                delta_t_out=10.0,
                valve_position=50.0
            )
        
        # Check bounds
        self.assertGreater(phys.mass_factor, 10.0)
        self.assertLess(phys.mass_factor, 50.0)
        self.assertGreater(phys.loss_factor, 1.0)
        self.assertLess(phys.loss_factor, 20.0)

        # Test 2: Zero/Small outdoor delta (Summer/Warm day)
        phys.loss_factor = 5.0
        phys.update_model(
            actual_duration=20.0,
            delta_t_in=2.0,
            delta_t_out=0.1,  # Below threshold
            valve_position=80.0
        )
        # Loss should NOT have updated matching 5.0
        self.assertAlmostEqual(phys.loss_factor, 5.0, delta=0.01)

        # Test 3: Weak Signal (0.1 < dt_out < 0.5)
        # Logic: Update allowed but dampened
        phys.loss_factor = 5.0
        phys.update_model(
            actual_duration=25.0,
            delta_t_in=2.0,
            delta_t_out=0.3, # Weak Signal range
            valve_position=80.0
        )
        self.assertNotEqual(phys.loss_factor, 5.0)
        self.assertTrue(5.0 < phys.loss_factor < 6.0)

    def test_linearity_check(self):
        """Verify No scaler artifact (Linearity Check)."""
        phys = ThermalPhysics()
        phys.deadtime = 10.0
        phys.mass_factor = 10.0
        phys.loss_factor = 2.0
        
        # Case A: Lift 2K, Outside Delta 10K
        d1 = phys.calculate_duration(2.0, 10.0)
        # 10 + 20 + 20 = 50
        
        # Case B: Lift 4K, Outside Delta 10K
        d2 = phys.calculate_duration(4.0, 10.0)
        # 10 + 40 + 20 = 70
        
        self.assertAlmostEqual(d1, 50.0, delta=0.1)
        self.assertAlmostEqual(d2, 70.0, delta=0.1)
        
        # Pure heating part should double
        heat_1 = d1 - 10.0 - 20.0 # 20
        heat_2 = d2 - 10.0 - 20.0 # 40
        self.assertAlmostEqual(heat_2 / heat_1, 2.0, delta=0.05)

if __name__ == '__main__':
    unittest.main()
