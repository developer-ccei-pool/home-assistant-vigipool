"""Tests for Vigipool discovery module."""
import asyncio
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock, patch

from custom_components.vigipool.const import DEFAULT_PORT
from custom_components.vigipool.discovery import (
    DiscoveredDevice,
    DiscoveredVigipoolBroker,
    async_discover_vigipool_brokers,
    async_probe_vigipool_broker,
    async_scan_network,
    async_scan_port,
    get_local_ip_ranges,
)


class TestDiscovery(IsolatedAsyncioTestCase):
    """Test discovery mechanisms."""

    def test_get_local_ip_ranges(self):
        """Test local IP subnet discovery clamps large subnets."""
        ips = get_local_ip_ranges()
        self.assertIsInstance(ips, list)
        # Should not include loopback
        for ip in ips:
            self.assertFalse(ip.startswith("127."))
            self.assertFalse(ip.startswith("169.254."))

    async def test_async_scan_port_open(self):
        """Test port scanning when port is open."""
        # Start a local dummy TCP server
        server = await asyncio.start_server(
            lambda r, w: w.close(),
            "127.0.0.1",
            0,
        )
        port = server.sockets[0].getsockname()[1]

        try:
            is_open = await async_scan_port("127.0.0.1", port=port, timeout=0.5)
            self.assertTrue(is_open)
        finally:
            server.close()
            await server.wait_closed()

    async def test_async_scan_port_closed(self):
        """Test port scanning when port is closed."""
        is_open = await async_scan_port("127.0.0.1", port=59999, timeout=0.2)
        self.assertFalse(is_open)

    async def test_async_scan_network(self):
        """Test scanning a small list of IPs."""
        progress_calls = []

        def cb(cur, total):
            progress_calls.append((cur, total))

        with patch("custom_components.vigipool.discovery.async_scan_port") as mock_scan:
            mock_scan.side_effect = lambda ip, port, timeout: ip == "192.168.1.50"
            res = await async_scan_network(
                ["192.168.1.10", "192.168.1.50", "192.168.1.99"],
                port=DEFAULT_PORT,
                progress_callback=cb,
            )
            self.assertEqual(res, ["192.168.1.50"])
            self.assertEqual(len(progress_calls), 3)
            self.assertEqual(progress_calls[-1], (3, 3))

    async def test_probe_vigipool_broker_success(self):
        """Test probing an MQTT broker that returns Vigipool topics."""
        with patch("paho.mqtt.client.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client

            def fake_connect(host, port, keepalive):
                # Simulate paho connect callback immediately
                mock_client.on_connect(mock_client, None, {}, 0)
                # Simulate receiving Vigipool messages
                msg1 = MagicMock()
                msg1.topic = "tild_84CCA89E2340/u16_r/value_temp/value/reported"
                msg1.payload = b"245"
                mock_client.on_message(mock_client, None, msg1)

                msg2 = MagicMock()
                msg2.topic = "ziphox_30AEA4071850/u16_r/value_ph/value/reported"
                msg2.payload = b"720"
                mock_client.on_message(mock_client, None, msg2)
                return 0

            mock_client.connect.side_effect = fake_connect

            broker = await async_probe_vigipool_broker("192.168.1.45", timeout=0.5)
            self.assertIsNotNone(broker)
            self.assertEqual(broker.ip, "192.168.1.45")
            self.assertEqual(broker.primary_device_id, "tild_84CCA89E2340")
            self.assertIn("tild_84CCA89E2340", broker.devices)
            self.assertIn("ziphox_30AEA4071850", broker.devices)
            self.assertEqual(broker.devices["tild_84CCA89E2340"].model, "Tild VP")
            self.assertEqual(broker.devices["ziphox_30AEA4071850"].model, "Ofix VP")
            self.assertIn("Tild VP", broker.display_name)
            self.assertIn("Ofix VP", broker.display_name)

    async def test_probe_generic_broker_not_vigipool(self):
        """Test that a generic MQTT broker (not Vigipool) is rejected."""
        with patch("paho.mqtt.client.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client

            def fake_connect(host, port, keepalive):
                mock_client.on_connect(mock_client, None, {}, 0)
                # Receive standard home assistant or zigbee2mqtt topics
                msg = MagicMock()
                msg.topic = "homeassistant/sensor/temp/state"
                msg.payload = b"21.5"
                mock_client.on_message(mock_client, None, msg)
                return 0

            mock_client.connect.side_effect = fake_connect

            broker = await async_probe_vigipool_broker("192.168.1.200", timeout=0.1)
            self.assertIsNone(broker)

    async def test_async_discover_vigipool_brokers(self):
        """Test full discover flow chaining port scan and MQTT probe."""
        with patch(
            "custom_components.vigipool.discovery.async_scan_network",
            return_value=["192.168.1.45"],
        ), patch(
            "custom_components.vigipool.discovery.async_probe_vigipool_broker"
        ) as mock_probe:
            dev = DiscoveredDevice(
                device_id="tild_84CCA89E2340",
                prefix="tild",
                mac="84CCA89E2340",
                model="Tild VP",
                description="Pool controller",
                url="https://ccei.fr",
            )
            mock_probe.return_value = DiscoveredVigipoolBroker(
                ip="192.168.1.45",
                port=1883,
                primary_device_id="tild_84CCA89E2340",
                devices={"tild_84CCA89E2340": dev},
            )

            discovered = await async_discover_vigipool_brokers(custom_ips=["192.168.1.45"])
            self.assertEqual(len(discovered), 1)
            self.assertEqual(discovered[0].ip, "192.168.1.45")
