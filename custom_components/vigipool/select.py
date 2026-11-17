"""Select platform for CCEI Vigipool operating modes and timers."""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time
from typing import Any

try:
    from homeassistant.components.select import SelectEntity, SelectEntityDescription
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.dispatcher import async_dispatcher_connect
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
except ImportError:
    @dataclass(frozen=True, kw_only=True)
    class SelectEntityDescription:
        key: str
        name: str | None = None
        translation_key: str | None = None
        options: list[str] = field(default_factory=list)

    class SelectEntity:
        @property
        def options(self) -> list[str]:
            return getattr(self, "_attr_options", [])

    async_dispatcher_connect = lambda *args: None

from .const import (
    DOMAIN,
    MODE_OPTIONS_MAP,
    MODE_OPTIONS_REVERSE_MAP,
    SIGNAL_VIGIPOOL_NEW_DEVICE,
)
from .coordinator import VigipoolCoordinator
from .entity import VigipoolBaseEntity

_LOGGER = logging.getLogger(__name__)

STANDARD_MODE_OPTIONS: list[str] = ["OFF", "ON", "PROG", "AUTO"]

# Generate 15-minute intervals from 00:00 to 24:45
TIMER_OPTIONS: list[str] = [
    f"{h:02d}:{m:02d}" for h in range(25) for m in (0, 15, 30, 45)
]


@dataclass(frozen=True, kw_only=True)
class VigipoolSelectEntityDescription(SelectEntityDescription):
    """Description for a Vigipool select entity."""

    supported_prefixes: tuple[str, ...] = ()
    data_type_rw: str = "u8_w"
    data_field: str = ""
    category: str = "info"


SELECT_DESCRIPTIONS: tuple[VigipoolSelectEntityDescription, ...] = (
    VigipoolSelectEntityDescription(
        key="filt_mode",
        data_field="filt_mode",
        name="Filtration Mode",
        translation_key="filtration_mode",
        options=STANDARD_MODE_OPTIONS,
        supported_prefixes=("anteam", "anteavs"),
    ),
    VigipoolSelectEntityDescription(
        key="light_mode",
        data_field="light_mode",
        name="Light Mode",
        translation_key="light_mode",
        options=STANDARD_MODE_OPTIONS,
        supported_prefixes=("anteam",),
    ),
    VigipoolSelectEntityDescription(
        key="aux1_mode",
        data_field="aux1_mode",
        name="Auxiliary 1 Mode",
        translation_key="aux1_mode",
        options=STANDARD_MODE_OPTIONS,
        supported_prefixes=("anteam",),
    ),
    VigipoolSelectEntityDescription(
        key="aux2_mode",
        data_field="aux2_mode",
        name="Auxiliary 2 Mode",
        translation_key="aux2_mode",
        options=STANDARD_MODE_OPTIONS,
        supported_prefixes=("anteam",),
    ),
)


class VigipoolModeSelect(VigipoolBaseEntity, SelectEntity):
    """Select entity for operational modes (OFF, ON, PROG, AUTO)."""

    entity_description: VigipoolSelectEntityDescription

    def __init__(
        self,
        coordinator: VigipoolCoordinator,
        device_id: str,
        description: VigipoolSelectEntityDescription,
    ) -> None:
        """Initialize mode select."""
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description
        self._attr_options = description.options

    @property
    def current_option(self) -> str | None:
        """Return currently active mode."""
        val = self.get_device_data(self.entity_description.data_field)
        if isinstance(val, str) and val in self.options:
            return val
        if isinstance(val, int) and val in MODE_OPTIONS_MAP:
            return MODE_OPTIONS_MAP[val]
        return None

    async def async_select_option(self, option: str) -> None:
        """Select mode option."""
        if option in MODE_OPTIONS_REVERSE_MAP:
            code = MODE_OPTIONS_REVERSE_MAP[option]
            await self.coordinator.async_send_command(
                self.device_id,
                self.entity_description.data_type_rw,
                self.entity_description.data_field,
                self.entity_description.category,
                str(code),
            )


class VigipoolTimerSelect(VigipoolBaseEntity, SelectEntity):
    """Select entity for light timer duration."""

    _attr_options = TIMER_OPTIONS
    _attr_translation_key = "light_timer_select"
    _attr_name = "Light Timer"

    def __init__(self, coordinator: VigipoolCoordinator, device_id: str) -> None:
        """Initialize timer select."""
        super().__init__(coordinator, device_id, "light_timer_select")

    @property
    def current_option(self) -> str | None:
        """Return option closest to remaining minutes."""
        mins = self.get_device_data("light_timer")
        if not mins or mins <= 0:
            return "00:00"
        h = int(mins // 60)
        # Round to nearest 15
        m = int(round((mins % 60) / 15.0) * 15)
        if m == 60:
            h += 1
            m = 0
        opt = f"{min(h, 24):02d}:{m:02d}"
        return opt if opt in self.options else "00:00"

    async def async_select_option(self, option: str) -> None:
        """Set timer duration via MQTT."""
        try:
            parts = option.split(":")
            h = int(parts[0])
            m = int(parts[1])
            total_minutes = h * 60 + m
        except Exception:
            total_minutes = 0

        if total_minutes == 0:
            payload = "0"
        else:
            # Send future timestamp as specified by Vigipool protocol
            payload = str(int(time.time()) + (total_minutes * 60))

        await self.coordinator.async_send_command(
            self.device_id,
            "u32_w",
            "light_timer",
            "info",
            payload,
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vigipool select entities."""
    coordinator: VigipoolCoordinator = hass.data[DOMAIN][entry.entry_id]
    created_entity_ids: set[str] = set()

    def _create_entities_for_device(device_id: str) -> list[SelectEntity]:
        device = coordinator.devices.get(device_id)
        if not device:
            return []

        new_entities: list[SelectEntity] = []
        for description in SELECT_DESCRIPTIONS:
            if device.prefix in description.supported_prefixes:
                entity_uid = f"{device_id}_{description.key}"
                if entity_uid not in created_entity_ids:
                    created_entity_ids.add(entity_uid)
                    new_entities.append(
                        VigipoolModeSelect(coordinator, device_id, description)
                    )

        if device.prefix == "x312":
            uid = f"{device_id}_light_timer_select"
            if uid not in created_entity_ids:
                created_entity_ids.add(uid)
                new_entities.append(VigipoolTimerSelect(coordinator, device_id))

        return new_entities

    initial_entities: list[SelectEntity] = []
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
