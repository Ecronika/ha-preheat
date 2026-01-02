"""Button platform for Preheat integration."""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION
from .coordinator import PreheatingCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from . import PreheatConfigEntry

@dataclass(frozen=True, kw_only=True)
class PreheatButtonDescription(ButtonEntityDescription):
    """Class to describe a Preheat button."""
    press_action: str

BUTTONS: tuple[PreheatButtonDescription, ...] = (
    PreheatButtonDescription(
        key="reset_gain",
        translation_key="reset_gain",
        icon="mdi:thermometer-alert",
        press_action="reset_gain",
    ),
    PreheatButtonDescription(
        key="reset_schedule",
        translation_key="reset_schedule",
        icon="mdi:calendar-refresh",
        press_action="reset_schedule",
    ),
    PreheatButtonDescription(
        key="analyze_history",
        translation_key="analyze_history",
        icon="mdi:history",
        press_action="analyze_history",
    ),
    # v3.0 Spec Buttons
    PreheatButtonDescription(
        key="reset_model",
        translation_key="reset_model",
        icon="mdi:restart",
        press_action="reset_model",
    ),
    PreheatButtonDescription(
        key="recompute",
        translation_key="recompute",
        icon="mdi:calculator",
        press_action="recompute",
    ),
)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: PreheatConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the buttons."""
    coordinator = entry.runtime_data
    async_add_entities(
        PreheatButton(coordinator, entry, description)
        for description in BUTTONS
    )

class PreheatButton(CoordinatorEntity[PreheatingCoordinator], ButtonEntity):
    """Representation of a Preheat button."""

    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False
    entity_description: PreheatButtonDescription

    def __init__(
        self,
        coordinator: PreheatingCoordinator,
        entry: PreheatConfigEntry,
        description: PreheatButtonDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.entity_description = description
        self.entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

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


    async def async_press(self) -> None:
        """Handle the button press."""
        if self.entity_description.press_action == "reset_gain":
            await self.coordinator.reset_gain()
        elif self.entity_description.press_action == "reset_schedule":
            await self.coordinator.reset_arrivals()
        elif self.entity_description.press_action == "analyze_history":
            await self.coordinator.analyze_history()
        elif self.entity_description.press_action == "reset_model":
            await self.coordinator.reset_model()
        elif self.entity_description.press_action == "recompute":
            await self.coordinator.recompute()