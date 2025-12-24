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
    """
    V2 Physics Model (Updated v2.7.1)
    
    Model: duration = deadtime + (mass * delta_t_in) + (loss * delta_t_out)
    
    Parameters:
        mass_factor (float): Minutes to raise 1K internally [min/K]
            - Represents thermal capacity of room + furnishings
            - Typical: 10-40 for radiators, 50-120 for floor heating
        
        loss_factor (float): Additional minutes per 1K outdoor delta [min/K]
            - Represents transmission losses through envelope
            - Physical: Inverse of (UA / Power) normalized to temp lift
            - Typical: 2-10 depending on insulation quality
            - V2 change: Previously scaled by (delta_t_in/2), now linear.
            - Migration: Old values are automatically reset to profile defaults.
        
        deadtime (float): System lag before heat reaches room [min]
            - Radiator inertia + valve response + piping delay
            - Typical: 5-15 min (radiators), 45-120 min (floor)
            
    Example:
        # Radiator system, 2K lift, 10K outdoor delta:
        # duration = 15 (deadtime) + 20*2 (mass) + 5*10 (loss) = 105 min
    """

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
            self.mass_factor = data.mass_factor if data.mass_factor is not None else initial_mass
            self.loss_factor = data.loss_factor if data.loss_factor is not None else DEFAULT_LOSS_FACTOR
            self.sample_count = data.sample_count
            
            # Sanitize Avg Error and Deadtime (getattr returns None if attr is None!)
            d_err = getattr(data, "avg_error", 0.0)
            self.avg_error = d_err if d_err is not None else 0.0
            
            d_time = getattr(data, "deadtime", 0.0)
            self.deadtime = d_time if d_time is not None else 0.0
            
            # V3 Migration logic:
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
        V3 Refined (v2.7.1 Fix): Duration = Deadtime + (Mass * Delta_In) + (Loss * Delta_Out)
        Removed incorrect loss_scaler (dt_in/2.0) causing physical inconsistency.
        """
        # 1. If we are already at or above target, no preheat needed.
        if delta_t_internal <= 0:
            return 0.0
            
        dt_in = delta_t_internal
        dt_out = max(0.0, delta_t_external) 

        # Time = Deadtime + (Mass * Delta_In) + (Loss * Delta_Out)
        duration = self.deadtime + (self.mass_factor * dt_in) + (self.loss_factor * dt_out)
        return max(0.0, duration)
    
    def update_deadtime(self, new_deadtime: float) -> None:
        """Update the deadtime parameter (usually from DeadtimeAnalyzer)."""
        # Apply EMA smoothing to deadtime updates to reject measurement noise.
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
        # 1. Reject Noise (Input Guard)
        if delta_t_in < 0.3:
            _LOGGER.debug("Skipping learning: Internal DeltaT %.1f too small (Noise)", delta_t_in)
            return False

        if valve_position is not None:
             expected_min = min(15.0, delta_t_in * 5.0) # V2.7.1: Relaxed from 2.0 to 5.0 check
             if valve_position < expected_min:
                 _LOGGER.debug("Skipping learning: Valve %.1f%% below expected %.1f%%", valve_position, expected_min)
                 return False

        predicted = self.calculate_duration(delta_t_in, delta_t_out)
        error = actual_duration - predicted
        
        abs_error = abs(error)
        self.avg_error = (0.2 * abs_error) + (0.8 * self.avg_error)

        # 2. Learning Rate Scheduling
        lr = self.learning_rate 
        if delta_t_in < 0.8:
            # Dampen learning for small maintenace heating (0.3 - 0.8K)
            lr = lr * 0.2 # V2.7.1: Increased from 0.1 to 0.2 to allow slow convergence
        
        # 3. Calculate Weighting
        term_mass = self.mass_factor * delta_t_in
        term_loss = self.loss_factor * delta_t_out
        total_term = term_mass + term_loss + 0.001
        
        weight_mass = term_mass / total_term
        weight_loss = term_loss / total_term
        
        # 4. Calculate Deltas
        
        # Mass connects to Delta_In
        delta_mass = lr * (error * weight_mass) / delta_t_in
        delta_mass = self._clip_dual(delta_mass, self.mass_factor, 0.05, 5.0)
        self.mass_factor += delta_mass

        # Loss connects to Delta_Out
        # GUARD: Only learn loss if significant outdoor delta exists to avoid division by zero/noise
        if delta_t_out > 0.5: 
            # Strong Signal
            delta_loss = lr * (error * weight_loss) / delta_t_out
            delta_loss = self._clip_dual(delta_loss, self.loss_factor, 0.05, 2.0)
            self.loss_factor += delta_loss
        elif delta_t_out > 0.1:
            # Weak Signal (0.1 < dt_out < 0.5) - e.g. mild spring/autumn
            # Learn with reduced confidence to prevent drift but allow adaptation
            delta_loss = lr * (error * weight_loss) / max(delta_t_out, 0.5) # Clamp divisor
            delta_loss *= 0.3 # Dampen update
            delta_loss = self._clip_dual(delta_loss, self.loss_factor, 0.05, 2.0)
            self.loss_factor += delta_loss

        # Enforce bounds
        self.mass_factor = max(self.min_mass, min(self.max_mass, self.mass_factor))
        # Loss can go to 0.0 if perfectly insulated/warm
        self.loss_factor = max(0.0, min(50.0, self.loss_factor)) 
        
        self.sample_count += 1
        return True

    def _clip_dual(self, delta: float, current: float, rel_limit: float, abs_limit: float) -> float:
        """Dual clipping: relative AND absolute limits."""
        # Allow at least some change even if current is small
        current_safe = max(abs(current), 1.0) 
        rel_bound = current_safe * rel_limit
        max_change = min(rel_bound, abs_limit)
        return max(-max_change, min(max_change, delta))

    def to_dict(self) -> dict:
        """Export data."""
        return {
            "mass_factor": self.mass_factor,
            "loss_factor": self.loss_factor,
            "sample_count": self.sample_count,
            "avg_error": self.avg_error,
            "deadtime": self.deadtime
        }
