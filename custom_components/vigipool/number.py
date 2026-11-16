"""Number platform for CCEI Vigipool setpoints and configurations."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

try:
    from homeassistant.components.number import (
        NumberDeviceClass,
        NumberEntity,
        NumberEntityDescription,
        NumberMode,
    )
    from homeassistant.const import UnitOfVolume
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.dispatcher import async_dispatcher_connect
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
except ImportError:
    @dataclass(frozen=True, kw_only=True)
    class NumberEntityDescription:
        key: str
        name: str | None = None
        translation_key: str | None = None
        native_min_value: float = 0.0
        native_max_value: float = 100.0
        native_step: float = 1.0
        native_unit_of_measurement: str | None = None
        mode: str = "slider"
        device_class: Any | None = None

    class NumberDeviceClass:
        pass

    class NumberMode:
        SLIDER = "slider"
        BOX = "box"

    UnitOfVolume = type("UnitOfVolume", (), {"LITERS": "L"})

    class NumberEntity:
        pass

    async_dispatcher_connect = lambda *args: None

from .const import DOMAIN, SIGNAL_VIGIPOOL_NEW_DEVICE
from .coordinator import VigipoolCoordinator
from .entity import VigipoolBaseEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class VigipoolNumberEntityDescription(NumberEntityDescription):
    """Description for a Vigipool number entity."""

    supported_prefixes: tuple[str, ...] = ()
    data_type_rw: str = ""
    data_field: str = ""
    category: str = "info"
    multiplier_to_device: float = 1.0


NUMBER_DESCRIPTIONS: tuple[VigipoolNumberEntityDescription, ...] = (
    VigipoolNumberEntityDescription(
        key="consigne_ph",
        data_field="consigne_ph",
        data_type_rw="u16_w",
        category="consigne",
        name="pH Setpoint",
        translation_key="ph_setpoint",
        native_min_value=6.8,
        native_max_value=7.6,
        native_step=0.1,
        native_unit_of_measurement="pH",
        mode=NumberMode.SLIDER,
        multiplier_to_device=100.0,
        supported_prefixes=("phileox", "daisyph"),
    ),
    VigipoolNumberEntityDescription(
        key="consigne_orp",
        data_field="consigne_orp",
        data_type_rw="u16_w",
        category="info",
        name="ORP Setpoint",
        translation_key="orp_setpoint",
        native_min_value=300.0,
        native_max_value=990.0,
        native_step=10.0,
        native_unit_of_measurement="mV",
        mode=NumberMode.SLIDER,
        multiplier_to_device=1.0,
        supported_prefixes=("anteam", "daisyox"),
    ),
    VigipoolNumberEntityDescription(
        key="vol_max_24h",
        data_field="vol_max_24h",
        data_type_rw="u16_w",
        category="info",
        name="Max Volume 24h",
        translation_key="max_volume_24h",
        native_min_value=0.0,
        native_max_value=2.0,
        native_step=0.05,
        native_unit_of_measurement="L/day",
        mode=NumberMode.BOX,
        multiplier_to_device=100.0,
        supported_prefixes=("phileox", "daisyph", "daisyox"),
    ),
    VigipoolNumberEntityDescription(
        key="vol_bac",
        data_field="vol_bac",
        data_type_rw="u16_w",
        category="info",
        name="Container Volume",
        translation_key="container_volume",
        native_min_value=0.0,
        native_max_value=50.0,
        native_step=1.0,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        mode=NumberMode.BOX,
        multiplier_to_device=100.0,
        supported_prefixes=("phileox", "daisyph", "daisyox"),
    ),
    VigipoolNumberEntityDescription(
        key="x3_speed",
        data_field="x3_speed",
        data_type_rw="u8_w",
        category="info",
        name="Effect Speed",
        translation_key="effect_speed",
        native_min_value=50.0,
        native_max_value=150.0,
        native_step=10.0,
        native_unit_of_measurement="%",
        mode=NumberMode.SLIDER,
        multiplier_to_device=1.0,
        supported_prefixes=("x312",),
    ),
)


class VigipoolNumber(VigipoolBaseEntity, NumberEntity):
    """Representation of a Vigipool numeric setpoint or parameter."""

    entity_description: VigipoolNumberEntityDescription

    def __init__(
        self,
        coordinator: VigipoolCoordinator,
        device_id: str,
        description: VigipoolNumberEntityDescription,
    ) -> None:
        """Initialize number entity."""
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        """Return current setpoint value."""
        return self.get_device_data(self.entity_description.data_field)

    async def async_set_native_value(self, value: float) -> None:
        """Send new setpoint to device via MQTT."""
        # Calculate raw payload sent to device
        payload_val = int(round(value * self.entity_description.multiplier_to_device))
        # Note: daisyox uses category 'consigne' for consigne_orp while anteam uses 'info'
        cat = self.entity_description.category
        if self.device_id.startswith("daisyox") and self.entity_description.key == "consigne_orp":
            cat = "consigne"

        await self.coordinator.async_send_command(
            self.device_id,
            self.entity_description.data_type_rw,
            self.entity_description.data_field,
            cat,
            str(payload_val),
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vigipool number entities."""
    coordinator: VigipoolCoordinator = hass.data[DOMAIN][entry.entry_id]
    created_entity_ids: set[str] = set()

    def _create_entities_for_device(device_id: str) -> list[NumberEntity]:
        device = coordinator.devices.get(device_id)
        if not device:
            return []

        new_entities: list[NumberEntity] = []
        for description in NUMBER_DESCRIPTIONS:
            if device.prefix in description.supported_prefixes:
                entity_uid = f"{device_id}_{description.key}"
                if entity_uid not in created_entity_ids:
                    created_entity_ids.add(entity_uid)
                    new_entities.append(
                        VigipoolNumber(coordinator, device_id, description)
                    )
        return new_entities

    initial_entities: list[NumberEntity] = []
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
