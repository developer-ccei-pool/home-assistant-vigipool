"""Data update coordinator for Vigipool devices and MQTT data dispatching."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import time
from typing import Any, Callable

from .const import (
    CONF_BROKER,
    CONF_DISCOVERY_INTERVAL,
    DEFAULT_DISCOVERY_INTERVAL,
    DEFAULT_PORT,
    DEVICE_MODELS,
    DOMAIN,
    INVALID_RAW_VALUES,
    MODE_OPTIONS_MAP,
    SIGNAL_VIGIPOOL_NEW_DEVICE,
    TEMP_ERROR_THRESHOLD,
    VIGIPOOL_TOPIC_REGEX,
)
from .discovery import DiscoveredDevice, async_discover_vigipool_brokers
from .mqtt import ConnectionState, VigipoolMqttClient

try:
    from homeassistant.helpers.dispatcher import async_dispatcher_send
except ImportError:
    async_dispatcher_send = lambda *args: None

_LOGGER = logging.getLogger(__name__)


def safe_float(val: Any) -> float | None:
    """Safely convert value to float, returning None on failure or special error codes."""
    if val is None or val in ("", "-", "Error"):
        return None
    try:
        f = float(val)
        if int(f) in INVALID_RAW_VALUES:
            return None
        return f
    except (ValueError, TypeError):
        return None


def safe_int(val: Any) -> int | None:
    """Safely convert value to int, returning None on failure or special error codes."""
    if val is None or val in ("", "-", "Error"):
        return None
    try:
        i = int(float(val))
        if i in INVALID_RAW_VALUES:
            return None
        return i
    except (ValueError, TypeError):
        return None


class VigipoolCoordinator:
    """Coordinates MQTT communication and maintains state of all Vigipool equipment."""

    def __init__(
        self,
        hass: Any,
        entry: Any,
        host: str,
        port: int = DEFAULT_PORT,
        primary_device_id: str = "",
    ) -> None:
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        self._host = host
        self._port = port
        self.primary_device_id = primary_device_id

        # Mapping: device_id -> DiscoveredDevice
        self.devices: dict[str, DiscoveredDevice] = {}

        # Mapping: device_id -> { field_name -> parsed_value }
        self.data: dict[str, dict[str, Any]] = {}

        # Listeners: device_id -> set of callbacks
        self._listeners: dict[str, set[Callable[[], None]]] = {}

        # MQTT Client
        self.mqtt_client = VigipoolMqttClient(
            host=host,
            port=port,
            on_message_callback=self._handle_mqtt_message,
            on_state_change_callback=self._handle_connection_change,
        )

        self._rediscovery_task: asyncio.Task | None = None
        self._is_closing = False
        self._last_state_change: float = time.time()

    @property
    def host(self) -> str:
        """Return broker host."""
        return self._host

    @property
    def port(self) -> int:
        """Return broker port."""
        return self._port

    @property
    def is_connected(self) -> bool:
        """Return True if MQTT client is connected."""
        return self.mqtt_client.is_connected

    @property
    def last_communication(self) -> float | None:
        """Return timestamp of last received MQTT message."""
        return self.mqtt_client.last_communication

    @property
    def broker_device_id(self) -> str:
        """Return stable identifier for the Vigipool broker/hub."""
        if self.primary_device_id:
            return f"hub_{self.primary_device_id}"
        return f"hub_{self._host.replace('.', '_')}"

    def register_listener(self, device_id: str, callback: Callable[[], None]) -> Callable[[], None]:
        """Register entity callback when device data updates."""
        if device_id not in self._listeners:
            self._listeners[device_id] = set()
        self._listeners[device_id].add(callback)

        def unsubscribe() -> None:
            if device_id in self._listeners:
                self._listeners[device_id].discard(callback)

        return unsubscribe

    def _notify_listeners(self, device_id: str) -> None:
        """Notify registered entities for this device."""
        if device_id in self._listeners:
            for callback in list(self._listeners[device_id]):
                try:
                    callback()
                except Exception as err:
                    _LOGGER.error("Error invoking listener callback for %s: %s", device_id, err)

    def _notify_all(self) -> None:
        """Notify all listeners across all devices."""
        for device_id in list(self._listeners.keys()):
            self._notify_listeners(device_id)

    def _handle_connection_change(self, state: ConnectionState) -> None:
        """Handle MQTT connection state transition."""
        self._last_state_change = time.time()
        self._notify_all()

    def _handle_mqtt_message(self, topic: str, payload: str) -> None:
        """Process incoming MQTT message."""
        match = VIGIPOOL_TOPIC_REGEX.match(topic)
        if not match:
            return

        prefix = match.group(1).lower()
        mac = match.group(2).upper()
        data_type = match.group(3).lower()
        field_name = match.group(4).lower()
        category = match.group(5).lower()
        direction = match.group(6).lower()

        device_id = f"{prefix}_{mac}"

        # Register device if not yet tracked
        is_new_device = False
        if device_id not in self.devices:
            model_info = DEVICE_MODELS.get(
                prefix,
                {
                    "model": f"Vigipool {prefix.capitalize()}",
                    "url": "https://www.ccei-pool.com/fr/gamme-vigipool",
                    "description": "Vigipool device",
                },
            )
            self.devices[device_id] = DiscoveredDevice(
                device_id=device_id,
                prefix=prefix,
                mac=mac,
                model=model_info["model"],
                description=model_info["description"],
                url=model_info["url"],
            )
            self.data[device_id] = {}
            is_new_device = True
            _LOGGER.info("Detected Vigipool device: %s (%s)", device_id, model_info["model"])

        device = self.devices[device_id]
        device.last_seen = time.time()

        # Parse value based on field name and type
        parsed_val = self._parse_field_value(field_name, data_type, category, direction, payload)

        # Store in device data
        self.data[device_id][field_name] = parsed_val
        self.data[device_id][f"{field_name}_raw"] = payload
        self.data[device_id][f"{field_name}_ts"] = time.time()
        self.data[device_id][f"{field_name}_direction"] = direction

        # Update metadata if serial, device_id, sw_vers, or hw_vers
        if field_name == "serial_num" and payload:
            device.info["serial_number"] = payload
        elif field_name == "sw_vers" and payload:
            device.info["sw_version"] = str(parsed_val) if parsed_val is not None else payload
        elif field_name == "hw_vers" and payload:
            device.info["hw_version"] = str(parsed_val) if parsed_val is not None else payload
        elif field_name == "meter_sn" and payload:
            device.info["serial_number"] = payload
        elif field_name == "meter_sw" and payload:
            device.info["sw_version"] = payload

        # Notify listeners
        self._notify_listeners(device_id)

        # If a new device was discovered, dispatch HA signal to create entities
        if is_new_device:
            signal_name = SIGNAL_VIGIPOOL_NEW_DEVICE.format(self.entry.entry_id)
            async_dispatcher_send(self.hass, signal_name, device_id)

    def _parse_field_value(
        self, field_name: str, data_type: str, category: str, direction: str, raw: str
    ) -> Any:
        """Parse raw MQTT payload into typed Python representation."""
        clean_raw = raw.strip()

        # Check sentinel error values
        if clean_raw in ("-", "Error", "65534", "65535"):
            return None

        # 1. Temperature
        if "temp" in field_name:
            f = safe_float(clean_raw)
            if f is None or f > TEMP_ERROR_THRESHOLD:
                return None
            # If value > 60.0 (e.g. 245 for 24.5°C), scale by 0.1
            if f > 60.0:
                return round(f * 0.1, 1)
            return round(f, 1)

        # 2. pH value & setpoint
        if "ph" in field_name and "mode" not in field_name:
            f = safe_float(clean_raw)
            if f is None:
                return None
            # Vigipool sends pH either as 7.2 or 720 (scaled by 100)
            if f > 20.0:
                return round(f * 0.01, 2)
            return round(f, 2)

        # 3. ORP value & setpoint
        if "orp" in field_name:
            return safe_int(clean_raw)

        # 4. RSSI
        if field_name == "rssi":
            return safe_int(clean_raw)

        # 5. Filtration, light, aux switch states
        if field_name in ("filt_state", "light_state", "x3_state"):
            val = safe_int(clean_raw)
            if val is None:
                return None
            return val == 1

        # 6. Auxiliary bitmask (bit 0 = ON/OFF)
        if field_name == "aux_conf":
            val = safe_int(clean_raw)
            if val is None:
                return None
            return (val % 2) == 1

        # 7. Flow & Injecting binary sensors
        if field_name in ("flow_on", "inject_on"):
            val = safe_int(clean_raw)
            if val is None:
                return None
            return val == 1

        # 8. Brightness & speed (percentages 0..100 or 50..150)
        if field_name in ("light_bright", "x3_bright", "x3_speed"):
            return safe_int(clean_raw)

        # 9. Modes (light_mode, filt_mode, aux1_mode, aux2_mode)
        if field_name in ("light_mode", "filt_mode", "aux1_mode", "aux2_mode"):
            val = safe_int(clean_raw)
            if val is not None and val in MODE_OPTIONS_MAP:
                return MODE_OPTIONS_MAP[val]
            return clean_raw

        # 10. Volume (vol_24h, vol_tot, vol_bac, vol_max_24h)
        if "vol" in field_name:
            f = safe_float(clean_raw)
            if f is None:
                return None
            # Template uses float(val) * 0.01 for volumes in Liters
            if f > 20.0 and field_name in ("vol_max_24h", "vol_bac"):
                return round(f * 0.01, 2)
            return round(f, 2)

        # 11. Electrical parameters (VigiWatt)
        if field_name == "amp":
            f = safe_float(clean_raw)
            return round(f * 0.1, 2) if f is not None else None
        if field_name in ("watt_ind", "volt", "freq", "pf"):
            return safe_float(clean_raw)

        # 12. Firmware version formatting (e.g. hex float representation)
        if field_name == "sw_vers":
            try:
                i = int(clean_raw)
                hex_str = f"{i:x}"
                return f"{int(hex_str) / 100:.2f}"
            except Exception:
                return clean_raw

        # 13. Light timer remaining (seconds / timestamp to minutes)
        if field_name == "light_timer":
            val = safe_int(clean_raw)
            if val is None or val == 0:
                return 0
            # If timestamp in future, compute minutes remaining
            now_ts = int(time.time())
            if val > now_ts:
                return int((val - now_ts) / 60) + 1
            return val

        # Default string return
        return clean_raw

    async def async_send_command(
        self,
        device_id: str,
        data_type_rw: str,
        field_name: str,
        category: str,
        value: Any,
    ) -> bool:
        """Send a desired state / command to a Vigipool device.

        Topic structure: {device_id}/{data_type_rw}/{field_name}/{category}/desired
        """
        topic = f"{device_id}/{data_type_rw}/{field_name}/{category}/desired"
        return await self.mqtt_client.async_publish(topic, value)

    async def async_start(self) -> bool:
        """Start coordinator and connect to MQTT broker."""
        self._is_closing = False
        connected = await self.mqtt_client.async_connect()
        # Always subscribe to '#' so all Vigipool devices and metrics are captured
        await self.mqtt_client.async_subscribe("#")

        # Launch periodic rediscovery background task if interval configured
        interval = self.entry.options.get(CONF_DISCOVERY_INTERVAL, DEFAULT_DISCOVERY_INTERVAL)
        if interval > 0:
            self._rediscovery_task = asyncio.create_task(self._async_periodic_check(interval))

        return connected

    async def async_stop(self) -> None:
        """Stop coordinator and cleanly disconnect."""
        self._is_closing = True
        if self._rediscovery_task and not self._rediscovery_task.done():
            self._rediscovery_task.cancel()
        await self.mqtt_client.async_disconnect()

    async def _async_periodic_check(self, interval: int) -> None:
        """Periodically verify connectivity and attempt rediscovery if IP changed."""
        while not self._is_closing:
            try:
                await asyncio.sleep(interval)
                if self._is_closing:
                    break

                # If disconnected for more than 2 minutes, scan local network for relocated broker
                if not self.is_connected and (time.time() - self._last_state_change > 120):
                    _LOGGER.info(
                        "Vigipool broker at %s disconnected for >120s; scanning network for IP changes...",
                        self._host,
                    )
                    brokers = await async_discover_vigipool_brokers()
                    for b in brokers:
                        # Match primary device id
                        if self.primary_device_id and self.primary_device_id in b.devices:
                            if b.ip != self._host:
                                _LOGGER.warning(
                                    "Vigipool broker moved from %s to %s. Updating configuration.",
                                    self._host,
                                    b.ip,
                                )
                                self._host = b.ip
                                self.mqtt_client.set_host(b.ip, b.port)
                                # Update config entry in Home Assistant
                                new_data = dict(self.entry.data)
                                new_data[CONF_BROKER] = b.ip
                                self.hass.config_entries.async_update_entry(self.entry, data=new_data)
                                await self.mqtt_client.async_connect()
                                break
            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.debug("Error during periodic check: %s", err)
