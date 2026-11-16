"""Dedicated MQTT client for direct communication with Vigipool equipment."""
from __future__ import annotations

import asyncio
from enum import Enum
import logging
import random
import time
from typing import Callable

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

from .const import DEFAULT_PORT

_LOGGER = logging.getLogger(__name__)


class ConnectionState(str, Enum):
    """MQTT connection state."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


class VigipoolMqttClient:
    """Dedicated async-wrapped MQTT client for CCEI Vigipool brokers."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        on_message_callback: Callable[[str, str], None] | None = None,
        on_state_change_callback: Callable[[ConnectionState], None] | None = None,
    ) -> None:
        """Initialize the Vigipool MQTT client."""
        self._host = host
        self._port = port
        self._on_message_callback = on_message_callback
        self._on_state_change_callback = on_state_change_callback

        self._state = ConnectionState.DISCONNECTED
        self._client: mqtt.Client | None = None
        self._subscriptions: set[str] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._should_reconnect = True
        self._reconnect_task: asyncio.Task | None = None
        self._last_communication: float | None = None

    @property
    def host(self) -> str:
        """Return the current host IP."""
        return self._host

    @property
    def port(self) -> int:
        """Return the port."""
        return self._port

    @property
    def state(self) -> ConnectionState:
        """Return connection state."""
        return self._state

    @property
    def is_connected(self) -> bool:
        """Return True if currently connected."""
        return self._state == ConnectionState.CONNECTED

    @property
    def last_communication(self) -> float | None:
        """Timestamp of last received message or ping."""
        return self._last_communication

    def set_host(self, host: str, port: int = DEFAULT_PORT) -> None:
        """Update broker host IP (e.g. following IP change)."""
        self._host = host
        self._port = port

    def _set_state(self, new_state: ConnectionState) -> None:
        """Set state and notify callback."""
        if self._state != new_state:
            self._state = new_state
            _LOGGER.debug("Vigipool MQTT connection state changed to: %s", new_state.value)
            if self._on_state_change_callback and self._loop:
                self._loop.call_soon_threadsafe(
                    self._on_state_change_callback, new_state
                )

    def _on_connect(self, client: mqtt.Client, userdata: any, flags: dict, rc: int) -> None:
        """Callback when paho-mqtt connects."""
        if rc == 0:
            _LOGGER.info("Connected directly to Vigipool MQTT broker at %s:%d", self._host, self._port)
            self._set_state(ConnectionState.CONNECTED)
            self._last_communication = time.time()
            # Resubscribe to all registered topics
            for topic in self._subscriptions:
                _LOGGER.debug("Subscribing to Vigipool topic: %s", topic)
                client.subscribe(topic)
        else:
            _LOGGER.warning("Connection to Vigipool broker %s failed with code %d", self._host, rc)
            self._set_state(ConnectionState.DISCONNECTED)

    def _on_disconnect(self, client: mqtt.Client, userdata: any, rc: int) -> None:
        """Callback when paho-mqtt disconnects."""
        if rc == 0:
            _LOGGER.info("Cleanly disconnected from Vigipool MQTT broker at %s", self._host)
        else:
            _LOGGER.warning(
                "Unexpected disconnection from Vigipool MQTT broker at %s (code %d). Reconnecting...",
                self._host,
                rc,
            )
        self._set_state(ConnectionState.DISCONNECTED)

        # Trigger async reconnect loop if appropriate
        if self._should_reconnect and self._loop and (not self._reconnect_task or self._reconnect_task.done()):
            self._reconnect_task = asyncio.run_coroutine_threadsafe(
                self._async_reconnect_loop(), self._loop
            )

    def _on_message(self, client: mqtt.Client, userdata: any, msg: mqtt.MQTTMessage) -> None:
        """Callback when a message arrives."""
        self._last_communication = time.time()
        try:
            payload = msg.payload.decode("utf-8", errors="replace")
        except Exception:
            payload = str(msg.payload)

        if self._on_message_callback and self._loop:
            self._loop.call_soon_threadsafe(
                self._on_message_callback, msg.topic, payload
            )

    async def async_connect(self) -> bool:
        """Connect to the Vigipool MQTT broker asynchronously."""
        if mqtt is None:
            raise RuntimeError("paho-mqtt is required for Vigipool integration")

        self._loop = asyncio.get_running_loop()
        self._should_reconnect = True
        self._set_state(ConnectionState.CONNECTING)

        client_id = f"vigipool_ha_{random.randint(1000, 9999)}"
        self._client = mqtt.Client(client_id=client_id, clean_session=True)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        try:
            # Connect in executor to avoid event loop blocking
            await self._loop.run_in_executor(
                None, lambda: self._client.connect(self._host, self._port, keepalive=30)
            )
            self._client.loop_start()
            return True
        except Exception as err:
            _LOGGER.warning("Could not connect to Vigipool broker %s:%d - %s", self._host, self._port, err)
            self._set_state(ConnectionState.DISCONNECTED)
            return False

    async def _async_reconnect_loop(self) -> None:
        """Handle reconnection with backoff."""
        delay = 2.0
        max_delay = 30.0
        while self._should_reconnect and not self.is_connected:
            await asyncio.sleep(delay)
            if not self._should_reconnect:
                break
            _LOGGER.debug("Attempting to reconnect to Vigipool broker at %s...", self._host)
            try:
                if self._client:
                    await self._loop.run_in_executor(None, self._client.reconnect)
                    # If reconnect succeeded without exception, wait for on_connect callback
                    break
            except Exception as err:
                _LOGGER.debug("Reconnection attempt failed: %s", err)
                delay = min(delay * 1.5, max_delay)

    async def async_disconnect(self) -> None:
        """Disconnect cleanly from broker."""
        self._should_reconnect = False
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()

        if self._client:
            try:
                self._client.loop_stop()
                await self._loop.run_in_executor(None, self._client.disconnect)
            except Exception as err:
                _LOGGER.debug("Error during MQTT disconnect: %s", err)
            finally:
                self._client = None

        self._set_state(ConnectionState.DISCONNECTED)

    async def async_subscribe(self, topic: str) -> None:
        """Subscribe to a topic."""
        self._subscriptions.add(topic)
        if self.is_connected and self._client:
            await self._loop.run_in_executor(None, lambda: self._client.subscribe(topic))

    async def async_publish(
        self,
        topic: str,
        payload: str | int | float,
        qos: int = 0,
        retain: bool = False,
    ) -> bool:
        """Publish a message to a topic."""
        if not self.is_connected or not self._client:
            _LOGGER.warning("Cannot publish to %s: Vigipool MQTT client disconnected", topic)
            return False

        payload_str = str(payload)
        _LOGGER.debug("Publishing to %s: %s (retain=%s)", topic, payload_str, retain)
        try:
            info = await self._loop.run_in_executor(
                None, lambda: self._client.publish(topic, payload_str, qos=qos, retain=retain)
            )
            return info.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as err:
            _LOGGER.error("Failed to publish to %s: %s", topic, err)
            return False
