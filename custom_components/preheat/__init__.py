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

    """Helper to resolve targets."""
    from homeassistant.helpers import service, entity_registry
    
    entries = set()
    
    # 1. Check for explicit config_entry_id
    if "config_entry_id" in call.data:
        ce_ids = call.data["config_entry_id"]
        if isinstance(ce_ids, str):
            entries.add(ce_ids)
        elif isinstance(ce_ids, list):
            entries.update(ce_ids)
            
    # 2. Check for entities
    referenced = await service.async_extract_referenced_entity_ids(hass, call)
    if referenced.referenced:
        ent_reg = entity_registry.async_get(hass)
        for eid in referenced.referenced:
            if ent := ent_reg.async_get(eid):
                if ent.platform == DOMAIN and ent.config_entry_id:
                     entries.add(ent.config_entry_id)
                     
    # 3. Fallback: If NO target specified at all (no area, no device, no entity, no ID)
    #    Then target ALL entries.
    if not entries and not referenced.referenced and not referenced.devices and not referenced.areas and "config_entry_id" not in call.data:
         for entry in hass.config_entries.async_entries(DOMAIN):
            entries.add(entry.entry_id)

    return list(entries)


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