"""Constants for the CCEI Vigipool integration."""
from __future__ import annotations

import re
from typing import Final

DOMAIN: Final = "vigipool"
MANUFACTURER: Final = "CCEI"

# Configuration keys
CONF_BROKER: Final = "broker"
CONF_PORT: Final = "port"
CONF_PRIMARY_DEVICE_ID: Final = "primary_device_id"
CONF_DISCOVERY_INTERVAL: Final = "discovery_interval"

# Network & MQTT Defaults
DEFAULT_PORT: Final = 1883
DEFAULT_PORT_SCAN_TIMEOUT: Final = 0.8  # seconds for TCP port scan
DEFAULT_MQTT_PROBE_TIMEOUT: Final = 1.5  # seconds to listen for Vigipool topics
DEFAULT_MAX_CONCURRENT_SCANS: Final = 30
DEFAULT_DISCOVERY_INTERVAL: Final = 300  # 5 minutes

# Regular expression matching Vigipool MQTT topics:
# Example: tild_84CCA89E2340/u16_r/value_temp/value/reported
# Group 1: device_type (e.g. tild)
# Group 2: device_mac (e.g. 84CCA89E2340)
# Group 3: data_type (e.g. u16_r, u8_w)
# Group 4: field_name (e.g. value_temp, filt_state)
# Group 5: category (e.g. value, info, consigne)
# Group 6: direction (reported, desired)
VIGIPOOL_TOPIC_REGEX: Final = re.compile(
    r"^([a-zA-Z0-9]+)_([0-9A-Fa-f]{12})/([a-zA-Z0-9]+_[rw])/([a-zA-Z0-9_]+)/([a-zA-Z0-9_]+)/(reported|desired)$"
)

# Known Vigipool device models and URLs
DEVICE_MODELS: Final[dict[str, dict[str, str]]] = {
    "tild": {
        "model": "Tild VP",
        "url": "https://www.ccei-pool.com/fr/produit/tild-vp",
        "description": "Pool electrical controller",
    },
    "ziphox": {
        "model": "Ofix VP",
        "url": "https://www.ccei-pool.com/fr/produit/ofix-vp",
        "description": "Water analyzer & probe",
    },
    "phileox": {
        "model": "Phileo VP",
        "url": "https://www.ccei-pool.com/fr/produit/phileo-vp",
        "description": "pH controller & dosing",
    },
    "daisyph": {
        "model": "Daisy pH",
        "url": "https://www.ccei-pool.com/fr/produit/daisy-vp",
        "description": "pH dosing pump",
    },
    "daisyox": {
        "model": "Daisy OX",
        "url": "https://www.ccei-pool.com/fr/produit/daisy-vp",
        "description": "ORP / Chlorine dosing pump",
    },
    "anteam": {
        "model": "AnteaM",
        "url": "https://www.poolplanet.com/produit/antea-vp-antenne-connectee-a-raccorder-aux-equipements-compatibles",
        "description": "Radio gateway & controller",
    },
    "anteaox": {
        "model": "AnteaOX",
        "url": "https://www.ccei-pool.com/fr/produit/antea-vp",
        "description": "ORP transmitter",
    },
    "anteavs": {
        "model": "AnteaVS",
        "url": "https://www.ccei-pool.com/fr/produit/antea-vs",
        "description": "Variable speed pump controller",
    },
    "lynx": {
        "model": "Lynx VP",
        "url": "https://www.ccei-pool.com/fr/produit/lynx-vp",
        "description": "Dosing dispenser",
    },
    "x312": {
        "model": "VigiBrio",
        "url": "https://www.ccei-pool.com/fr/produit/vigibrio",
        "description": "RGB LED lighting controller",
    },
    "vigiwatt": {
        "model": "VigiW@tt",
        "url": "https://www.ccei-pool.com/fr/produit/vigiwatt",
        "description": "Energy & electrical monitor",
    },
    "vigipool": {
        "model": "Vigipool Gateway",
        "url": "https://www.ccei-pool.com/fr/gamme-vigipool",
        "description": "Vigipool communication hub",
    },
}

# Special sentinel error/offline values returned by sensors
INVALID_RAW_VALUES: Final[set[int]] = {65534, 65535, 0xFFFE, 0xFFFF}
TEMP_ERROR_THRESHOLD: Final = 65530

# VigiBrio effects
VIGIBRIO_EFFECT_LIST: Final[list[str]] = [
    "Rainbow",
    "Fun",
    "Ocean",
    "Flamme",
    "Parade",
    "Bleu nuit",
    "Bleu",
    "Bleu clair",
    "Blanc",
    "Blanc chaud",
    "Vert",
    "Jaune",
    "Orange",
    "Rouge",
    "Rose",
    "Violet",
]

# Mode select options for AnteaM
MODE_OPTIONS_MAP: Final[dict[int, str]] = {
    0: "OFF",
    1: "ON",
    2: "PROG",
    3: "AUTO",
}
MODE_OPTIONS_REVERSE_MAP: Final[dict[str, int]] = {v: k for k, v in MODE_OPTIONS_MAP.items()}

# Signals
SIGNAL_VIGIPOOL_NEW_DEVICE: Final = "vigipool_new_device_{}"
