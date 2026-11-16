"""Button platform for CCEI Vigipool integration."""
from __future__ import annotations

import logging
from typing import Any

try:
    from homeassistant.components.button import (
        ButtonDeviceClass,
        ButtonEntity,
        ButtonEntityDescription,
    )
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity import EntityCategory
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
except ImportError:
    class ButtonEntityDescription:
        def __init__(self, key: str, **kwargs):
            self.key = key
            self.__dict__.update(kwargs)

    class ButtonDeviceClass:
        RESTART = "restart"
        UPDATE = "update"

    class EntityCategory:
        DIAGNOSTIC = "diagnostic"

    class ButtonEntity:
        pass

from .const import DOMAIN
from .coordinator import VigipoolCoordinator
from .entity import VigipoolHubBaseEntity

_LOGGER = logging.getLogger(__name__)


class VigipoolReconnectButton(VigipoolHubBaseEntity, ButtonEntity):
    """Button to manually force reconnection to the Vigipool gateway."""

    _attr_translation_key = "reconnect_gateway"
    _attr_name = "Reconnect Gateway"
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VigipoolCoordinator) -> None:
        """Initialize reconnect button."""
        super().__init__(coordinator, "reconnect")

    async def async_press(self) -> None:
        """Handle button press."""
        _LOGGER.info("User requested reconnection to Vigipool gateway at %s", self.coordinator.host)
        await self.coordinator.mqtt_client.async_disconnect()
        await self.coordinator.mqtt_client.async_connect()


class VigipoolRefreshButton(VigipoolHubBaseEntity, ButtonEntity):
    """Button to refresh Vigipool device data subscriptions."""

    _attr_translation_key = "refresh_data"
    _attr_name = "Refresh Devices Data"
    _attr_device_class = ButtonDeviceClass.UPDATE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VigipoolCoordinator) -> None:
        """Initialize refresh button."""
        super().__init__(coordinator, "refresh")

    async def async_press(self) -> None:
        """Handle refresh button press."""
        _LOGGER.info("User requested refresh of Vigipool device data")
        if self.coordinator.is_connected:
            await self.coordinator.mqtt_client.async_subscribe("#")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vigipool diagnostic buttons."""
    coordinator: VigipoolCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            VigipoolReconnectButton(coordinator),
            VigipoolRefreshButton(coordinator),
        ]
    )
