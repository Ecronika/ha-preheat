"""
Standalone Test Script for Preheat Physics Model (v2.0.0)
Run this script to verify the learning logic independently of Home Assistant.
Usage: python3 tests/test_physics.py
"""
import sys
import os
import logging

# Add parent dir to path to allow importing custom_components
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# MOCK Home Assistant modules to allow importing package without HA installed
from unittest.mock import MagicMock
sys.modules["homeassistant"] = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock()
sys.modules["homeassistant.const"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.helpers.update_coordinator"] = MagicMock()
sys.modules["homeassistant.helpers.event"] = MagicMock()
sys.modules["homeassistant.helpers.storage"] = MagicMock()
sys.modules["homeassistant.helpers.issue_registry"] = MagicMock() # Added
sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.sensor"] = MagicMock()
sys.modules["homeassistant.components.switch"] = MagicMock()
sys.modules["homeassistant.components.button"] = MagicMock()
sys.modules["homeassistant.exceptions"] = MagicMock()
sys.modules["homeassistant.loader"] = MagicMock()
sys.modules["homeassistant.util"] = MagicMock()
sys.modules["homeassistant.util.dt"] = MagicMock() # Often imported as dt_util

# Mock entire package to avoid __init__ execution if possible? 
# No, __init__ runs. But now it will succeed importing mocks.

# Mocking consts since we aren't in HA
from custom_components.preheat.physics import ThermalPhysics, ThermalModelData
from custom_components.preheat.const import DEFAULT_MASS_FACTOR, DEFAULT_LOSS_FACTOR

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
_LOGGER = logging.getLogger(__name__)

def test_initialization():
    _LOGGER.info("--- Test 1: Initialization ---")
    p = ThermalPhysics()
    assert p.mass_factor == DEFAULT_MASS_FACTOR
    assert p.loss_factor == DEFAULT_LOSS_FACTOR
    assert p.sample_count == 0
    _LOGGER.info("✅ Defaults correct.")

def test_calculation():
    _LOGGER.info("--- Test 2: Duration Calculation ---")
    p = ThermalPhysics()
    # Assume 10 min/K, 5 min/K loss
    # Case A: 2K rise, 0K loss -> 20 mins
    dur = p.calculate_duration(2.0, 0.0)
    assert abs(dur - 20.0) < 0.1, f"Expected 20.0, got {dur}"
    
    # Case B: 2K rise, 10K outdoor diff -> 20 + 50 = 70 mins
    dur = p.calculate_duration(2.0, 10.0)
    assert abs(dur - 70.0) < 0.1, f"Expected 70.0, got {dur}"
    _LOGGER.info("✅ Calculations correct.")

def test_learning_perfect_match():
    _LOGGER.info("--- Test 3: Learning (Perfect Match) ---")
    p = ThermalPhysics()
    # Predicted: 20 mins (2K * 10). Actual: 20 mins.
    # Should be no change.
    updated = p.update_model(20.0, 2.0, 0.0)
    assert updated is True
    assert abs(p.mass_factor - 10.0) < 0.01
    _LOGGER.info("✅ No drift on perfect match.")

def test_learning_too_slow():
    _LOGGER.info("--- Test 4: Learning (Room too slow) ---")
    p = ThermalPhysics()
    # Scenario: We thought 2K takes 20 mins.
    # Reality: It took 40 mins! (Room is heavy/slow)
    # Error = +20 mins.
    # We expect Mass Factor to INCREASE.
    
    initial_mass = p.mass_factor
    p.update_model(40.0, 2.0, 0.0)
    
    _LOGGER.info(f"Mass Factor: {initial_mass} -> {p.mass_factor}")
    assert p.mass_factor > initial_mass
    _LOGGER.info("✅ Model adapted (Mass Factor increased).")

def test_learning_high_loss():
    _LOGGER.info("--- Test 5: Learning (Bad Insulation) ---")
    p = ThermalPhysics()
    # Scenario: 2K rise, but it's freezing outside (Delta Out 20K).
    # Predicted: (10*2) + (5*20) = 20 + 100 = 120 mins.
    # Reality: It took 150 mins!
    # Error = 30 mins.
    # Since outdoor delta is HIGH, we should attribute error to Loss Factor too.
    
    initial_loss = p.loss_factor
    p.update_model(150.0, 2.0, 20.0)
    
    _LOGGER.info(f"Loss Factor: {initial_loss} -> {p.loss_factor}")
    assert p.loss_factor > initial_loss
    _LOGGER.info("✅ Model adapted (Loss Factor increased).")

def test_noise_filtering():
    _LOGGER.info("--- Test 6: Noise Filtering ---")
    p = ThermalPhysics()
    start_samples = p.sample_count
    
    # Tiny delta (0.1K) -> Should be ignored
    updated = p.update_model(100.0, 0.1, 0.0)
    assert updated is False
    assert p.sample_count == start_samples
    _LOGGER.info("✅ Small delta correctly ignored.")

    # Valve closed (<10%) -> Should be ignored if Delta is large
    # Delta 5.0 -> Expected min = min(15, 10.0) = 10.0
    updated = p.update_model(100.0, 5.0, 0.0, valve_position=5.0)
    assert updated is False
    _LOGGER.info("✅ Low valve correctly ignored for large delta.")

    # Smart Valve Logic: Low valve (5%) OK if Delta is small (1.0K)
    # Delta 1.0 -> Expected min = min(15, 2.0) = 2.0
    updated = p.update_model(10.0, 1.0, 0.0, valve_position=5.0)
    assert updated is True
    _LOGGER.info("✅ Low valve accepted for small delta (Smart Logic).")

    # Manual Stop (Valid) -> Should be learned
    # Delta 2.0K, Valve 50%
    updated = p.update_model(30.0, 2.0, 0.0, valve_position=50.0)
    assert updated is True
    _LOGGER.info("✅ Valid manual stop accepted.")

def test_confidence_and_error():
    _LOGGER.info("--- Test 7: Confidence & Error Metrics ---")
    p = ThermalPhysics()
    assert p.get_confidence() == 0
    assert p.avg_error == 0.0
    
    # Update 1: Perfect match
    p.update_model(20.0, 2.0, 0.0) # Predicted 20
    assert p.sample_count == 1
    assert p.get_confidence() == 5 # 1/20 * 100
    assert p.avg_error == 0.0
    
    # Update 2: Error 10 mins
    # Predicted 20, Actual 30. Error = 10.
    # Avg Error = 0.2 * 10 + 0.8 * 0 = 2.0
    p.update_model(30.0, 2.0, 0.0) 
    assert abs(p.avg_error - 2.0) < 0.1
    assert p.get_confidence() == 10 # 2/20 * 100
    
    _LOGGER.info("✅ Confidence and Avg Error tracking correct.")

if __name__ == "__main__":
    _LOGGER.info("🚀 Starting Physics Verification (v2.1)...")
    try:
        test_initialization()
        test_calculation()
        test_learning_perfect_match()
        test_learning_too_slow()
        test_learning_high_loss()
        test_noise_filtering()
        test_confidence_and_error()
        _LOGGER.info("\n🎉 ALL TESTS PASSED! Physics Engine v2.1 is solid.")
    except AssertionError as e:
        _LOGGER.error(f"❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        _LOGGER.exception("❌ UNEXPECTED ERROR")
        sys.exit(1)
