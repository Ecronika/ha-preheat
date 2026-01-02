"""The Preheat integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, CONF_PRESET_MODE, CONF_EXPERT_MODE, PRESET_BALANCED
# from .coordinator import PreheatingCoordinator # Lazy import

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.BUTTON, Platform.BINARY_SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PreheatConfigEntry = ConfigEntry # [PreheatingCoordinator] Lazy typing

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Preheat component globally."""
    await async_setup_services(hass)
    return True

async def async_setup_services(hass: HomeAssistant):
    """Register services."""
    
    async def handle_recompute(call):
        """Force recompute."""
        for entry_id in await _get_target_entries(hass, call):
            if entry := hass.config_entries.async_get_entry(entry_id):
                 if hasattr(entry, "runtime_data"):
                     await entry.runtime_data.async_refresh()

    async def handle_reset_model(call):
        """Reset thermal model."""
        for entry_id in await _get_target_entries(hass, call):
             if entry := hass.config_entries.async_get_entry(entry_id):
                 if hasattr(entry, "runtime_data"):
                     entry.runtime_data.reset_model()

    hass.services.async_register(DOMAIN, "recompute", handle_recompute)
    hass.services.async_register(DOMAIN, "reset_model", handle_reset_model)

async def _get_target_entries(hass, call):
    """Helper to resolve targets."""
    # Simplified target resolution (Target Selector support requires services.yaml)
    # For now, it iterates all active preheat entries if no target specified
    # Or strict targetting if 'entity_id' is passed.
    # TODO: Full TargetSelector support
    entries = []
    if "config_entry_id" in call.data:
        entries.append(call.data["config_entry_id"])
    elif "entity_id" in call.data:
         # Resolve entity to config entry
         reg = hass.helpers.entity_registry.async_get(hass)
         for eid in call.data["entity_id"]:
             if ent := reg.async_get(eid):
                 entries.append(ent.config_entry_id)
    else:
        # Fallback: All Loaded Entries
        for entry in hass.config_entries.async_entries(DOMAIN):
            entries.append(entry.entry_id)
    
    return entries


async def async_setup_entry(hass: HomeAssistant, entry: PreheatConfigEntry) -> bool:
    """Set up Preheat from a config entry."""
    from .coordinator import PreheatingCoordinator
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
    await hass.config_entries.async_reload(entry.entry_id)

async def async_migrate_entry(hass: HomeAssistant, config_entry: PreheatConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    current_version = config_entry.version

    # v1 -> v2
    if current_version == 1:
        _LOGGER.info("Migrating v1 -> v2")
        new_options = {**config_entry.options}
        new_options[CONF_PRESET_MODE] = PRESET_BALANCED
        new_options[CONF_EXPERT_MODE] = True
        
        hass.config_entries.async_update_entry(config_entry, options=new_options, version=2)
        current_version = 2

    # v2 -> v3: Move options to data
    if current_version == 2:
        _LOGGER.info("Migrating v2 -> v3")
        data = dict(config_entry.data)
        options = dict(config_entry.options)
        
        # Move core keys into data if they were previously stored in options
        # We need to import these keys here or ensure they are available
        from .const import CONF_OCCUPANCY, CONF_CLIMATE, CONF_TEMPERATURE, CONF_WEATHER_ENTITY

        for k in (CONF_OCCUPANCY, CONF_CLIMATE, CONF_TEMPERATURE, CONF_WEATHER_ENTITY):
            if k not in data and k in options:
                data[k] = options.pop(k)
        
        # Ensure defaults for Behavior
        if CONF_PRESET_MODE not in options:
            options[CONF_PRESET_MODE] = PRESET_BALANCED
        if CONF_EXPERT_MODE not in options:
            options[CONF_EXPERT_MODE] = False # Default to Simple

        hass.config_entries.async_update_entry(
            config_entry, 
            data=data, 
            options=options, 
            version=3
        )
        current_version = 3
        _LOGGER.info("Migration v2->v3 successful")

    return True