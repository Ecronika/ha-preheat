"""Sensor platform for Preheat."""
from __future__ import annotations

from typing import Any
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION
from .coordinator import PreheatingCoordinator, PreheatData

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator: PreheatingCoordinator = entry.runtime_data
    
    sensors = [
        PreheatStatusSensor(coordinator, entry),
        NextEventSensor(coordinator, entry),
        ThermalModelSensor(coordinator, entry),
        PhysicsSensor(coordinator, entry, "mass_factor", "mass_factor", "min/K"),
        PhysicsSensor(coordinator, entry, "loss_factor", "loss_factor", "min/K"),
        PreheatConfidenceSensor(coordinator, entry),
        PreheatOptimalStopTimeSensor(coordinator, entry),
    ]
    
    async_add_entities(sensors)

class PreheatBaseSensor(CoordinatorEntity[PreheatingCoordinator], SensorEntity):
    """Base sensor."""
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

class PreheatStatusSensor(PreheatBaseSensor):
    """Main Status Sensor."""
    _attr_translation_key = "status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["idle", "preheating"]

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_status"

    @property
    def native_value(self) -> str:
        if self.coordinator.data.preheat_active:
            return "preheating"
        return "idle"
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        physics = self.coordinator.physics
        return {
            "target_temp": data.target_setpoint,
            "current_temp": data.operative_temp,
            "predicted_duration": round(data.predicted_duration, 1),
            "confidence": physics.get_confidence(),
            "avg_error": round(physics.avg_error, 2),
            "sample_count": physics.sample_count,
            "window_open": data.window_open,
            "learned_setpoint": data.last_comfort_setpoint,
            "deadtime_min": round(data.deadtime, 1),
            "health_score": physics.health_score,
        }

class NextEventSensor(PreheatBaseSensor):
    """Next Planned Event."""
    _attr_translation_key = "next_event"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_next_event"

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.next_arrival
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        attrs = {}
        if data.next_start_time:
            attrs["planned_start"] = data.next_start_time.isoformat()
        if data.schedule_summary:
            attrs["learned_schedule"] = data.schedule_summary

        # v2.6 Patterns
        attrs["pattern_type"] = data.pattern_type
        attrs["pattern_confidence"] = round(data.pattern_confidence, 2)
        attrs["pattern_stability"] = round(data.pattern_stability, 2)
        attrs["fallback_used"] = data.fallback_used
        
        if data.detected_modes:
            attrs["detected_modes"] = data.detected_modes
            
        return attrs

class ThermalModelSensor(PreheatBaseSensor):
    """Combined Model Status."""
    _attr_translation_key = "model_status"
    _attr_icon = "mdi:chart-line"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_model_status"
    
    @property
    def native_value(self) -> str:
        if self.coordinator.data.learning_active:
            return "learning"
        return "ready"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        val = self.coordinator.data.valve_signal
        return {
            "valve_coverage": "ok" if val is not None else "none",
            "valve_position": f"{val}%" if val is not None else "n/a"
        }

class PhysicsSensor(PreheatBaseSensor):
    """Raw Physics Values."""
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:function"

    def __init__(self, coordinator, entry, key, translation_key, unit):
        super().__init__(coordinator, entry)
        self._key = key
        self._attr_translation_key = translation_key
        self._attr_native_unit_of_measurement = unit

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_{self._key}"

    @property
    def native_value(self) -> float:
        return round(getattr(self.coordinator.data, self._key, 0.0), 2)

class PreheatConfidenceSensor(PreheatBaseSensor):
    """Confidence in the learned model."""
    _attr_translation_key = "confidence"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:shield-check"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_confidence"

    @property
    def native_value(self) -> int:
        return self.coordinator.physics.get_confidence()

class PreheatOptimalStopTimeSensor(PreheatBaseSensor):
    """Optimal Stop trigger time."""
    _attr_translation_key = "optimal_stop_time"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-end"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_optimal_stop_time"

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.optimal_stop_time

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "savings_total_min": round(data.savings_total, 1),
            "savings_remaining_min": round(data.savings_remaining, 1),
            "reason": data.stop_reason,
            "coast_tau_hours": round(data.coast_tau, 1),
            "tau_confidence": round(data.tau_confidence * 100, 1),
            "is_active": data.optimal_stop_active
        }