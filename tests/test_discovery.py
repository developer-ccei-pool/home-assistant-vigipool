"""Tests for Vigipool discovery module."""
import asyncio
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock, patch

from custom_components.vigipool.const import DEFAULT_PORT
from custom_components.vigipool.discovery import (
    DiscoveredDevice,
    DiscoveredVigipoolBroker,
    async_check_vigipool_http_signature,
    async_discover_vigipool_brokers,
    async_probe_vigipool_broker,
    async_scan_network,
    async_scan_port,
    get_local_ip_ranges,
    _is_virtual_interface,
    _network_hosts_for_interface,
)


async def _mock_http_signature(ip):
    return ip == "192.168.1.45"


class TestDiscovery(IsolatedAsyncioTestCase):
    def test_get_local_ip_ranges(self):
        ips = get_local_ip_ranges()
        self.assertIsInstance(ips, list)
        for ip in ips:
            self.assertFalse(ip.startswith("127."))
            self.assertFalse(ip.startswith("169.254."))

    async def test_async_scan_port_open(self):
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            self.assertTrue(await async_scan_port("127.0.0.1", port=port, timeout=0.5))
        finally:
            server.close()
            await server.wait_closed()

    async def test_async_scan_port_closed(self):
        self.assertFalse(await async_scan_port("127.0.0.1", port=59999, timeout=0.2))

    async def test_async_scan_network(self):
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

    async def test_http_signature_accepts_exact_vigipool_body(self):
        with patch(
            "custom_components.vigipool.discovery._has_vigipool_http_signature",
            return_value=True,
        ):
            self.assertTrue(await async_check_vigipool_http_signature("192.168.1.45"))

    async def test_http_signature_rejects_other_server(self):
        with patch(
            "custom_components.vigipool.discovery._has_vigipool_http_signature",
            return_value=False,
        ):
            self.assertFalse(await async_check_vigipool_http_signature("192.168.1.121"))

    async def test_probe_vigipool_broker_success(self):
        with patch("paho.mqtt.client.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            def fake_connect(host, port, keepalive):
                mock_client.on_connect(mock_client, None, {}, 0)
                for topic, payload in (
                    ("tild_84CCA89E2340/u16_r/value_temp/value/reported", b"245"),
                    ("ziphox_30AEA4071850/u16_r/value_ph/value/reported", b"720"),
                ):
                    msg = MagicMock()
                    msg.topic, msg.payload = topic, payload
                    mock_client.on_message(mock_client, None, msg)
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

    async def test_probe_generic_broker_not_vigipool(self):
        with patch("paho.mqtt.client.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            def fake_connect(host, port, keepalive):
                mock_client.on_connect(mock_client, None, {}, 0)
                msg = MagicMock()
                msg.topic = "homeassistant/sensor/temp/state"
                msg.payload = b"21.5"
                mock_client.on_message(mock_client, None, msg)
                return 0
            mock_client.connect.side_effect = fake_connect
            self.assertIsNone(
                await async_probe_vigipool_broker("192.168.1.200", timeout=0.1)
            )

    async def test_discovery_filters_http_before_mqtt(self):
        dev = DiscoveredDevice(
            device_id="tild_84CCA89E2340", prefix="tild", mac="84CCA89E2340",
            model="Tild VP", description="Pool controller", url="https://ccei.fr",
        )
        broker = DiscoveredVigipoolBroker(
            ip="192.168.1.45", port=1883,
            primary_device_id="tild_84CCA89E2340",
            devices={"tild_84CCA89E2340": dev},
        )
        with patch(
            "custom_components.vigipool.discovery.async_scan_network",
            side_effect=[["192.168.1.45", "192.168.1.121"], ["192.168.1.45"]],
        ) as mock_scan, patch(
            "custom_components.vigipool.discovery.async_check_vigipool_http_signature",
            side_effect=_mock_http_signature,
        ), patch(
            "custom_components.vigipool.discovery.async_probe_vigipool_broker",
            return_value=broker,
        ) as mock_probe:
            discovered = await async_discover_vigipool_brokers(
                custom_ips=["192.168.1.45", "192.168.1.121"]
            )
            self.assertEqual([item.ip for item in discovered], ["192.168.1.45"])
            mock_probe.assert_awaited_once_with("192.168.1.45", port=1883)
            self.assertEqual(mock_scan.await_count, 2)

    def test_network_hosts_preserves_slash_22(self):
        hosts = _network_hosts_for_interface("192.168.41.54", "255.255.252.0")
        self.assertEqual(len(hosts), 1022)
        self.assertEqual(hosts[0], "192.168.40.1")
        self.assertEqual(hosts[-1], "192.168.43.254")

    def test_network_hosts_skips_excessively_large_network(self):
        self.assertEqual(
            _network_hosts_for_interface("192.168.41.54", "255.255.0.0"), []
        )

    def test_virtual_interfaces_are_excluded(self):
        for interface in (
            "docker0", "br-123456789", "veth74dde91", "virbr0",
            "wg0-mullvad", "tun0", "tailscale0", "lo",
        ):
            with self.subTest(interface=interface):
                self.assertTrue(_is_virtual_interface(interface))
        self.assertFalse(_is_virtual_interface("enp2s0"))
        self.assertFalse(_is_virtual_interface("eth0"))
