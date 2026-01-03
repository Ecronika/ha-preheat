"""Binary Sensor platform for Preheat."""
from __future__ import annotations

from typing import Any
from datetime import datetime, timedelta
from homeassistant.util import dt as dt_util

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, VERSION, CONF_ENABLE_OPTIMAL_STOP
from .coordinator import PreheatingCoordinator

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator: PreheatingCoordinator = entry.runtime_data
    
    sensors = [
        PreheatOptimalStopBinarySensor(coordinator, entry),
        PreheatActiveBinarySensor(coordinator, entry),
        PreheatNeededBinarySensor(coordinator, entry),
        PreheatBlockedBinarySensor(coordinator, entry),
        PreheatHeatDemandBinarySensor(coordinator, entry),
    ]
    
    # Auto-Enable Logic for Existing Installs
    # If the user enables Optimal Stop in Options, we ensure the entity is enabled in the registry.
    # We check if it was disabled by 'integration' (default) and unhide it.
    enabled_in_config = entry.options.get(CONF_ENABLE_OPTIMAL_STOP) or entry.data.get(CONF_ENABLE_OPTIMAL_STOP, False)
    if enabled_in_config:
        ent_reg = er.async_get(hass)
        opt_stop_id = f"{entry.entry_id}_optimal_stop_active"
        # We need the full entity_id. Since we don't have it easily without 'async_add_entities' returning it or guessing,
        # we can iterate or construct it. But sensors use 'binary_sensor.<name>_optimal_stop_active' usually.
        # Safer: Let the entity init handle default, but if platform setup runs, we can look up by unique_id.
        entity_id = ent_reg.async_get_entity_id("binary_sensor", DOMAIN, opt_stop_id)
        if entity_id:
            entity_entry = ent_reg.async_get(entity_id)
            if entity_entry and entity_entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION:
                ent_reg.async_update_entity(entity_id, disabled_by=None)

    async_add_entities(sensors)

class PreheatBaseBinarySensor(CoordinatorEntity[PreheatingCoordinator], BinarySensorEntity):
    """Base binary sensor."""
    _attr_has_entity_name = True


    def __init__(self, coordinator: PreheatingCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "Ecronika",
            "model": "Intelligent Preheating v2",
            "sw_version": VERSION,
        }

class PreheatOptimalStopBinarySensor(PreheatBaseBinarySensor):
    """Binary sensor indicating if Optimal Stop (Coasting) is active."""
    _attr_translation_key = "optimal_stop_active"
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:leaf"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_optimal_stop_active"

    def __init__(self, coordinator: PreheatingCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        # Dynamic Visibility: Default to ON if feature is enabled in config
        enabled = entry.options.get(CONF_ENABLE_OPTIMAL_STOP) or entry.data.get(CONF_ENABLE_OPTIMAL_STOP, False)
        self._attr_entity_registry_enabled_default = enabled

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.optimal_stop_active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "savings_remaining_min": round(data.savings_remaining, 1),
            "reason": data.stop_reason,
            "coast_tau_hours": round(data.coast_tau, 2),
            "tau_confidence": round(data.tau_confidence * 100, 1)
        }

class PreheatActiveBinarySensor(PreheatBaseBinarySensor):
    """
    Binary sensor indicating if preheat logic is actively heating.
    Rehabilitated as core entity in v2.9.
    """
    _attr_translation_key = "preheat_active"
    _attr_icon = "mdi:radiator"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_preheat_active"

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.preheat_active

class PreheatNeededBinarySensor(PreheatBaseBinarySensor):
    """
    Indicates if preheating IS REQUIRED (Time reached), even if blocked.
    Logic: Now >= Next Start Time (and Start Time exists).
    This serves as the "TriggeR" signal for automations.
    """
    _attr_translation_key = "preheat_needed"
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:clock-alert"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_preheat_needed"

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data
        if not data.next_start_time:
            return False
        
        # We need 'now'. Coordinator updates every minute. 
        # Ideally we compare vs utcnow()
        from homeassistant.util import dt as dt_util
        return dt_util.utcnow() >= data.next_start_time

class PreheatBlockedBinarySensor(PreheatBaseBinarySensor):
    """
    Indicates if preheating is BLOCKED (e.g. Hold, Window, Holiday).
    """
    _attr_translation_key = "preheat_blocked"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:block-helper"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_preheat_blocked"

    @property
    def is_on(self) -> bool:
        trace = self.coordinator.data.decision_trace
        if trace and trace.get("blocked"):
            return True
        return False
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        trace = self.coordinator.data.decision_trace
        attrs = {}
        if trace and trace.get("blocked"):
            attrs["blocked_reasons"] = trace.get("blocked_reasons", [trace.get("reason", "unknown")])
            attrs["reason"] = trace.get("reason", "unknown")
        return attrs

