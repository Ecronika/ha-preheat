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
    ]
    
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
