"""Light platform for CCEI Vigipool pool projectors and controllers."""
from __future__ import annotations

import logging
from typing import Any

try:
    from homeassistant.components.light import (
        ATTR_BRIGHTNESS,
        ATTR_EFFECT,
        ColorMode,
        LightEntity,
        LightEntityFeature,
    )
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.dispatcher import async_dispatcher_connect
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
except ImportError:
    class ColorMode:
        ONOFF = "onoff"
        BRIGHTNESS = "brightness"

    class LightEntityFeature:
        EFFECT = 4

    ATTR_BRIGHTNESS = "brightness"
    ATTR_EFFECT = "effect"

    class LightEntity:
        pass

    async_dispatcher_connect = lambda *args: None

from .const import DOMAIN, SIGNAL_VIGIPOOL_NEW_DEVICE, VIGIBRIO_EFFECT_LIST
from .coordinator import VigipoolCoordinator
from .entity import VigipoolBaseEntity

_LOGGER = logging.getLogger(__name__)


class VigipoolTildLight(VigipoolBaseEntity, LightEntity):
    """Representation of Tild VP pool lighting."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_translation_key = "pool_light"
    _attr_name = "Light"

    def __init__(self, coordinator: VigipoolCoordinator, device_id: str) -> None:
        """Initialize Tild light."""
        super().__init__(coordinator, device_id, "light")

    @property
    def is_on(self) -> bool | None:
        """Return True if light is on."""
        return self.get_device_data("light_state")

    @property
    def brightness(self) -> int | None:
        """Return brightness between 0 and 255."""
        bright_pct = self.get_device_data("light_bright")
        if bright_pct is None:
            return None
        return int((bright_pct / 100.0) * 255)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light, optionally setting brightness."""
        if ATTR_BRIGHTNESS in kwargs:
            pct = int((kwargs[ATTR_BRIGHTNESS] / 255.0) * 100)
            await self.coordinator.async_send_command(
                self.device_id, "u8_w", "light_bright", "info", pct
            )
        await self.coordinator.async_send_command(
            self.device_id, "u8_w", "light_state", "info", "1"
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        await self.coordinator.async_send_command(
            self.device_id, "u8_w", "light_state", "info", "0"
        )


class VigipoolVigiBrioLight(VigipoolBaseEntity, LightEntity):
    """Representation of VigiBrio (x312) RGB projector lighting."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = VIGIBRIO_EFFECT_LIST
    _attr_translation_key = "vigibrio_light"
    _attr_name = "VigiBrio Light"

    def __init__(self, coordinator: VigipoolCoordinator, device_id: str) -> None:
        """Initialize VigiBrio light."""
        super().__init__(coordinator, device_id, "x3_light")

    @property
    def is_on(self) -> bool | None:
        """Return True if light is on."""
        return self.get_device_data("x3_state")

    @property
    def brightness(self) -> int | None:
        """Return brightness (0..255)."""
        pct = self.get_device_data("x3_bright")
        if pct is None:
            return None
        return int((pct / 100.0) * 255)

    @property
    def effect(self) -> str | None:
        """Return current lighting effect."""
        return self.get_device_data("x3_color")

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light, optionally with brightness or effect."""
        if ATTR_EFFECT in kwargs:
            effect_name = kwargs[ATTR_EFFECT]
            await self.coordinator.async_send_command(
                self.device_id, "s128_w", "x3_color", "info", effect_name
            )
        if ATTR_BRIGHTNESS in kwargs:
            pct = int((kwargs[ATTR_BRIGHTNESS] / 255.0) * 100)
            await self.coordinator.async_send_command(
                self.device_id, "u8_w", "x3_bright", "info", pct
            )
        await self.coordinator.async_send_command(
            self.device_id, "u8_w", "x3_state", "info", "1"
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        await self.coordinator.async_send_command(
            self.device_id, "u8_w", "x3_state", "info", "0"
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vigipool lights."""
    coordinator: VigipoolCoordinator = hass.data[DOMAIN][entry.entry_id]
    created_entity_ids: set[str] = set()

    def _create_entities_for_device(device_id: str) -> list[LightEntity]:
        device = coordinator.devices.get(device_id)
        if not device:
            return []

        new_entities: list[LightEntity] = []
        if device.prefix == "tild":
            uid = f"{device_id}_light"
            if uid not in created_entity_ids:
                created_entity_ids.add(uid)
                new_entities.append(VigipoolTildLight(coordinator, device_id))
        elif device.prefix == "x312":
            uid = f"{device_id}_x3_light"
            if uid not in created_entity_ids:
                created_entity_ids.add(uid)
                new_entities.append(VigipoolVigiBrioLight(coordinator, device_id))

        return new_entities

    initial_entities: list[LightEntity] = []
    for dev_id in coordinator.devices:
        initial_entities.extend(_create_entities_for_device(dev_id))
    if initial_entities:
        async_add_entities(initial_entities)

    def _on_new_device(new_device_id: str) -> None:
        entities = _create_entities_for_device(new_device_id)
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_VIGIPOOL_NEW_DEVICE.format(entry.entry_id),
            _on_new_device,
        )
    )
