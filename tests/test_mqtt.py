"""Tests for Vigipool MQTT client."""
import asyncio
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock, patch

from custom_components.vigipool.mqtt import ConnectionState, VigipoolMqttClient


class TestVigipoolMqttClient(IsolatedAsyncioTestCase):
    """Test dedicated Vigipool MQTT client."""

    async def test_connect_and_message_delivery(self):
        """Test connecting, receiving messages, and updating state."""
        messages_received = []
        state_changes = []

        def msg_cb(topic, payload):
            messages_received.append((topic, payload))

        def state_cb(state):
            state_changes.append(state)

        with patch("paho.mqtt.client.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client

            client = VigipoolMqttClient(
                host="192.168.1.55",
                port=1883,
                on_message_callback=msg_cb,
                on_state_change_callback=state_cb,
            )

            # Initially disconnected
            self.assertEqual(client.state, ConnectionState.DISCONNECTED)
            self.assertFalse(client.is_connected)

            # Connect
            connected = await client.async_connect()
            self.assertTrue(connected)
            mock_client.connect.assert_called_with("192.168.1.55", 1883, keepalive=30)
            mock_client.loop_start.assert_called_once()

            # Trigger on_connect callback
            client._on_connect(mock_client, None, {}, 0)
            await asyncio.sleep(0.01)
            self.assertTrue(client.is_connected)
            self.assertEqual(client.state, ConnectionState.CONNECTED)
            self.assertIn(ConnectionState.CONNECTED, state_changes)

            # Subscribe
            await client.async_subscribe("tild_84CCA89E2340/#")
            mock_client.subscribe.assert_called_with("tild_84CCA89E2340/#")

            # Receive message
            mqtt_msg = MagicMock()
            mqtt_msg.topic = "tild_84CCA89E2340/u16_r/value_temp/value/reported"
            mqtt_msg.payload = b"248"
            client._on_message(mock_client, None, mqtt_msg)

            # Give a tick for call_soon_threadsafe
            await asyncio.sleep(0.01)
            self.assertEqual(len(messages_received), 1)
            self.assertEqual(
                messages_received[0],
                ("tild_84CCA89E2340/u16_r/value_temp/value/reported", "248"),
            )

            # Publish
            mock_info = MagicMock()
            mock_info.rc = 0
            mock_client.publish.return_value = mock_info
            pub_ok = await client.async_publish("tild_84CCA89E2340/u8_w/filt_state/info/desired", "1")
            self.assertTrue(pub_ok)
            mock_client.publish.assert_called_with(
                "tild_84CCA89E2340/u8_w/filt_state/info/desired", "1", qos=0, retain=False
            )

            # Disconnect
            await client.async_disconnect()
            self.assertFalse(client.is_connected)
            mock_client.loop_stop.assert_called_once()
            mock_client.disconnect.assert_called_once()
