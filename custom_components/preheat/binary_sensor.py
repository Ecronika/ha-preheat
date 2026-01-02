"""Binary Sensor platform for Preheat."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION
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
    ]
    
    async_add_entities(sensors)

class PreheatBaseBinarySensor(CoordinatorEntity[PreheatingCoordinator], BinarySensorEntity):
    """Base binary sensor."""
    _attr_has_entity_name = True
    _attr_name = None


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
    _attr_icon = "mdi:leaf"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.entry_id}_optimal_stop_active"

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
