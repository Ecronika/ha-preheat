
import unittest
from custom_components.preheat.physics import ThermalPhysics, ThermalModelData

class TestPhysicsV26(unittest.TestCase):
    """Test v2.6.0 specific improvements."""

    def setUp(self):
        self.p_data = ThermalModelData(
            mass_factor=10.0,
            loss_factor=5.0,
            sample_count=10,
            avg_error=1.0,
            deadtime=0.0
        )
        self.physics = ThermalPhysics(data=self.p_data)

    def test_dynamic_loss_scaling_small_lift(self):
        """Test that small temperature lifts have reduced loss impact."""
        # Scenario: Delta In = 0.5K (Small). Delta Out = 10K (Cold).
        # Loss Scaler = 0.5 / 2.0 = 0.25 (25% of Loss)
        # Duration = Mass*0.5 + Loss*10*0.25 = 5 + 5*2.5 = 17.5 min
        # Legacy would be: 5 + 5*10 = 55 min (Too high)
        
        duration = self.physics.calculate_duration(0.5, 10.0)
        
        # Expect ~17.5
        self.assertAlmostEqual(duration, 17.5, delta=0.5)
        self.assertLess(duration, 30.0, "Small lift should not trigger massive cold penalty")

    def test_dynamic_loss_scaling_standard_lift(self):
        """Test that standard 2.0K lift has 100% loss impact."""
        # Scenario: Delta In = 2.0K. Delta Out = 10K.
        # Loss Scaler = 2.0 / 2.0 = 1.0 (100%)
        # Duration = 10*2 + 5*10*1 = 20 + 50 = 70 min
        
        duration = self.physics.calculate_duration(2.0, 10.0)
        self.assertAlmostEqual(duration, 70.0, delta=0.1)

    def test_warm_room_zero_duration(self):
        """Test that already warm room returns 0 duration."""
        # Delta In negative or zero
        self.assertEqual(self.physics.calculate_duration(0.0, 10.0), 0.0)
        self.assertEqual(self.physics.calculate_duration(-0.5, 10.0), 0.0)

    def test_null_input_resilience(self):
        """Test that None values in data explicitly fall back to defaults (Ref v2.6.0-beta18)."""
        # Create a corrupted data object (simulating JSON nulls)
        # Note: We must bypass type hints to simulate runtime corruption
        corrupted_data = unittest.mock.MagicMock()
        corrupted_data.mass_factor = None
        corrupted_data.loss_factor = None
        corrupted_data.sample_count = 0
        corrupted_data.avg_error = None
        corrupted_data.deadtime = None
        
        # Init Physics with corrupted data
        p = ThermalPhysics(data=corrupted_data)
        
        # Verify defaults applied
        self.assertEqual(p.mass_factor, 10.0) # Default Mass
        self.assertEqual(p.loss_factor, 5.0)  # Default Loss
        self.assertEqual(p.avg_error, 0.0)
        self.assertEqual(p.deadtime, 0.0)
        
        # Verify simple calculation works without crashing
        dur = p.calculate_duration(1.0, 10.0)
        # 10*1 + 5*10*(1/2) = 10 + 25 = 35
        self.assertAlmostEqual(dur, 35.0, delta=0.1)