class PreheatHeatDemandBinarySensor(PreheatBaseBinarySensor):
    """
    Indicates valid Heat Demand (Preheat OR Occupancy) adjusted by Optimal Stop / Blocking.
    Logic: (PreheatActive OR Occupied) AND NOT OptimalStop AND NOT Blocked
    Includes Hysteresis and Timers (Min ON 5m, Min OFF 3m).
    """
    _attr_translation_key = "heat_demand"
    _attr_entity_registry_enabled_default = False # User must enable if needed
    _attr_icon = "mdi:fire"

    def __init__(self, coordinator: PreheatingCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_is_on = False # Initial state
        self._last_switch_time: datetime | None = None
        
        # Determine internal demand state separately from output state (for timers)
        # Actually, we can just track output state change time.
        pass

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_heat_demand"

    def _handle_coordinator_update(self) -> None:
        """Calculate state with hysteresis and timers."""
        data = self.coordinator.data
        trace = data.decision_trace or {}
        now = dt_util.utcnow()
        current_state = self._attr_is_on

        # --- Step 1: Calculate Raw Demand (Instantaneous) ---
        raw_demand = False
        forced_off_safety = False
        
        # A. Safety Blocks (Instant OFF)
        if (data.optimal_stop_active or 
            trace.get("blocked", False) or 
            data.window_open or 
            (not data.is_occupied and not data.preheat_active and not data.hvac_action == "heating")): 
             # Note: logic regarding occupancy is simplified here: 
             # If NOT occupied AND NOT preheat AND NOT hvac_heating -> OFF (unless we want to allow valve > 15% when unoccupied? No, usually not).
             # Wait, user spec says: "Wenn eine der Bedingungen zutrifft (Blocks), ist heat_demand = OFF".
             # Occupancy is part of "Demand Logic".
             pass

        if data.optimal_stop_active or trace.get("blocked", False) or data.window_open:
             forced_off_safety = True
             raw_demand = False
        elif data.preheat_active:
             # Boost Mode overrides physical checks
             raw_demand = True
        elif not data.is_occupied:
             # Unoccupied -> OFF (Normal)
             raw_demand = False
        else:
             # B. Physical Checks (Occupied)
             raw_demand = False # Default unless proven otherwise
             
             # 1. HVAC Action
             if data.hvac_action == "heating":
                  raw_demand = True
             
             # 2. Valve Position (with Deadband)
             # V_on = 15%, V_off = 8%
             # If HVAC didn't decide, we check Valve
             if not raw_demand and data.valve_signal is not None:
                  if data.valve_signal >= 15.0:
                       raw_demand = True
                  elif data.valve_signal > 8.0 and current_state:
                       # Deadband retention (if was ON, stay ON down to 8%)
                       raw_demand = True
             
             # 3. Delta T (with Deadband)
             # D_on = 0.4, D_off = 0.2
             if not raw_demand and data.target_setpoint is not None and data.operative_temp is not None:
                  delta = data.target_setpoint - data.operative_temp
                  if delta >= 0.4:
                       raw_demand = True
                  elif delta > 0.2 and current_state:
                       # Deadband retention
                       raw_demand = True

        # --- Step 2: Apply Timers (Anti-Short-Cycle) ---
        new_state = current_state
        
        if forced_off_safety:
             # Safety Override: Instant OFF
             new_state = False
        else:
             if raw_demand != current_state:
                  # State Change Requested
                  if self._last_switch_time is None:
                       # First change -> Allow
                       new_state = raw_demand
                  else:
                       elapsed = (now - self._last_switch_time).total_seconds()
                       
                       if raw_demand: 
                            # Turning ON -> Check Min OFF Time (3 min)
                            # "Wenn er OFF wurde, bleibt er mindestens 3 min OFF"
                            if elapsed >= (3 * 60):
                                 new_state = True
                       else:
                            # Turning OFF -> Check Min ON Time (5 min)
                            # "Wenn er ON wurde, bleibt er mindestens 5 min ON"
                            if elapsed >= (5 * 60):
                                 new_state = False
        
        # --- Step 3: Update State ---
        if new_state != current_state:
             self._attr_is_on = new_state
             self._last_switch_time = now
        
        # Call super to write state to HA
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        trace = data.decision_trace or {}
        
        target = data.target_setpoint
        current = data.operative_temp
        delta = round(target - current, 2) if (target and current) else None
        
        return {
             "reason": trace.get("reason", "unknown"),
             "blocked": trace.get("blocked", False),
             "hvac_action": data.hvac_action,
             "valve_position": data.valve_signal,
             "delta_t": delta,
             "demand_source": self._determine_source(data, delta)
        }

    def _determine_source(self, data, delta):
         if data.preheat_active: return "preheat"
         if data.hvac_action == "heating": return "hvac_action"
         if data.valve_signal is not None and data.valve_signal >= 15.0: return "valve"
         if delta is not None and delta >= 0.4: return "delta_t"
         return "none"
