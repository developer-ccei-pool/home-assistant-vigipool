"""CCEI Vigipool integration for Home Assistant."""
from __future__ import annotations

import logging
from typing import Any

try:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.const import Platform
    from homeassistant.core import HomeAssistant
except ImportError:
    class Platform:
        SENSOR = "sensor"
        BINARY_SENSOR = "binary_sensor"
        SWITCH = "switch"
        LIGHT = "light"
        NUMBER = "number"
        SELECT = "select"
        BUTTON = "button"

    class ConfigEntry:
        pass

    class HomeAssistant:
        pass

from .const import (
    CONF_BROKER,
    CONF_PORT,
    CONF_PRIMARY_DEVICE_ID,
    DEFAULT_PORT,
    DOMAIN,
)
from .coordinator import VigipoolCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.BUTTON,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CCEI Vigipool from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_BROKER]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    primary_device_id = entry.data.get(CONF_PRIMARY_DEVICE_ID, "")

    _LOGGER.info("Setting up Vigipool integration for broker %s:%d", host, port)

    coordinator = VigipoolCoordinator(
        hass=hass,
        entry=entry,
        host=host,
        port=port,
        primary_device_id=primary_device_id,
    )

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Start coordinator (connects to MQTT broker and subscribes)
    await coordinator.async_start()

    # Forward setup to all entity platforms
    if hasattr(hass.config_entries, "async_forward_entry_setups"):
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    else:
        # Fallback for older versions
        for platform in PLATFORMS:
            hass.async_create_task(
                hass.config_entries.async_forward_entry_setup(entry, platform)
            )

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Vigipool config entry."""
    _LOGGER.info("Unloading Vigipool integration entry %s", entry.entry_id)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: VigipoolCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_stop()

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)
