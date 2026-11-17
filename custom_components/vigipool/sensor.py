"""Sensor platform for CCEI Vigipool integration."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Callable

try:
    from homeassistant.components.sensor import (
        SensorDeviceClass,
        SensorEntity,
        SensorEntityDescription,
        SensorStateClass,
    )
    from homeassistant.const import (
        SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        UnitOfElectricCurrent,
        UnitOfElectricPotential,
        UnitOfEnergy,
        UnitOfFrequency,
        UnitOfPower,
        UnitOfTemperature,
        UnitOfTime,
        UnitOfVolume,
    )
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers.dispatcher import async_dispatcher_connect
    from homeassistant.helpers.entity import EntityCategory
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
except ImportError:
    # Standalone mock definitions for tests
    @dataclass(frozen=True, kw_only=True)
    class SensorEntityDescription:
        key: str
        name: str | None = None
        translation_key: str | None = None
        native_unit_of_measurement: str | None = None
        device_class: Any | None = None
        state_class: Any | None = None
        icon: str | None = None
        entity_category: Any | None = None

    class SensorDeviceClass:
        TEMPERATURE = "temperature"
        PH = "ph"
        SIGNAL_STRENGTH = "signal_strength"
        POWER = "power"
        ENERGY = "energy"
        VOLTAGE = "voltage"
        CURRENT = "current"
        FREQUENCY = "frequency"
        TIMESTAMP = "timestamp"

    class SensorStateClass:
        MEASUREMENT = "measurement"
        TOTAL_INCREASING = "total_increasing"

    class EntityCategory:
        DIAGNOSTIC = "diagnostic"

    UnitOfTemperature = type("UnitOfTemperature", (), {"CELSIUS": "°C"})
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT = "dBm"
    UnitOfPower = type("UnitOfPower", (), {"WATT": "W"})
    UnitOfEnergy = type("UnitOfEnergy", (), {"WATT_HOUR": "Wh"})
    UnitOfElectricPotential = type("UnitOfElectricPotential", (), {"VOLT": "V"})
    UnitOfElectricCurrent = type("UnitOfElectricCurrent", (), {"AMPERE": "A"})
    UnitOfFrequency = type("UnitOfFrequency", (), {"HERTZ": "Hz"})
    UnitOfVolume = type("UnitOfVolume", (), {"LITERS": "L"})
    UnitOfTime = type("UnitOfTime", (), {"MINUTES": "min"})

    class SensorEntity:
        @property
        def native_unit_of_measurement(self):
            return self.entity_description.native_unit_of_measurement

        @property
        def device_class(self):
            return self.entity_description.device_class

    er = None

    async_dispatcher_connect = lambda *args: None

from .capabilities import (
    entity_payload,
    field_already_covered,
    is_metadata_field,
    spec_for_field,
)
from .const import DOMAIN, SIGNAL_VIGIPOOL_NEW_DEVICE, SIGNAL_VIGIPOOL_NEW_FIELD
from .coordinator import VigipoolCoordinator
from .discovery import DiscoveredDevice
from .entity import VigipoolBaseEntity, VigipoolHubBaseEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class VigipoolSensorEntityDescription(SensorEntityDescription):
    """Description for a Vigipool sensor entity."""

    supported_prefixes: tuple[str, ...] = ()
    data_field: str = ""


# Sensor definitions mapped by data field
SENSOR_DESCRIPTIONS: tuple[VigipoolSensorEntityDescription, ...] = (
    VigipoolSensorEntityDescription(
        key="value_temp",
        data_field="value_temp",
        name="Water Temperature",
        translation_key="water_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        supported_prefixes=("tild", "ziphox", "anteam"),
    ),
    VigipoolSensorEntityDescription(
        key="value_ph",
        data_field="value_ph",
        name="pH Value",
        translation_key="ph_value",
        device_class=SensorDeviceClass.PH,
        state_class=SensorStateClass.MEASUREMENT,
        supported_prefixes=("ziphox", "phileox", "anteam"),
    ),
    VigipoolSensorEntityDescription(
        key="value_orp",
        data_field="value_orp",
        name="ORP Value",
        translation_key="orp_value",
        native_unit_of_measurement="mV",
        state_class=SensorStateClass.MEASUREMENT,
        supported_prefixes=("ziphox", "anteam", "anteaox", "daisyox"),
    ),
    VigipoolSensorEntityDescription(
        key="rssi",
        data_field="rssi",
        name="Signal Strength",
        translation_key="rssi",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        supported_prefixes=("tild", "ziphox", "phileox", "daisyox", "anteam"),
    ),
    VigipoolSensorEntityDescription(
        key="vol_24h_inject",
        data_field="vol_24h_inject",
        name="Injected Volume 24h",
        translation_key="injected_volume_24h",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        supported_prefixes=("daisyph", "lynx", "phileox"),
    ),
    VigipoolSensorEntityDescription(
        key="vol_tot_inject",
        data_field="vol_tot_inject",
        name="Total Injected Volume",
        translation_key="total_injected_volume",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        supported_prefixes=("daisyph", "lynx", "phileox"),
    ),
    VigipoolSensorEntityDescription(
        key="watt_ind",
        data_field="watt_ind",
        name="Power",
        translation_key="power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        supported_prefixes=("vigiwatt",),
    ),
    VigipoolSensorEntityDescription(
        key="volt",
        data_field="volt",
        name="Voltage",
        translation_key="voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        supported_prefixes=("vigiwatt",),
    ),
    VigipoolSensorEntityDescription(
        key="amp",
        data_field="amp",
        name="Current",
        translation_key="current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        supported_prefixes=("vigiwatt",),
    ),
    VigipoolSensorEntityDescription(
        key="freq",
        data_field="freq",
        name="Frequency",
        translation_key="frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        supported_prefixes=("vigiwatt",),
    ),
    VigipoolSensorEntityDescription(
        key="pf",
        data_field="pf",
        name="Power Factor",
        translation_key="power_factor",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        supported_prefixes=("vigiwatt",),
    ),
    VigipoolSensorEntityDescription(
        key="serial_num",
        data_field="serial_num",
        name="Serial Number",
        translation_key="serial_number",
        entity_category=EntityCategory.DIAGNOSTIC,
        supported_prefixes=("tild", "ziphox", "phileox", "daisyox", "anteam"),
    ),
    VigipoolSensorEntityDescription(
        key="sw_vers",
        data_field="sw_vers",
        name="Firmware Version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        supported_prefixes=("phileox",),
    ),
    VigipoolSensorEntityDescription(
        key="hw_vers",
        data_field="hw_vers",
        name="Hardware Version",
        translation_key="hardware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        supported_prefixes=("phileox",),
    ),
    VigipoolSensorEntityDescription(
        key="light_timer",
        data_field="light_timer",
        name="Light Timer Remaining",
        translation_key="light_timer_remaining",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        supported_prefixes=("x312",),
    ),
)


class VigipoolSensor(VigipoolBaseEntity, SensorEntity):
    """Representation of a Vigipool sensor."""

    entity_description: VigipoolSensorEntityDescription

    def __init__(
        self,
        coordinator: VigipoolCoordinator,
        device_id: str,
        description: VigipoolSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the current sensor value."""
        val = self.get_device_data(self.entity_description.data_field)
        return val


