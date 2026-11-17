"""Tests for Vigipool discovery module."""
import asyncio
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock, patch

from custom_components.vigipool.const import DEFAULT_PORT
from custom_components.vigipool.discovery import (
    DiscoveredDevice,
    DiscoveredVigipoolBroker,
    _InterfaceInfo,
    _is_virtual_interface,
    _network_hosts_for_interface,
    _sysfs_interface_is_physical,
    async_check_vigipool_http_signature,
    async_discover_vigipool_brokers,
    async_probe_vigipool_broker,
    async_scan_network,
    async_scan_port,
    get_local_ip_ranges,
)


async def _mock_http_signature(ip):
    return ip == "192.168.1.45"


def _interface(name, ipv4=(), is_up=True):
    """Build interface information without touching the host network."""
    return _InterfaceInfo(name=name, ipv4=list(ipv4), is_up=is_up)


@contextmanager
def _mock_network(interfaces, sysfs=None):
    """Isolate get_local_ip_ranges() from the machine running the tests.

    All three system sources are mocked (psutil/netifaces/route fallback) and
    the sysfs classification is driven by the given mapping: ``True`` means a
    physical NIC, ``False`` a virtual one, ``None`` "information unavailable".
    """
    sysfs = sysfs or {}
    with patch(
        "custom_components.vigipool.discovery._interfaces_from_psutil",
        return_value=interfaces,
    ), patch(
        "custom_components.vigipool.discovery._interfaces_from_netifaces",
        return_value=[],
    ), patch(
        "custom_components.vigipool.discovery._add_route_fallback"
    ), patch(
        "custom_components.vigipool.discovery._sysfs_interface_is_physical",
        side_effect=lambda name: sysfs.get(name),
    ):
        yield


