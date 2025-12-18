"""Diagnostics support for Intelligent Preheating."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import PreheatingCoordinator, PreheatData

from .const import (
    CONF_OCCUPANCY, CONF_CLIMATE, CONF_TEMPERATURE, CONF_SETPOINT, 
    CONF_OUTDOOR_TEMP, CONF_WEATHER_ENTITY, CONF_WORKDAY, CONF_SCHEDULE_ENTITY
)

TO_REDACT = {
    "unique_id", "entry_id",
    CONF_OCCUPANCY, CONF_CLIMATE, CONF_TEMPERATURE, CONF_SETPOINT,
    CONF_OUTDOOR_TEMP, CONF_WEATHER_ENTITY, CONF_WORKDAY, CONF_SCHEDULE_ENTITY
}

async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: PreheatingCoordinator = entry.runtime_data
    
    physics_data = coordinator.physics.to_dict()
    physics_data["health_score"] = coordinator.physics.health_score

    # Planner Data
    schedule_summary = coordinator.planner.get_schedule_summary()
    
    # Internal State
    internal_state = {
        "preheat_active": coordinator.data.preheat_active,
        "target_setpoint": coordinator.data.target_setpoint,
        "operative_temp": coordinator.data.operative_temp,
        "outdoor_temp": coordinator.data.outdoor_temp,
        "next_arrival": coordinator.data.next_arrival.isoformat() if coordinator.data.next_arrival else None,
        "valve_position": coordinator.data.valve_signal,
        "window_open_detected": getattr(coordinator, "window_open_detected", None), # To be implemented
        "learning_active": coordinator.data.learning_active,
    }

    return {
        "entry_data": async_redact_data(entry.data, TO_REDACT),
        "entry_options": async_redact_data(entry.options, TO_REDACT),
        "physics": physics_data,
        "schedule": schedule_summary,
        "state": internal_state,
    }
