"""Switch platform for Preheat integration."""
from __future__ import annotations

from functools import cached_property
from typing import Any, TYPE_CHECKING

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from . import PreheatConfigEntry
    from .coordinator import PreheatingCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PreheatConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Preheat switch."""
    coordinator = entry.runtime_data
    async_add_entities([PreheatingSwitch(coordinator, entry)])


class PreheatingSwitch(CoordinatorEntity["PreheatingCoordinator"], SwitchEntity):
    """Switch to control preheat mode."""

    _attr_icon = "mdi:radiator"
    _attr_has_entity_name = True
    _attr_translation_key = "preheat"

    def __init__(self, coordinator: PreheatingCoordinator, entry: PreheatConfigEntry) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_preheat"

    @cached_property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry_id)},
            name=self.coordinator.device_name,
            manufacturer="Ecronika",
            model="Intelligent Preheating",
            sw_version=VERSION,
        )

    @property
    def is_on(self) -> bool:
        """Return true if preheat is on."""
        return self.coordinator.data.preheat_active


    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on preheat."""
        await self.coordinator.force_preheat_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off preheat manually."""
        await self.coordinator.stop_preheat_manual()