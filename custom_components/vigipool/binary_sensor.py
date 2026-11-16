"""Binary sensor platform for CCEI Vigipool integration."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

try:
    from homeassistant.components.binary_sensor import (
        BinarySensorDeviceClass,
        BinarySensorEntity,
        BinarySensorEntityDescription,
    )
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.dispatcher import async_dispatcher_connect
    from homeassistant.helpers.entity import EntityCategory
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
except ImportError:
    @dataclass(frozen=True, kw_only=True)
    class BinarySensorEntityDescription:
        key: str
        name: str | None = None
        translation_key: str | None = None
        device_class: Any | None = None
        entity_category: Any | None = None

    class BinarySensorDeviceClass:
        RUNNING = "running"
        CONNECTIVITY = "connectivity"

    class EntityCategory:
        DIAGNOSTIC = "diagnostic"

    class BinarySensorEntity:
        pass

    async_dispatcher_connect = lambda *args: None

from .const import DOMAIN, SIGNAL_VIGIPOOL_NEW_DEVICE
from .coordinator import VigipoolCoordinator
from .entity import VigipoolBaseEntity, VigipoolHubBaseEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class VigipoolBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Description for a Vigipool binary sensor entity."""

    supported_prefixes: tuple[str, ...] = ()
    data_field: str = ""


BINARY_SENSOR_DESCRIPTIONS: tuple[VigipoolBinarySensorEntityDescription, ...] = (
    VigipoolBinarySensorEntityDescription(
        key="flow_on",
        data_field="flow_on",
        name="Water Flow",
        translation_key="water_flow",
        device_class=BinarySensorDeviceClass.RUNNING,
        supported_prefixes=("ziphox", "anteaox"),
    ),
    VigipoolBinarySensorEntityDescription(
        key="inject_on",
        data_field="inject_on",
        name="Injecting Product",
        translation_key="injecting_product",
        device_class=BinarySensorDeviceClass.RUNNING,
        supported_prefixes=("phileox", "daisyph", "lynx"),
    ),
)


class VigipoolBinarySensor(VigipoolBaseEntity, BinarySensorEntity):
    """Representation of a Vigipool binary sensor."""

    entity_description: VigipoolBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: VigipoolCoordinator,
        device_id: str,
        description: VigipoolBinarySensorEntityDescription,
    ) -> None:
        """Initialize binary sensor."""
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return True if the binary sensor is on."""
        val = self.get_device_data(self.entity_description.data_field)
        if val is None:
            return None
        return bool(val)


class VigipoolHubConnectivityBinarySensor(VigipoolHubBaseEntity, BinarySensorEntity):
    """Hub connectivity binary sensor."""

    def __init__(self, coordinator: VigipoolCoordinator) -> None:
        """Initialize connectivity sensor."""
        super().__init__(coordinator, "connectivity")
        self._attr_name = "Cloud / Gateway Connection"
        self._attr_translation_key = "gateway_connectivity"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        """Return True if broker is currently connected."""
        return self.coordinator.is_connected


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vigipool binary sensors."""
    coordinator: VigipoolCoordinator = hass.data[DOMAIN][entry.entry_id]
    created_entity_ids: set[str] = set()

    def _create_entities_for_device(device_id: str) -> list[BinarySensorEntity]:
        device = coordinator.devices.get(device_id)
        if not device:
            return []

        new_entities: list[BinarySensorEntity] = []
        for description in BINARY_SENSOR_DESCRIPTIONS:
            if device.prefix in description.supported_prefixes:
                entity_uid = f"{device_id}_{description.key}"
                if entity_uid not in created_entity_ids:
                    created_entity_ids.add(entity_uid)
                    new_entities.append(
                        VigipoolBinarySensor(coordinator, device_id, description)
                    )
        return new_entities

    # Add Hub connectivity binary sensor
    async_add_entities([VigipoolHubConnectivityBinarySensor(coordinator)])

    # Add existing devices
    initial_entities: list[BinarySensorEntity] = []
    for dev_id in coordinator.devices:
        initial_entities.extend(_create_entities_for_device(dev_id))
    if initial_entities:
        async_add_entities(initial_entities)

    # Listen for new devices
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
