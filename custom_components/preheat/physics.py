"""Physics module for intelligent preheating."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .const import (
    DEFAULT_MASS_FACTOR,
    DEFAULT_LOSS_FACTOR,
    DEFAULT_LEARNING_RATE
)

_LOGGER = logging.getLogger(__name__)

@dataclass
class ThermalModelData:
    """Holds the learned parameters."""
    mass_factor: float # Minutes to raise 1°C internally
    loss_factor: float # Additional minutes per 1°C difference to outside
    sample_count: int
    avg_error: float = 0.0 # Exponential Moving Average of absolute error used for quality metric

class ThermalPhysics:
    """Calculates preheat duration and updates model."""

    def __init__(self, data: ThermalModelData | None = None, 
                 initial_mass: float = DEFAULT_MASS_FACTOR,
                 initial_loss: float = DEFAULT_LOSS_FACTOR,
                 learning_rate: float = DEFAULT_LEARNING_RATE) -> None:
        """Initialize with existing data or defaults."""
        self.learning_rate = learning_rate
        if data:
            self.mass_factor = data.mass_factor
            self.loss_factor = data.loss_factor
            self.sample_count = data.sample_count
            self.avg_error = getattr(data, "avg_error", 0.0) # Handle migration implicitly
        else:
            self.mass_factor = initial_mass
            self.loss_factor = initial_loss
            self.sample_count = 0
            self.avg_error = 0.0

    def calculate_duration(self, delta_t_internal: float, delta_t_external: float) -> float:
        """
        Calculate required preheat minutes.
        delta_t_internal: Target - Current Indoor (K)
        delta_t_external: Target - Current Outdoor (K) (Positive implies colder outside)
        """
        dt_in = max(0.0, delta_t_internal)
        dt_out = max(0.0, delta_t_external) # If hotter outside, loss is 0 (or gain, but we ignore cooling)

        # Basic formula: 
        # Time = (Mass * Delta_In) + (Loss * Delta_Out)
        
        duration = (self.mass_factor * dt_in) + (self.loss_factor * dt_out)
        return max(0.0, duration)

    def get_confidence(self) -> int:
        """Return confidence score 0-100% based on sample count."""
        # Simple heuristic: 20 samples = 100% confidence for Beta
        if self.sample_count <= 0:
            return 0
        return min(100, int((self.sample_count / 20.0) * 100))

    @property
    def health_score(self) -> int:
        """
        Return the health score of the model (0-100%).
        Based on:
        1. Average Error (lower is better): < 5 min = 100%
        2. Parameter Drift: Mass factor within bounds
        """
        score = 100
        
        # Penalize High Error
        # Error 5m -> 0 penalty
        # Error 15m -> 20 penalty
        # Error 30m -> 50 penalty
        if self.avg_error > 5.0:
            penalty = (self.avg_error - 5.0) * 2.0 
            score -= int(penalty)

        # Penalize Extreme Mass Factor (Potential Model Failure)
        if self.mass_factor < 5.0 or self.mass_factor > 100.0:
            score -= 20
            
        # Penalize Extreme Loss Factor
        if self.loss_factor > 40.0:
            score -= 10

        return max(0, min(100, score))

    def update_model(self, actual_duration: float, delta_t_in: float, delta_t_out: float, valve_position: float | None = None) -> bool:
        """
        Update the model based on actual performance.
        actual_duration: Minutes it took to reach target.
        delta_t_in: Temperature rise required (Start to Target).
        delta_t_out: Average outdoor delta during this period.
        """
        if delta_t_in < 0.2:
            _LOGGER.debug("Skipping learning: Internal DeltaT %.1f too small (Noise)", delta_t_in)
            return False

        # Smart Valve Check
        # If valve is very low, it might be due to low native power limits, not room physics.
        # But for floor heating, 15% valve might be normal for keeping temp.
        # Heuristic: If we needed a large rise (>1K) but valve was < 10%, that's suspicious.
        # If we needed small rise (0.5K), valve 8% is fine.
        if valve_position is not None:
             expected_min = min(15.0, delta_t_in * 2.0)
             if valve_position < expected_min:
                 _LOGGER.debug("Skipping learning: Valve %.1f%% below expected %.1f%% for %.1fK rise", 
                               valve_position, expected_min, delta_t_in)
                 return False

        predicted = self.calculate_duration(delta_t_in, delta_t_out)
        error = actual_duration - predicted
        
        # Track Error Metric
        abs_error = abs(error)
        # Updates avg_error with same alpha as learning rate (or fixed 0.1)
        # Use a slightly faster alpha for error tracking to reflect recent performance
        self.avg_error = (0.2 * abs_error) + (0.8 * self.avg_error)

        # ... (heuristic blocks remain same) ...

        # Use configured rate
        lr = self.learning_rate 
        if delta_t_in < 0.5:
            lr = lr * 0.2 # Be very careful with small deltas
        
        # Determine weight attribution
        # total_input = Mass_Term + Loss_Term
        # We distribute the error correction proportionally to the magnitude of influence
        
        term_mass = self.mass_factor * delta_t_in
        term_loss = self.loss_factor * delta_t_out
        total_term = term_mass + term_loss + 0.001
        
        weight_mass = term_mass / total_term
        weight_loss = term_loss / total_term
        
        # Update
        # If Actual > Predicted (Error > 0), we need to INCREASE factors.
        # New_Mass = Old_Mass + LR * (Error * Weight / Delta_In)
        
        if delta_t_in > 0.1:
            self.mass_factor += lr * (error * weight_mass) / delta_t_in
        
        if delta_t_out > 1.0: # Only update loss if there was actually a temperature diff
            self.loss_factor += lr * (error * weight_loss) / delta_t_out

        # Constraints
        self.mass_factor = max(1.0, min(120.0, self.mass_factor))
        self.loss_factor = max(0.0, min(50.0, self.loss_factor))
        
        self.sample_count += 1
        return True

    def to_dict(self) -> dict:
        """Export data."""
        return {
            "mass_factor": self.mass_factor,
            "loss_factor": self.loss_factor,
            "sample_count": self.sample_count,
            "avg_error": self.avg_error
        }