class VigipoolHubStatusSensor(VigipoolHubBaseEntity, SensorEntity):
    """Hub diagnostic sensor for MQTT broker connection status."""

    def __init__(self, coordinator: VigipoolCoordinator) -> None:
        """Initialize gateway connection sensor."""
        super().__init__(coordinator, "connection_state")
        self._attr_name = "Connection State"
        self._attr_translation_key = "gateway_connection_state"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str:
        """Return current connection state string."""
        return self.coordinator.mqtt_client.state.value


class VigipoolHubDevicesSensor(VigipoolHubBaseEntity, SensorEntity):
    """Hub diagnostic sensor reporting the count of active Vigipool devices."""

    def __init__(self, coordinator: VigipoolCoordinator) -> None:
        """Initialize device counter sensor."""
        super().__init__(coordinator, "device_count")
        self._attr_name = "Connected Devices Count"
        self._attr_translation_key = "device_count"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> int:
        """Return number of discovered devices."""
        return len(self.coordinator.devices)


class VigipoolHubLastCommSensor(VigipoolHubBaseEntity, SensorEntity):
    """Hub diagnostic sensor for last received communication timestamp."""

    def __init__(self, coordinator: VigipoolCoordinator) -> None:
        """Initialize last communication sensor."""
        super().__init__(coordinator, "last_communication")
        self._attr_name = "Last Communication"
        self._attr_translation_key = "last_communication"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> datetime | None:
        """Return ISO timestamp of last MQTT message."""
        ts = self.coordinator.last_communication
        if ts is None:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vigipool sensor entities."""
    coordinator: VigipoolCoordinator = hass.data[DOMAIN][entry.entry_id]

    created_entity_ids: set[str] = set()

    def _create_entities_for_device(device_id: str) -> list[SensorEntity]:
        device = coordinator.devices.get(device_id)
        if not device:
            return []

        new_entities: list[SensorEntity] = []
        for description in SENSOR_DESCRIPTIONS:
            if device.prefix in description.supported_prefixes:
                entity_uid = f"{device_id}_{description.key}"
                if entity_uid not in created_entity_ids:
                    created_entity_ids.add(entity_uid)
                    new_entities.append(
                        VigipoolSensor(coordinator, device_id, description)
                    )

        # Sensors built from fields actually received over MQTT. This covers
        # models with no static description (e.g. Tildrc) without inventing
        # entities for data that is never published.
        for field_name in coordinator.data.get(device_id, {}):
            entity = _dynamic_sensor_for(device_id, device, field_name)
            if entity is not None:
                new_entities.append(entity)
        return new_entities

    def _dynamic_sensor_for(
        device_id: str, device: DiscoveredDevice, field_name: str
    ) -> VigipoolSensor | None:
        """Build a read-only sensor for a field really received via MQTT."""
        if is_metadata_field(field_name) or field_already_covered(
            device.prefix, field_name
        ):
            return None
        spec = spec_for_field(field_name)
        if spec is None or spec.platform != "sensor":
            return None
        entity_uid = f"{device_id}_{field_name}"
        if entity_uid in created_entity_ids:
            return None
        registry = er.async_get(hass) if er is not None else None
        if registry is not None and registry.async_get_entity_id(
            "sensor", DOMAIN, entity_uid
        ):
            # Entity already exists in Home Assistant: never duplicate it.
            created_entity_ids.add(entity_uid)
            return None
        created_entity_ids.add(entity_uid)
        description = VigipoolSensorEntityDescription(
            key=field_name,
            data_field=field_name,
            supported_prefixes=(device.prefix,),
            **entity_payload(spec),
        )
        return VigipoolSensor(coordinator, device_id, description)

    # Add Hub diagnostics
    hub_entities: list[SensorEntity] = [
        VigipoolHubStatusSensor(coordinator),
        VigipoolHubDevicesSensor(coordinator),
        VigipoolHubLastCommSensor(coordinator),
    ]
    async_add_entities(hub_entities)

    # Add existing devices
    initial_entities: list[SensorEntity] = []
    for dev_id in coordinator.devices:
        initial_entities.extend(_create_entities_for_device(dev_id))
    if initial_entities:
        async_add_entities(initial_entities)

    # Listen for new devices dynamically detected over MQTT
    def _on_new_device(new_device_id: str) -> None:
        entities = _create_entities_for_device(new_device_id)
        if entities:
            async_add_entities(entities)

    # Listen for MQTT fields seen for the first time on a known device, to
    # create the matching sensor at runtime (only for documented capabilities).
    def _on_new_field(device_id: str, field_name: str) -> None:
        device = coordinator.devices.get(device_id)
        if not device:
            return
        entity = _dynamic_sensor_for(device_id, device, field_name)
        if entity is not None:
            async_add_entities([entity])

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_VIGIPOOL_NEW_DEVICE.format(entry.entry_id),
            _on_new_device,
        )
    )
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_VIGIPOOL_NEW_FIELD.format(entry.entry_id),
            _on_new_field,
        )
    )