def _make_broker(ip, prefixes):
    """Build a broker with one device per prefix, for discovery tests."""
    devices = {}
    for index, prefix in enumerate(prefixes):
        mac = f"{index + 1:012X}"
        device_id = f"{prefix}_{mac}"
        devices[device_id] = DiscoveredDevice(
            device_id=device_id,
            prefix=prefix,
            mac=mac,
            model=f"Vigipool {prefix.capitalize()}",
            description="Pool device",
            url="https://www.ccei-pool.com/",
        )
    return DiscoveredVigipoolBroker(
        ip=ip,
        port=DEFAULT_PORT,
        primary_device_id=next(iter(devices)),
        devices=devices,
    )


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

    async def test_async_scan_network_keeps_input_order(self):
        """Results stay deterministic even with concurrent workers."""
        ips = ["192.168.1.10", "192.168.1.20", "192.168.1.30"]
        with patch("custom_components.vigipool.discovery.async_scan_port") as mock_scan:
            mock_scan.side_effect = lambda ip, port, timeout: True
            self.assertEqual(await async_scan_network(ips, max_concurrent=2), ips)

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

    async def test_full_discovery_expected_brokers_and_devices(self):
        """The Apache server is rejected; 4 brokers / 6 devices are found."""
        http_servers = [
            "192.168.41.10",
            "192.168.41.83",
            "192.168.41.114",
            "192.168.41.115",
            "192.168.41.121",  # Apache: HTTP signature mismatch
        ]
        expected = {
            "192.168.41.10": ("tild",),
            "192.168.41.83": ("tildrc",),
            "192.168.41.114": ("tild", "vigiwatt"),
            "192.168.41.115": ("vigiwatt", "lynx"),
        }

        async def fake_probe(ip, port=DEFAULT_PORT):
            return _make_broker(ip, expected[ip])

        with patch(
            "custom_components.vigipool.discovery.async_scan_network",
            side_effect=[http_servers, list(expected)],
        ), patch(
            "custom_components.vigipool.discovery.async_check_vigipool_http_signature",
            side_effect=lambda ip: ip != "192.168.41.121",
        ), patch(
            "custom_components.vigipool.discovery.async_probe_vigipool_broker",
            side_effect=fake_probe,
        ) as mock_probe:
            brokers = await async_discover_vigipool_brokers(custom_ips=http_servers)

        self.assertEqual(len(brokers), 4)
        self.assertEqual(sum(len(broker.devices) for broker in brokers), 6)
        self.assertNotIn("192.168.41.121", [broker.ip for broker in brokers])
        self.assertEqual(mock_probe.await_count, 4)

    def test_network_hosts_preserves_slash_22(self):
        hosts = _network_hosts_for_interface("192.168.41.54", "255.255.252.0")
        self.assertEqual(len(hosts), 1022)
        self.assertEqual(hosts[0], "192.168.40.1")
        self.assertEqual(hosts[-1], "192.168.43.254")

    def test_network_hosts_skips_excessively_large_network(self):
        self.assertEqual(
            _network_hosts_for_interface("192.168.41.54", "255.255.0.0"), []
        )

    def test_network_hosts_skips_loopback_and_link_local(self):
        self.assertEqual(_network_hosts_for_interface("127.0.0.1", "255.0.0.0"), [])
        self.assertEqual(_network_hosts_for_interface("169.254.1.2", "255.255.0.0"), [])

    def test_virtual_interfaces_are_excluded(self):
        for interface in (
            "docker0", "br-123456789", "veth74dde91", "virbr0",
            "wg0-mullvad", "tun0", "tap0", "tailscale0", "ham0", "lo",
            "zt0", "podman0", "cni0",
        ):
            with self.subTest(interface=interface):
                self.assertTrue(_is_virtual_interface(interface))
        self.assertFalse(_is_virtual_interface("enp2s0"))
        self.assertFalse(_is_virtual_interface("eth0"))
        self.assertFalse(_is_virtual_interface("wlan0"))

    # --- Interface selection -------------------------------------------------

    def test_physical_ethernet_active_included(self):
        with _mock_network(
            [_interface("enp2s0", [("192.168.41.54", "255.255.252.0")])],
            {"enp2s0": True},
        ):
            ips = get_local_ip_ranges()
        self.assertEqual(len(ips), 1022)
        self.assertEqual(ips[0], "192.168.40.1")
        self.assertIn("192.168.43.254", ips)

    def test_physical_wifi_active_included(self):
        with _mock_network(
            [_interface("wlp2s0", [("192.168.1.20", "255.255.255.0")])],
            {"wlp2s0": True},
        ):
            ips = get_local_ip_ranges()
        self.assertEqual(len(ips), 254)
        self.assertEqual(ips[0], "192.168.1.1")
        self.assertIn("192.168.1.254", ips)

    def test_docker0_excluded(self):
        with _mock_network(
            [_interface("docker0", [("172.17.0.1", "255.255.0.0")])],
            {"docker0": False},
        ):
            self.assertEqual(get_local_ip_ranges(), [])

    def test_docker_bridge_excluded(self):
        with _mock_network(
            [_interface("br-ff96d053c0c3", [("172.18.0.1", "255.255.0.0")])],
            {"br-ff96d053c0c3": False},
        ):
            self.assertEqual(get_local_ip_ranges(), [])

    def test_libvirt_bridge_excluded(self):
        with _mock_network(
            [_interface("virbr0", [("192.168.122.1", "255.255.255.0")])],
            {"virbr0": False},
        ):
            self.assertEqual(get_local_ip_ranges(), [])

    def test_wireguard_interface_excluded(self):
        with _mock_network(
            [_interface("wg0-mullvad", [("10.136.174.66", "255.255.255.255")])],
            {"wg0-mullvad": False},
        ):
            self.assertEqual(get_local_ip_ranges(), [])

    def test_tailscale_interface_excluded(self):
        with _mock_network(
            [_interface("tailscale0", [("100.64.0.1", "255.255.255.0")])],
            {"tailscale0": False},
        ):
            self.assertEqual(get_local_ip_ranges(), [])

    def test_loopback_excluded(self):
        with _mock_network(
            [_interface("lo", [("127.0.0.1", "255.0.0.0")])],
            {"lo": False},
        ):
            self.assertEqual(get_local_ip_ranges(), [])

    def test_interface_without_ipv4_excluded(self):
        with _mock_network([_interface("eth1", [])], {"eth1": True}):
            self.assertEqual(get_local_ip_ranges(), [])

    def test_inactive_interface_excluded(self):
        with _mock_network(
            [_interface("enp3s0", [("192.168.5.10", "255.255.255.0")], is_up=False)],
            {"enp3s0": True},
        ):
            self.assertEqual(get_local_ip_ranges(), [])

    def test_slash_22_network_preserved_in_logs(self):
        with self.assertLogs("custom_components.vigipool.discovery", level="DEBUG") as logs:
            with _mock_network(
                [_interface("enp2s0", [("192.168.41.54", "255.255.252.0")])],
                {"enp2s0": True},
            ):
                ips = get_local_ip_ranges()
        output = "\n".join(logs.output)
        self.assertIn("[INCLUDED] enp2s0", output)
        self.assertIn("192.168.40.0/22", output)
        self.assertNotIn("192.168.41.0/24", output)
        self.assertEqual(len(ips), 1022)

    def test_multiple_physical_interfaces_all_included(self):
        with _mock_network(
            [
                _interface("enp2s0", [("192.168.41.54", "255.255.252.0")]),
                _interface("wlp2s0", [("192.168.1.20", "255.255.255.0")]),
            ],
            {"enp2s0": True, "wlp2s0": True},
        ):
            ips = get_local_ip_ranges()
        self.assertEqual(len(ips), 1022 + 254)
        self.assertIn("192.168.40.1", ips)
        self.assertIn("192.168.1.1", ips)

    def test_duplicate_addresses_deduplicated(self):
        with _mock_network(
            [
                _interface("enp2s0", [("192.168.41.54", "255.255.252.0")]),
                _interface("eno1", [("192.168.41.60", "255.255.252.0")]),
            ],
            {"enp2s0": True, "eno1": True},
        ):
            ips = get_local_ip_ranges()
        self.assertEqual(len(ips), 1022)
        self.assertEqual(len(ips), len(set(ips)))

    def test_fallback_without_sysfs_information(self):
        """Without sysfs data, name heuristics still exclude virtual NICs."""
        with _mock_network(
            [
                _interface("enp2s0", [("192.168.41.54", "255.255.252.0")]),
                _interface("docker0", [("172.17.0.1", "255.255.0.0")]),
                _interface("enx001122334455", [("192.168.10.5", "255.255.255.0")]),
            ],
            {},
        ):
            ips = get_local_ip_ranges()
        self.assertEqual(len(ips), 1022 + 254)
        self.assertNotIn("172.17.0.1", ips)
        self.assertIn("192.168.10.1", ips)

    def test_sysfs_takes_precedence_over_interface_names(self):
        """Physical detection uses system information, not names alone."""
        with _mock_network(
            [
                _interface("eth9", [("192.168.9.5", "255.255.255.0")]),
                _interface("wg-custom", [("10.9.0.5", "255.255.255.0")]),
            ],
            {"eth9": False, "wg-custom": True},
        ):
            ips = get_local_ip_ranges()
        self.assertEqual(len(ips), 254)
        # sysfs says eth9 is virtual and wg-custom is real hardware.
        self.assertNotIn("192.168.9.1", ips)
        self.assertIn("10.9.0.1", ips)

    def test_sysfs_detection_with_simulated_sysfs(self):
        """The real sysfs helper is exercised against a temporary tree."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            net_dir = root / "class" / "net"
            net_dir.mkdir(parents=True)

            physical_dir = net_dir / "enp2s0"
            physical_dir.mkdir()
            (physical_dir / "device").mkdir()

            virtual_dir = root / "devices" / "virtual" / "net" / "docker0"
            virtual_dir.mkdir(parents=True)
            (net_dir / "docker0").symlink_to(virtual_dir, target_is_directory=True)

            with patch(
                "custom_components.vigipool.discovery._SYSFS_NET_PATH", net_dir
            ):
                self.assertIs(_sysfs_interface_is_physical("enp2s0"), True)
                self.assertIs(_sysfs_interface_is_physical("docker0"), False)
                self.assertIsNone(_sysfs_interface_is_physical("missing0"))

    def test_diagnostic_logs_are_detailed_at_debug_level(self):
        interfaces = [
            _interface("enp2s0", [("192.168.41.54", "255.255.252.0")]),
            _interface("docker0", [("172.17.0.1", "255.255.0.0")]),
            _interface("virbr0", [("192.168.122.1", "255.255.255.0")]),
            _interface("wg0-mullvad", [("10.136.174.66", "255.255.255.255")]),
        ]
        sysfs = {
            "enp2s0": True,
            "docker0": False,
            "virbr0": False,
            "wg0-mullvad": False,
        }
        with self.assertLogs(
            "custom_components.vigipool.discovery", level="DEBUG"
        ) as logs:
            with _mock_network(interfaces, sysfs):
                ips = get_local_ip_ranges()
        output = "\n".join(logs.output)

        self.assertIn("[INCLUDED] enp2s0", output)
        self.assertIn("[EXCLUDED] docker0", output)
        self.assertIn("virtual container bridge", output)
        self.assertIn("[EXCLUDED] virbr0", output)
        self.assertIn("libvirt virtual bridge", output)
        self.assertIn("[EXCLUDED] wg0-mullvad", output)
        self.assertIn("VPN / tunnel interface", output)
        self.assertIn("Included interfaces : 1", output)
        self.assertIn("Excluded interfaces : 3", output)
        self.assertIn("Addresses to scan   : 1022", output)
        self.assertEqual(len(ips), 1022)
