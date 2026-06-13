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

async def _get_target_entries(hass: HomeAssistant, call) -> list[str]:
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
                     
    # 3. Fallback: If NO target specified at all
    # We only check for referenced entities (resolved from devices/areas) to determine if target was provided.
    # Accessing .devices/.areas directly on the result of async_extract_referenced_entity_ids is risky/incorrect.
    has_targets = bool(entries or referenced.referenced)
    
    if not has_targets and "config_entry_id" not in call.data:
         for entry in hass.config_entries.async_entries(DOMAIN):
            entries.add(entry.entry_id)

    return list(entries)


async def async_setup_entry(hass: HomeAssistant, entry: PreheatConfigEntry) -> bool:
    """Set up Preheat from a config entry."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
        
    if "house" not in hass.data[DOMAIN]:
        from .house_collector import HouseArrivalCollector
        house = HouseArrivalCollector(hass)
        await house.async_load()
        await house.async_bootstrap()
        hass.data[DOMAIN]["house"] = house
    else:
        hass.data[DOMAIN]["house"].update_config()

    if entry.unique_id == "preheat_system":
        entry.runtime_data = hass.data[DOMAIN]["house"]
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        entry.async_on_unload(entry.add_update_listener(async_reload_entry))
        return True

    # Check if system entry exists
    system_entry_exists = any(
        e.unique_id == "preheat_system"
        for e in hass.config_entries.async_entries(DOMAIN)
    )
    if not system_entry_exists:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": "system"}
            )
        )

    from .coordinator import PreheatingCoordinator
    coordinator = PreheatingCoordinator(hass, entry)
    coordinator.house_collector = hass.data[DOMAIN]["house"]
    
    await coordinator.async_load_data()
    await coordinator.async_config_entry_first_refresh()
    
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: PreheatConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        if entry.unique_id == "preheat_system":
            if DOMAIN in hass.data and "house" in hass.data[DOMAIN]:
                house = hass.data[DOMAIN].pop("house")
                if house._unsub_listener:
                    house._unsub_listener()
                    house._unsub_listener = None
    return unload_ok

async def async_remove_entry(hass: HomeAssistant, entry: PreheatConfigEntry) -> None:
    """Handle removal of an entry."""
    if entry.unique_id == "preheat_system":
        # Recreate system entry automatically if there are still active zone entries
        active_zones = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.unique_id != "preheat_system"
        ]
        if active_zones:
            _LOGGER.warning(
                "Preheat System entry was deleted while active zone entries exist. Re-creating system entry automatically."
            )
            hass.async_create_task(
                hass.config_entries.flow.async_init(
                    DOMAIN, context={"source": "system"}
                )
            )

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
        
        from .const import CONF_OCCUPANCY, CONF_CLIMATE, CONF_TEMPERATURE, CONF_WEATHER_ENTITY

        for k in (CONF_OCCUPANCY, CONF_CLIMATE, CONF_TEMPERATURE, CONF_WEATHER_ENTITY):
            if k not in data and k in options:
                data[k] = options.pop(k)
        
        if CONF_PRESET_MODE not in options:
            options[CONF_PRESET_MODE] = PRESET_BALANCED
        if CONF_EXPERT_MODE not in options:
            options[CONF_EXPERT_MODE] = False

        hass.config_entries.async_update_entry(
            config_entry, 
            data=data, 
            options=options, 
            version=3
        )
        current_version = 3
        _LOGGER.info("Migration v2->v3 successful")

    # v3 -> v4: Clean Storage (Remove None/Empty)
    if current_version == 3:
        _LOGGER.info("Migrating v3 -> v4 (Cleaning Storage)")
        
        new_data = {}
        for k, v in config_entry.data.items():
            if v not in (None, "", []):
                new_data[k] = v
                
        new_options = {}
        for k, v in config_entry.options.items():
            if v not in (None, "", []):
                new_options[k] = v
                
        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            options=new_options,
            version=4
        )
        current_version = 4
        _LOGGER.info("Migration v3->v4 successful")

    # v4 -> v5: Add default settings for House Arrival Hub
    if current_version == 4:
        _LOGGER.info("Migrating v4 -> v5 (Adding House Hub Defaults)")
        new_data = dict(config_entry.data)
        new_options = dict(config_entry.options)
        
        from .const import CONF_GLOBAL_PRESENCE, CONF_ARRIVAL_COMFORT_BIAS, CONF_EVENING_COMFORT_WINDOW
        if CONF_ARRIVAL_COMFORT_BIAS not in new_options:
            new_options[CONF_ARRIVAL_COMFORT_BIAS] = "comfort"
            
        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            options=new_options,
            version=5
        )
        current_version = 5
        _LOGGER.info("Migration v4->v5 successful")

    # v5 -> v6: Move Hub ownership to system config entry
    if current_version == 5:
        _LOGGER.info("Migrating v5 -> v6 (Moving Hub ownership to system config entry)")
        # 1. Ensure system entry exists
        system_entry = None
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.unique_id == "preheat_system":
                system_entry = entry
                break
        if not system_entry:
            await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": "system"}
            )
            for entry in hass.config_entries.async_entries(DOMAIN):
                if entry.unique_id == "preheat_system":
                    system_entry = entry
                    break
                    
        if system_entry:
            # 2. Re-home device
            from homeassistant.helpers import device_registry as dr
            dev_reg = dr.async_get(hass)
            dev = dev_reg.async_get_device(identifiers={(DOMAIN, "house")})
            if dev and config_entry.entry_id in dev.config_entries:
                dev_reg.async_update_device(
                    dev.id,
                    add_config_entry_id=system_entry.entry_id,
                    remove_config_entry_id=config_entry.entry_id
                )
                
            # 3. Re-home global entities
            from homeassistant.helpers import entity_registry as er
            ent_reg = er.async_get(hass)
            from .const import CONF_GLOBAL_PRESENCE, CONF_ARRIVAL_COMFORT_BIAS, CONF_EVENING_COMFORT_WINDOW
            GLOBAL_ENTITY_UNIQUE_IDS = {"house_next_arrival", "house_arrival_confidence", "house_arrival_window", "house_incoming"}
            for unique_id in GLOBAL_ENTITY_UNIQUE_IDS:
                for platform in PLATFORMS:
                    entity_id = ent_reg.async_get_entity_id(platform, DOMAIN, unique_id)
                    if entity_id:
                        entity_entry = ent_reg.async_get(entity_id)
                        if entity_entry and entity_entry.config_entry_id == config_entry.entry_id:
                            ent_reg.async_update_entity(entity_id, config_entry_id=system_entry.entry_id)
                        break
                        
            # 4. Migrate global option values
            system_options = dict(system_entry.options)
            zone_options = dict(config_entry.options)
            zone_data = dict(config_entry.data)
            
            for key in (CONF_GLOBAL_PRESENCE, CONF_ARRIVAL_COMFORT_BIAS, CONF_EVENING_COMFORT_WINDOW):
                if key in zone_options:
                    system_options[key] = zone_options.pop(key)
                elif key in zone_data:
                    system_options[key] = zone_data.pop(key)
                    
            hass.config_entries.async_update_entry(system_entry, options=system_options)
            
            # Update zone entry (removing migrated keys and bumping version to 6)
            hass.config_entries.async_update_entry(
                config_entry,
                data=zone_data,
                options=zone_options,
                version=6
            )
            current_version = 6
            _LOGGER.info("Migration v5->v6 successful")

    return True