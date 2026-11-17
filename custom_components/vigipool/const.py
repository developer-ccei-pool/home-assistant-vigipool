"""Constants for the CCEI Vigipool integration."""
from __future__ import annotations

import re
from typing import Final

DOMAIN: Final = "vigipool"
MANUFACTURER: Final = "CCEI"

CONF_BROKER: Final = "broker"
CONF_PORT: Final = "port"
CONF_PRIMARY_DEVICE_ID: Final = "primary_device_id"
CONF_DISCOVERY_INTERVAL: Final = "discovery_interval"

DEFAULT_PORT: Final = 1883
DEFAULT_PORT_SCAN_TIMEOUT: Final = 1.2
DEFAULT_HTTP_PROBE_TIMEOUT: Final = 2.0
DEFAULT_MQTT_PROBE_TIMEOUT: Final = 1.5
DEFAULT_MAX_CONCURRENT_SCANS: Final = 30
DEFAULT_DISCOVERY_INTERVAL: Final = 300

# Exact body returned by the HTTP root page of a physical Vigipool device.
VIGIPOOL_HTTP_SIGNATURE: Final = "File does not exist"

VIGIPOOL_TOPIC_REGEX: Final = re.compile(
    r"^([a-zA-Z0-9]+)_([0-9A-Fa-f]{12})/([a-zA-Z0-9]+_[rw])/([a-zA-Z0-9_]+)/([a-zA-Z0-9_]+)/(reported|desired)$"
)

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
    "tildrc": {
        "model": "Tildrc",
        "url": "https://www.ccei-pool.com/fr/gamme-vigipool",
        "description": "Pool remote controller",
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

INVALID_RAW_VALUES: Final[set[int]] = {65534, 65535, 0xFFFE, 0xFFFF}
TEMP_ERROR_THRESHOLD: Final = 65530

VIGIBRIO_EFFECT_LIST: Final[list[str]] = [
    "Rainbow", "Fun", "Ocean", "Flamme", "Parade", "Bleu nuit", "Bleu",
    "Bleu clair", "Blanc", "Blanc chaud", "Vert", "Jaune", "Orange",
    "Rouge", "Rose", "Violet",
]

MODE_OPTIONS_MAP: Final[dict[int, str]] = {
    0: "OFF", 1: "ON", 2: "PROG", 3: "AUTO",
}
MODE_OPTIONS_REVERSE_MAP: Final[dict[str, int]] = {
    v: k for k, v in MODE_OPTIONS_MAP.items()
}

SIGNAL_VIGIPOOL_NEW_DEVICE: Final = "vigipool_new_device_{}"
SIGNAL_VIGIPOOL_NEW_FIELD: Final = "vigipool_new_field_{}"
