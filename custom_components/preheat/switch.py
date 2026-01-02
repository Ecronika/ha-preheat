"""Switch platform for Preheat integration."""
from __future__ import annotations

from functools import cached_property
from typing import Any, TYPE_CHECKING

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION, ATTR_DECISION_TRACE, CONF_PREHEAT_HOLD

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
    async_add_entities([
        PreheatingSwitch(coordinator, entry),
        PreheatHoldSwitch(coordinator, entry),
        PreheatEnabledSwitch(coordinator, entry)
    ])


class PreheatingSwitch(CoordinatorEntity["PreheatingCoordinator"], SwitchEntity):
    """Switch to control preheat mode."""

    _attr_icon = "mdi:radiator"
    _attr_has_entity_name = True
    _attr_name = None
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
        
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return decision trace."""
        attrs = {}
        if self.coordinator.data.decision_trace:
             attrs[ATTR_DECISION_TRACE] = self.coordinator.data.decision_trace
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on preheat."""
        await self.coordinator.force_preheat_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off preheat manually."""
        await self.coordinator.stop_preheat_manual()

class PreheatHoldSwitch(CoordinatorEntity["PreheatingCoordinator"], SwitchEntity):
    """Switch to manually HOLD (Block) preheat logic."""

    _attr_icon = "mdi:hand-back-left"
    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "preheat_hold"

    def __init__(self, coordinator: PreheatingCoordinator, entry: PreheatConfigEntry) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_{CONF_PREHEAT_HOLD}"

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
        """Return true if hold is active."""
        return self.coordinator.hold_active

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on hold."""
        await self.coordinator.set_hold(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off hold."""
        await self.coordinator.set_hold(False)

class PreheatEnabledSwitch(CoordinatorEntity["PreheatingCoordinator"], SwitchEntity):
    """Master switch to enable/disable the preheat logic."""

    _attr_icon = "mdi:power"
    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "enabled"

    def __init__(self, coordinator: PreheatingCoordinator, entry: PreheatConfigEntry) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.entry_id = entry.entry_id
        # Use existing 'enabled' convention if possible? No, we use custom unique_id
        self._attr_unique_id = f"{entry.entry_id}_enabled"

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
        """Return true if enabled."""
        return self.coordinator.enable_active

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable."""
        await self.coordinator.set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable."""
        await self.coordinator.set_enabled(False)