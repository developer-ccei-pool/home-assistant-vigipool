"""Diagnostics support for CCEI Vigipool."""
from __future__ import annotations

from typing import Any

try:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
except ImportError:
    class ConfigEntry:  # type: ignore[no-redef]
        pass

    class HomeAssistant:  # type: ignore[no-redef]
        pass

from .const import CONF_BROKER, CONF_PORT, CONF_PRIMARY_DEVICE_ID, DOMAIN
from .coordinator import VigipoolCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: VigipoolCoordinator = hass.data[DOMAIN][entry.entry_id]

    devices_info: dict[str, Any] = {}
    for device_id, device in coordinator.devices.items():
        devices_info[device_id] = {
            "model": device.model,
            "prefix": device.prefix,
            "mac": device.mac,
            "description": device.description,
            "last_seen": device.last_seen,
            "info": device.info,
            "data": coordinator.data.get(device_id, {}),
        }

    return {
        "entry": {
            "entry_id": getattr(entry, "entry_id", ""),
            "version": getattr(entry, "version", 1),
            "domain": getattr(entry, "domain", DOMAIN),
            "title": getattr(entry, "title", ""),
            "data": {
                CONF_BROKER: entry.data.get(CONF_BROKER),
                CONF_PORT: entry.data.get(CONF_PORT),
                CONF_PRIMARY_DEVICE_ID: entry.data.get(CONF_PRIMARY_DEVICE_ID),
            },
            "options": dict(getattr(entry, "options", {})),
        },
        "coordinator": {
            "host": coordinator.host,
            "port": coordinator.port,
            "is_connected": coordinator.is_connected,
            "last_communication": coordinator.last_communication,
            "devices_count": len(coordinator.devices),
        },
        "devices": devices_info,
    }
