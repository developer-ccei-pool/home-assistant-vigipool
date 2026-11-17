"""Catalogue of Vigipool MQTT fields and their real capabilities.

Every entry maps a field that Vigipool equipment actually publishes on topics
``{prefix}_{mac}/{type}/{field}/{category}/{reported|desired}`` to the entity
that represents it in Home Assistant. Fields are derived from the values the
coordinator already parses (see ``VigipoolCoordinator._parse_field_value``):
nothing is invented here, and no command is offered for fields whose operation
is not documented.

Only read-only entity kinds (sensor / binary_sensor) are generated from this
catalogue. Writable controls (switch, number, select, light) keep using the
hand-written per-model platform descriptions, whose MQTT behaviour is
documented in the project README.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, kw_only=True)
class FieldSpec:
    """Neutral description of a Vigipool MQTT field."""

    platform: str  # "sensor" or "binary_sensor"
    name: str
    native_unit_of_measurement: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    icon: str | None = None
    entity_category: str | None = None


# Fields actually published by Vigipool equipment (see coordinator parser).
FIELD_SPECS: dict[str, FieldSpec] = {
    # --- Water measurements -------------------------------------------------
    "value_temp": FieldSpec(
        platform="sensor",
        name="Water Temperature",
        native_unit_of_measurement="°C",
        device_class="temperature",
        state_class="measurement",
        icon="mdi:thermometer-water",
    ),
    "value_ph": FieldSpec(
        platform="sensor",
        name="pH Value",
        device_class="ph",
        state_class="measurement",
        icon="mdi:ph",
    ),
    "value_orp": FieldSpec(
        platform="sensor",
        name="ORP Value",
        native_unit_of_measurement="mV",
        state_class="measurement",
        icon="mdi:water-check",
    ),
    # --- Setpoint states (read-only mirrors of the configured setpoints) ----
    "consigne_ph": FieldSpec(
        platform="sensor",
        name="pH Setpoint",
        device_class="ph",
        state_class="measurement",
        icon="mdi:ph",
    ),
    "consigne_orp": FieldSpec(
        platform="sensor",
        name="ORP Setpoint",
        native_unit_of_measurement="mV",
        state_class="measurement",
        icon="mdi:water-check",
    ),
    # --- Dosing volumes ------------------------------------------------------
    "vol_24h_inject": FieldSpec(
        platform="sensor",
        name="Injected Volume 24h",
        native_unit_of_measurement="L",
        state_class="measurement",
        icon="mdi:beaker-outline",
    ),
    "vol_tot_inject": FieldSpec(
        platform="sensor",
        name="Total Injected Volume",
        native_unit_of_measurement="L",
        state_class="total_increasing",
        icon="mdi:beaker-outline",
    ),
    "vol_bac": FieldSpec(
        platform="sensor",
        name="Container Volume",
        native_unit_of_measurement="L",
        state_class="measurement",
        icon="mdi:can-outline",
    ),
    "vol_max_24h": FieldSpec(
        platform="sensor",
        name="Max Volume 24h",
        native_unit_of_measurement="L",
        state_class="measurement",
        icon="mdi:arrow-up-bold-circle-outline",
    ),
    # --- Electrical measurements (VigiW@tt) ----------------------------------
    "watt_ind": FieldSpec(
        platform="sensor",
        name="Power",
        native_unit_of_measurement="W",
        device_class="power",
        state_class="measurement",
        icon="mdi:flash",
    ),
    "volt": FieldSpec(
        platform="sensor",
        name="Voltage",
        native_unit_of_measurement="V",
        device_class="voltage",
        state_class="measurement",
        icon="mdi:sine-wave",
    ),
    "amp": FieldSpec(
        platform="sensor",
        name="Current",
        native_unit_of_measurement="A",
        device_class="current",
        state_class="measurement",
        icon="mdi:current-ac",
    ),
    "freq": FieldSpec(
        platform="sensor",
        name="Frequency",
        native_unit_of_measurement="Hz",
        device_class="frequency",
        state_class="measurement",
        icon="mdi:sine-wave",
    ),
    "pf": FieldSpec(
        platform="sensor",
        name="Power Factor",
        native_unit_of_measurement="%",
        state_class="measurement",
        icon="mdi:angle-acute",
    ),
    # --- Lighting state (read-only mirrors) ----------------------------------
    "light_bright": FieldSpec(
        platform="sensor",
        name="Light Brightness",
        native_unit_of_measurement="%",
        state_class="measurement",
        icon="mdi:brightness-percent",
    ),
    "x3_bright": FieldSpec(
        platform="sensor",
        name="Light Brightness",
        native_unit_of_measurement="%",
        state_class="measurement",
        icon="mdi:brightness-percent",
    ),
    "x3_speed": FieldSpec(
        platform="sensor",
        name="Effect Speed",
        native_unit_of_measurement="%",
        state_class="measurement",
        icon="mdi:speedometer",
    ),
    "x3_color": FieldSpec(
        platform="sensor",
        name="Light Effect",
        icon="mdi:palette",
    ),
    "light_timer": FieldSpec(
        platform="sensor",
        name="Light Timer Remaining",
        native_unit_of_measurement="min",
        state_class="measurement",
        icon="mdi:timer-outline",
    ),
    # --- Operating mode states (read-only mirrors of the mode selects) ------
    "filt_mode": FieldSpec(
        platform="sensor",
        name="Filtration Mode",
        icon="mdi:pump",
    ),
    "light_mode": FieldSpec(
        platform="sensor",
        name="Light Mode",
        icon="mdi:lightbulb-on-outline",
    ),
    "aux1_mode": FieldSpec(
        platform="sensor",
        name="Auxiliary 1 Mode",
        icon="mdi:toggle-switch-outline",
    ),
    "aux2_mode": FieldSpec(
        platform="sensor",
        name="Auxiliary 2 Mode",
        icon="mdi:toggle-switch-outline",
    ),
    # --- Diagnostics ----------------------------------------------------------
    "rssi": FieldSpec(
        platform="sensor",
        name="Signal Strength",
        native_unit_of_measurement="dBm",
        device_class="signal_strength",
        state_class="measurement",
        entity_category="diagnostic",
    ),
    "serial_num": FieldSpec(
        platform="sensor",
        name="Serial Number",
        entity_category="diagnostic",
        icon="mdi:numeric",
    ),
    "sw_vers": FieldSpec(
        platform="sensor",
        name="Firmware Version",
        entity_category="diagnostic",
        icon="mdi:chip",
    ),
    "hw_vers": FieldSpec(
        platform="sensor",
        name="Hardware Version",
        entity_category="diagnostic",
        icon="mdi:chip",
    ),
    "meter_sn": FieldSpec(
        platform="sensor",
        name="Meter Serial Number",
        entity_category="diagnostic",
        icon="mdi:counter",
    ),
    "meter_sw": FieldSpec(
        platform="sensor",
        name="Meter Firmware Version",
        entity_category="diagnostic",
        icon="mdi:counter",
    ),
    # --- Binary states ---------------------------------------------------------
    "filt_state": FieldSpec(
        platform="binary_sensor",
        name="Filtration",
        device_class="running",
        icon="mdi:pump",
    ),
    "light_state": FieldSpec(
        platform="binary_sensor",
        name="Light",
        device_class="power",
        icon="mdi:lightbulb",
    ),
    "x3_state": FieldSpec(
        platform="binary_sensor",
        name="Light",
        device_class="power",
        icon="mdi:lightbulb",
    ),
    "aux_conf": FieldSpec(
        platform="binary_sensor",
        name="Auxiliary Output",
        device_class="power",
        icon="mdi:electric-switch",
    ),
    "flow_on": FieldSpec(
        platform="binary_sensor",
        name="Water Flow",
        device_class="running",
        icon="mdi:water-pump",
    ),
    "inject_on": FieldSpec(
        platform="binary_sensor",
        name="Injecting Product",
        device_class="running",
        icon="mdi:syringe",
    ),
}

# Internal coordinator metadata keys are never exposed as entities.
METADATA_SUFFIXES: tuple[str, ...] = ("_raw", "_ts", "_direction")

# Fields covered by hand-written writable entities in the platform files,
# per device prefix. Dynamic entities are never created for those pairs to
# avoid duplicate entities for the same physical value.
WRITABLE_FIELD_COVERAGE: dict[str, dict[str, set[str]]] = {
    "light": {
        "tild": {"light_state", "light_bright"},
        "x312": {"x3_state", "x3_bright", "x3_color", "x3_speed"},
    },
    "switch": {
        "tild": {"filt_state", "aux_conf"},
    },
    "number": {
        "phileox": {"consigne_ph", "vol_max_24h", "vol_bac"},
        "daisyph": {"consigne_ph", "vol_max_24h", "vol_bac"},
        "daisyox": {"consigne_orp", "vol_max_24h", "vol_bac"},
        "anteam": {"consigne_orp"},
        "x312": {"x3_speed"},
    },
    "select": {
        "anteam": {"filt_mode", "light_mode", "aux1_mode", "aux2_mode"},
        "anteavs": {"filt_mode"},
        "x312": {"light_timer"},
    },
}


def is_metadata_field(field_name: str) -> bool:
    """Return True for coordinator bookkeeping keys, never shown as entities."""
    return field_name.endswith(METADATA_SUFFIXES)


def field_already_covered(prefix: str, field_name: str) -> bool:
    """Return True when a writable entity already manages this field."""
    for coverage in WRITABLE_FIELD_COVERAGE.values():
        if field_name in coverage.get(prefix, set()):
            return True
    return False


def spec_for_field(field_name: str) -> FieldSpec | None:
    """Return the capability spec of a received field, if known."""
    return FIELD_SPECS.get(field_name)


def entity_payload(spec: FieldSpec) -> dict[str, Any]:
    """Return the keyword arguments used to build a sensor description."""
    kwargs: dict[str, Any] = {
        "name": spec.name,
        "native_unit_of_measurement": spec.native_unit_of_measurement,
        "device_class": spec.device_class,
        "state_class": spec.state_class,
        "icon": spec.icon,
        "entity_category": spec.entity_category,
    }
    return kwargs


def binary_sensor_payload(spec: FieldSpec) -> dict[str, Any]:
    """Return the keyword arguments accepted by BinarySensorEntityDescription.

    Binary sensors in Home Assistant carry no unit of measurement and no
    state class, so those fields are deliberately dropped.
    """
    return {
        "name": spec.name,
        "device_class": spec.device_class,
        "icon": spec.icon,
        "entity_category": spec.entity_category,
    }
