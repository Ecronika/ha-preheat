
import logging
from dataclasses import dataclass

# Mock Constants
DEFAULT_MASS_FACTOR = 10.0
DEFAULT_LOSS_FACTOR = 5.0
DEFAULT_LEARNING_RATE = 0.1

@dataclass
class ThermalModelData:
    mass_factor: float
    loss_factor: float
    sample_count: int
    avg_error: float = 0.0
    deadtime: float = 0.0

class ThermalPhysics:
    def __init__(self, data: ThermalModelData | None = None, 
                 profile_data: dict | None = None,
                 learning_rate: float = DEFAULT_LEARNING_RATE) -> None:
        self.learning_rate = learning_rate
        
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
            self.avg_error = getattr(data, "avg_error", 0.0)
            self.deadtime = getattr(data, "deadtime", 0.0)
            if self.deadtime == 0.0 and profile_data and data.sample_count < 5:
                self.deadtime = initial_deadtime
        else:
            self.mass_factor = initial_mass
            self.loss_factor = DEFAULT_LOSS_FACTOR
            self.sample_count = 0
            self.avg_error = 0.0
            self.deadtime = initial_deadtime

    def calculate_duration(self, delta_t_internal: float, delta_t_external: float) -> float:
        if delta_t_internal <= 0:
            return 0.0
            
        dt_in = delta_t_internal
        dt_out = max(0.0, delta_t_external) 

        loss_scaler = dt_in / 2.0
        
        # The Crashing Line
        duration = self.deadtime + (self.mass_factor * dt_in) + (self.loss_factor * dt_out * loss_scaler)
        return max(0.0, duration)

# Test Cases
print("Test 1: Normal Data")
p1 = ThermalPhysics(ThermalModelData(10.0, 5.0, 10))
res = p1.calculate_duration(2.0, 10.0)
print(f"Result: {res}")

print("\nTest 2: None Data (fresh)")
p2 = ThermalPhysics(None)
res = p2.calculate_duration(2.0, 10.0)
print(f"Result: {res}")

print("\nTest 3: Data with None Factors (Corruption)")
p3 = ThermalPhysics(ThermalModelData(None, None, 10)) # Mypy would complain, but runtime allows
res = p3.calculate_duration(2.0, 10.0)
print(f"Result: {res}")

print("\nTest 4: Data with None Factors AND Profile")
profile = {"default_mass": 20.0, "deadtime": 15.0}
p4 = ThermalPhysics(ThermalModelData(None, None, 10), profile_data=profile)
res = p4.calculate_duration(2.0, 10.0)
print(f"Result: {res}")

print("\nTest 5: None inputs to calculate_duration")
try:
    p1.calculate_duration(None, 10.0)
except Exception as e:
    print(f"Caught expected error for None delta_in: {e}")

