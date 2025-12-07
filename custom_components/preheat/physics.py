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
    deadtime: float = 0.0 # V3: Deadtime (Totzeit) in minutes

class ThermalPhysics:
    """Calculates preheat duration and updates model."""

    def __init__(self, data: ThermalModelData | None = None, 
                 profile_data: dict | None = None,
                 learning_rate: float = DEFAULT_LEARNING_RATE) -> None:
        """Initialize with existing data or defaults."""
        self.learning_rate = learning_rate
        
        # Load Defaults from Profile or Constants
        self.min_mass = 1.0
        self.max_mass = 120.0
        initial_mass = DEFAULT_MASS_FACTOR
        initial_deadtime = 0.0
        
        if profile_data:
            self.min_mass = profile_data.get("mass_factor_min", 1.0)
            self.max_mass = profile_data.get("mass_factor_max", 120.0)
            initial_mass = profile_data.get("default_mass", DEFAULT_MASS_FACTOR)
            initial_deadtime = profile_data.get("deadtime", 0.0)

        if data:
            self.mass_factor = data.mass_factor
            self.loss_factor = data.loss_factor
            self.sample_count = data.sample_count
            self.avg_error = getattr(data, "avg_error", 0.0)
            # V3 Migration: Use profile default if deadtime is missing/zero (unless explicitly 0 learned?)
            # Actually, migration should rely on profile default if it was never learned.
            self.deadtime = getattr(data, "deadtime", 0.0)
            if self.deadtime == 0.0 and profile_data and data.sample_count < 5:
                # Assuming new or un-tuned system, apply profile default
                self.deadtime = initial_deadtime
        else:
            self.mass_factor = initial_mass
            self.loss_factor = DEFAULT_LOSS_FACTOR
            self.sample_count = 0
            self.avg_error = 0.0
            self.deadtime = initial_deadtime

    def calculate_duration(self, delta_t_internal: float, delta_t_external: float) -> float:
        """
        Calculate required preheat minutes.
        V3: Duration = Deadtime + (Mass * Delta_In) + (Loss * Delta_Out)
        """
        dt_in = max(0.0, delta_t_internal)
        dt_out = max(0.0, delta_t_external) 

        # Time = Deadtime + (Mass * Delta_In) + (Loss * Delta_Out)
        duration = self.deadtime + (self.mass_factor * dt_in) + (self.loss_factor * dt_out)
        return max(0.0, duration)
        
    def update_deadtime(self, new_deadtime: float) -> None:
        """Update the deadtime parameter (usually from DeadtimeAnalyzer)."""
        # Smooth update? Or direct? Deadtime is physically constant.
        # But measurement is noisy. Let's use EMA.
        if self.deadtime == 0.0:
            self.deadtime = new_deadtime
        else:
            # Slow adaptation for deadtime
            self.deadtime = (0.2 * new_deadtime) + (0.8 * self.deadtime)
            
    def get_confidence(self) -> int:
        """Return confidence score 0-100% based on sample count."""
        if self.sample_count <= 0:
            return 0
        return min(100, int((self.sample_count / 20.0) * 100))

    @property
    def health_score(self) -> int:
        """Return the health score of the model (0-100%)."""
        score = 100
        
        if self.avg_error > 15.0:
            penalty = (self.avg_error - 15.0) * 2.0 
            score -= int(penalty)

        if self.mass_factor < self.min_mass or self.mass_factor > self.max_mass:
            score -= 20
            
        if self.loss_factor > 40.0:
            score -= 10

        return max(0, min(100, score))

    def update_model(self, actual_duration: float, delta_t_in: float, delta_t_out: float, valve_position: float | None = None) -> bool:
        """Update the model based on actual performance."""
        if delta_t_in < 0.2:
            _LOGGER.debug("Skipping learning: Internal DeltaT %.1f too small (Noise)", delta_t_in)
            return False

        if valve_position is not None:
             expected_min = min(15.0, delta_t_in * 2.0)
             if valve_position < expected_min:
                 _LOGGER.debug("Skipping learning: Valve %.1f%% below expected %.1f%%", valve_position, expected_min)
                 return False

        predicted = self.calculate_duration(delta_t_in, delta_t_out)
        error = actual_duration - predicted
        
        abs_error = abs(error)
        self.avg_error = (0.2 * abs_error) + (0.8 * self.avg_error)

        lr = self.learning_rate 
        if delta_t_in < 0.5:
            lr = lr * 0.2 
        
        # In V3, we subtract Deadtime from both Actual and Predicted to balance Mass/Loss
        # effectively we want to correct the "Variable Part".
        # Variable_Actual = Actual - Deadtime
        # Variable_Predicted = Predicted - Deadtime
        # Error is the same.
        
        term_mass = self.mass_factor * delta_t_in
        term_loss = self.loss_factor * delta_t_out
        total_term = term_mass + term_loss + 0.001
        
        weight_mass = term_mass / total_term
        weight_loss = term_loss / total_term
        
        if delta_t_in > 0.1:
            self.mass_factor += lr * (error * weight_mass) / delta_t_in
        
        if delta_t_out > 1.0: 
            self.loss_factor += lr * (error * weight_loss) / delta_t_out

        # V3 Constraints (Dynamic based on Profile)
        self.mass_factor = max(self.min_mass, min(self.max_mass, self.mass_factor))
        self.loss_factor = max(0.0, min(50.0, self.loss_factor))
        
        self.sample_count += 1
        return True

    def to_dict(self) -> dict:
        """Export data."""
        return {
            "mass_factor": self.mass_factor,
            "loss_factor": self.loss_factor,
            "sample_count": self.sample_count,
            "avg_error": self.avg_error,
            "deadtime": self.deadtime
        }
