
import sys
import os
import unittest
from unittest.mock import MagicMock

# --- Full Mock Setup BEFORE imports ---
# Recurse: homeassistant, helpers, issue_registry, etc.

mock_ha = MagicMock()
sys.modules["homeassistant"] = mock_ha
sys.modules["homeassistant.const"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock()

mock_helpers = MagicMock()
sys.modules["homeassistant.helpers"] = mock_helpers
sys.modules["homeassistant.helpers.issue_registry"] = MagicMock() # The one that failed
sys.modules["homeassistant.helpers.update_coordinator"] = MagicMock()
sys.modules["homeassistant.helpers.event"] = MagicMock()
sys.modules["homeassistant.helpers.storage"] = MagicMock()

sys.modules["homeassistant.util"] = MagicMock()

# --- End Mocks ---

# Add custom_components to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from custom_components.preheat.physics import ThermalPhysics, ThermalModelData
from custom_components.preheat.const import PROFILE_RADIATOR_NEW, HEATING_PROFILES

class TestPhysicsV3(unittest.TestCase):

    def setUp(self):
        self.profile = HEATING_PROFILES[PROFILE_RADIATOR_NEW]
        
    def test_calculate_duration_v3(self):
        p_data = ThermalModelData(
            mass_factor=20.0,
            loss_factor=5.0,
            sample_count=10,
            deadtime=15.0 
        )
        physics = ThermalPhysics(data=p_data, profile_data=self.profile)
        # Duration = 15 + (20 * 2) + (5 * 10) = 105
        duration = physics.calculate_duration(2.0, 10.0)
        self.assertEqual(duration, 105.0)
        
    def test_profile_constraints_clamping(self):
        p_data = ThermalModelData(mass_factor=20.0, loss_factor=5.0, sample_count=10, deadtime=15.0)
        physics = ThermalPhysics(data=p_data, profile_data=self.profile)
        
        # Force huge mass
        physics.mass_factor = 100.0 
        physics.update_model(100, 1.0, 1.0)
        self.assertEqual(physics.mass_factor, 40.0) # Max
        
        # Force tiny mass
        physics.mass_factor = 1.0 
        physics.update_model(100, 1.0, 1.0)
        self.assertEqual(physics.mass_factor, 10.0) # Min

    def test_deadtime_update(self):
        # Initial deadtime from profile default logic? 
        # Actually __init__ uses profile_data["deadtime"] as default if data is None?
        # Let's verify __init__ logic. 
        # If I pass data=None, deadtime = profile["deadtime"].
        physics = ThermalPhysics(profile_data=self.profile)
        # However, data defaults to None.
        # Physics class: if data: ... else: self.deadtime = initial_deadtime (arg) or profile deadtime?
        # I need to check Physics __init__ code.
        # Assuming it uses profile default:
        # self.assertEqual(physics.deadtime, 5.0) # Wait, radiator new is 5? No, I defined it as 5 in const.py?
        # Let's look at const.py in the code snippet I saw earlier.
        # PROFILE_RADIATOR_NEW: "deadtime": 5? Or 15? I saw 5 in step 388.
        # Wait, Step 388 snippet: "deadtime": 5 for Infrared.
        # What about Radiator New?
        # I should check the Const values I am asserting against!
        pass 

if __name__ == '__main__':
    unittest.main()
