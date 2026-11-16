"""Switch platform for CCEI Vigipool integration."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

try:
    from homeassistant.components.switch import (
        SwitchDeviceClass,
        SwitchEntity,
        SwitchEntityDescription,
    )
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.dispatcher import async_dispatcher_connect
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
except ImportError:
    @dataclass(frozen=True, kw_only=True)
    class SwitchEntityDescription:
        key: str
        name: str | None = None
        translation_key: str | None = None
        device_class: Any | None = None

    class SwitchDeviceClass:
        SWITCH = "switch"

    class SwitchEntity:
        pass

    async_dispatcher_connect = lambda *args: None

from .const import DOMAIN, SIGNAL_VIGIPOOL_NEW_DEVICE
from .coordinator import VigipoolCoordinator
from .entity import VigipoolBaseEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class VigipoolSwitchEntityDescription(SwitchEntityDescription):
    """Description for a Vigipool switch entity."""

    supported_prefixes: tuple[str, ...] = ()
    data_type_rw: str = ""
    data_field: str = ""
    category: str = "info"


SWITCH_DESCRIPTIONS: tuple[VigipoolSwitchEntityDescription, ...] = (
    VigipoolSwitchEntityDescription(
        key="filt_state",
        data_field="filt_state",
        data_type_rw="u8_w",
        category="info",
        name="Filtration",
        translation_key="filtration",
        device_class=SwitchDeviceClass.SWITCH,
        supported_prefixes=("tild",),
    ),
    VigipoolSwitchEntityDescription(
        key="aux_conf",
        data_field="aux_conf",
        data_type_rw="u16_w",
        category="info",
        name="Auxiliary Output",
        translation_key="auxiliary",
        device_class=SwitchDeviceClass.SWITCH,
        supported_prefixes=("tild",),
    ),
)


class VigipoolSwitch(VigipoolBaseEntity, SwitchEntity):
    """Representation of a Vigipool switch (filtration, auxiliary output)."""

    entity_description: VigipoolSwitchEntityDescription

    def __init__(
        self,
        coordinator: VigipoolCoordinator,
        device_id: str,
        description: VigipoolSwitchEntityDescription,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return True if switch is on."""
        return self.get_device_data(self.entity_description.data_field)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn switch on via MQTT desired topic."""
        await self.coordinator.async_send_command(
            self.device_id,
            self.entity_description.data_type_rw,
            self.entity_description.data_field,
            self.entity_description.category,
            "1",
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn switch off via MQTT desired topic."""
        await self.coordinator.async_send_command(
            self.device_id,
            self.entity_description.data_type_rw,
            self.entity_description.data_field,
            self.entity_description.category,
            "0",
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vigipool switches."""
    coordinator: VigipoolCoordinator = hass.data[DOMAIN][entry.entry_id]
    created_entity_ids: set[str] = set()

    def _create_entities_for_device(device_id: str) -> list[SwitchEntity]:
        device = coordinator.devices.get(device_id)
        if not device:
            return []

        new_entities: list[SwitchEntity] = []
        for description in SWITCH_DESCRIPTIONS:
            if device.prefix in description.supported_prefixes:
                entity_uid = f"{device_id}_{description.key}"
                if entity_uid not in created_entity_ids:
                    created_entity_ids.add(entity_uid)
                    new_entities.append(
                        VigipoolSwitch(coordinator, device_id, description)
                    )
        return new_entities

    initial_entities: list[SwitchEntity] = []
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
