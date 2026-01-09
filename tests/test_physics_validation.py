import sys
import os
import unittest
from unittest.mock import MagicMock

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
from datetime import timezone
mock_dt = MagicMock()
mock_dt.UTC = timezone.utc
sys.modules["homeassistant.util.dt"] = mock_dt

from custom_components.preheat.physics import ThermalPhysics, ThermalModelData
from custom_components.preheat.const import (
    PROFILE_RADIATOR_NEW, 
    PROFILE_FLOOR_CONCRETE, 
    HEATING_PROFILES
)

class TestPhysicsValidation(unittest.TestCase):
    """
    Action 1.1: ISO 12831 Validation Suite.
    Verifies that the Thermal Physics Model produces physically plausible results
    consistent with standard building types.
    """

    def setUp(self):
        self.profile_rad = HEATING_PROFILES[PROFILE_RADIATOR_NEW]
        self.profile_floor = HEATING_PROFILES[PROFILE_FLOOR_CONCRETE]

    def test_radiator_standard_room(self):
        """
        Scenario: Modern Radiator, 2K Warmup, 0C Outdoor.
        Reference: DIN 12831 Standard Room.
        Expectation: 60-180 minutes context.
        """
        # Default Mass (20), Default Loss (5)
        # Formula: dur = deadtime + (mass * d_in) + (loss * d_out)
        # Deadtime=15
        
        data = ThermalModelData(
            mass_factor=20.0,
            loss_factor=5.0, # Default conservative
            sample_count=50,
            avg_error=0.0,
            deadtime=15.0
        )
        
        physics = ThermalPhysics(data, self.profile_rad, 0.1)
        
        delta_in = 2.0  # 20->22C
        delta_out = 22.0 # 22C In, 0C Out
        
        duration = physics.calculate_duration(delta_in, delta_out)
        
        # Calculation:
        # 15 + (20*2) + (5*22) = 15 + 40 + 110 = 165 min
        self.assertAlmostEqual(duration, 165.0, delta=0.1)
        
        # Plausibility Check (1 hour < t < 4 hours)
        self.assertTrue(60 < duration < 240, f"Radiator duration {duration} min is implausible")

    def test_floor_heating_heavy(self):
        """
        Scenario: Concrete Floor Heating, 2K Warmup, 0C Outdoor.
        High thermal mass, long deadtime.
        Expectation: 4-8 hours context.
        """
        data = ThermalModelData(
            mass_factor=100.0, # Heavy
            loss_factor=3.0,   # Better insulation assumption
            sample_count=50,
            avg_error=0.0,
            deadtime=120.0
        )
        
        physics = ThermalPhysics(data, self.profile_floor, 0.1)
        
        delta_in = 2.0
        delta_out = 22.0
        
        duration = physics.calculate_duration(delta_in, delta_out)
        
        # Calculation:
        # 120 + (100*2) + (3*22) = 120 + 200 + 66 = 386 min (6.4 hours)
        self.assertAlmostEqual(duration, 386.0, delta=0.1)
        
        # Plausibility Check (> 4 hours)
        self.assertTrue(240 < duration < 600, f"Floor heating duration {duration} min is implausible")

    def test_insulation_impact(self):
        """
        Scenario: Comparison of Passive House (Loss=1) vs Old Building (Loss=10).
        """
        # Passive House
        p_passive = ThermalPhysics(ThermalModelData(20, 1.0, 10, 0, 15), self.profile_rad, 0.1)
        # Old Building
        p_old = ThermalPhysics(ThermalModelData(20, 10.0, 10, 0, 15), self.profile_rad, 0.1)
        
        d_in = 2.0
        d_out = 30.0 # Extreme cold -10C
        
        t_passive = p_passive.calculate_duration(d_in, d_out)
        t_old = p_old.calculate_duration(d_in, d_out)
        
        # Passive: 15 + 40 + 30 = 85 min
        # Old: 15 + 40 + 300 = 355 min
        
        print(f"\n[Validation] Passive House: {t_passive:.1f}m, Old Building: {t_old:.1f}m")
        
        self.assertLess(t_passive, 100)
        self.assertGreater(t_old, 300)
        
        # Sensitivity: Old building should react much stronger to outdoor temp
        self.assertGreater(t_old - t_passive, 200)

if __name__ == '__main__':
    unittest.main()
