"""The Preheat integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from homeassistant.helpers import config_validation as cv
from .const import DOMAIN, CONF_PRESET_MODE, CONF_EXPERT_MODE, PRESET_BALANCED
from .coordinator import PreheatingCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.BUTTON]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PreheatConfigEntry = ConfigEntry[PreheatingCoordinator]

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Preheat component globally."""
    return True

async def async_setup_entry(hass: HomeAssistant, entry: PreheatConfigEntry) -> bool:
    """Set up Preheat from a config entry."""
    coordinator = PreheatingCoordinator(hass, entry)
    
    await coordinator.async_load_data()
    await coordinator.async_config_entry_first_refresh()
    
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True

async def async_unload_entry(hass: HomeAssistant, entry: PreheatConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

async def async_reload_entry(hass: HomeAssistant, entry: PreheatConfigEntry) -> None:
    """Reload config entry when options change."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)

async def async_migrate_entry(hass: HomeAssistant, config_entry: PreheatConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    # v1 -> v2
    if config_entry.version == 1:
        new_options = {**config_entry.options}
        new_options[CONF_PRESET_MODE] = PRESET_BALANCED
        new_options[CONF_EXPERT_MODE] = True
        hass.config_entries.async_update_entry(config_entry, options=new_options, version=2)

    # v2 -> v3: Move data to options
    if config_entry.version == 2:
        new_options = {**config_entry.options}
        if config_entry.data:
            new_options.update(config_entry.data)
        
        # Ensure defaults
        if CONF_PRESET_MODE not in new_options:
            new_options[CONF_PRESET_MODE] = PRESET_BALANCED
        if CONF_EXPERT_MODE not in new_options:
            new_options[CONF_EXPERT_MODE] = True

        hass.config_entries.async_update_entry(
            config_entry, 
            data={}, 
            options=new_options, 
            version=3
        )
        _LOGGER.info("Migration v2->v3 successful")

    return True