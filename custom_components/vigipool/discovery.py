"""Network discovery and Vigipool MQTT broker detection."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import ipaddress
import logging
from pathlib import Path
import socket
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None  # Handled during tests or mocks

from .const import (
    DEFAULT_HTTP_PROBE_TIMEOUT,
    DEFAULT_MAX_CONCURRENT_SCANS,
    DEFAULT_MQTT_PROBE_TIMEOUT,
    DEFAULT_PORT,
    DEFAULT_PORT_SCAN_TIMEOUT,
    DEVICE_MODELS,
    VIGIPOOL_HTTP_SIGNATURE,
    VIGIPOOL_TOPIC_REGEX,
)
from .mqtt import get_mqtt_client

_LOGGER = logging.getLogger(__name__)

# Linux sysfs mount used to distinguish real NICs from virtual interfaces.
_SYSFS_NET_PATH = Path("/sys/class/net")

# Do not scan networks broader than /20 (Docker/libvirt commonly use /16).
_MIN_NETWORK_PREFIXLEN = 20


@dataclass
class DiscoveredDevice:
    """Represents a physical Vigipool device connected via the broker."""

    device_id: str
    prefix: str
    mac: str
    model: str
    description: str
    url: str
    last_seen: float = field(default_factory=time.time)
    info: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoveredVigipoolBroker:
    """Represents a discovered Vigipool MQTT broker / gateway."""

    ip: str
    port: int = DEFAULT_PORT
    primary_device_id: str = ""
    devices: dict[str, DiscoveredDevice] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """User-friendly display name for the broker and its devices."""
        if not self.devices:
            return f"Vigipool ({self.ip})"
        device_names = [d.model for d in self.devices.values()]
        return f"Vigipool ({self.ip}) - {', '.join(device_names)}"


@dataclass
class _InterfaceInfo:
    """IPv4 information collected for a single network interface."""

    name: str
    ipv4: list[tuple[str, str]] = field(default_factory=list)
    is_up: bool | None = None


@dataclass
class _InterfaceDecision:
    """Result of the interface selection step, kept for diagnostics."""

    name: str
    included: bool
    reason: str = ""
    address: str = ""
    network: str = ""
    kind: str = ""


# Known virtual/tunnel interface names and the reason attached to each family.
# This is only a first hint: sysfs (when available) is authoritative.
_VIRTUAL_NAME_REASONS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("lo", "loop"), "loopback interface"),
    (
        ("docker", "veth", "podman", "cni", "br-", "br_"),
        "virtual container bridge",
    ),
    (("virbr",), "libvirt virtual bridge"),
    (("wg", "tun", "tap", "tailscale", "zt", "ham"), "VPN / tunnel interface"),
)


def _is_virtual_interface(name: str) -> bool:
    """Return True for well-known virtual, bridge or tunnel interface names."""
    name = name.lower()
    virtual_prefixes = (
        "lo", "docker", "br-", "br_", "veth", "virbr",
        "wg", "tun", "tap", "tailscale", "ham",
        "zt", "podman", "cni",
    )
    return name.startswith(virtual_prefixes)


def _virtual_interface_reason(name: str) -> str:
    """Explain why an interface name is considered virtual."""
    lower_name = name.lower()
    for prefixes, reason in _VIRTUAL_NAME_REASONS:
        if lower_name.startswith(prefixes):
            return reason
    return "virtual interface"


def _sysfs_interface_is_physical(name: str) -> bool | None:
    """Identify a physical NIC from Linux sysfs.

    A real network device exposes a ``device`` symlink pointing to a PCI, USB
    or platform device. Virtual devices (Docker/libvirt bridges, WireGuard,
    veth pairs, loopback, ...) live under ``/sys/devices/virtual/net`` and have
    no such link.

    Returns ``True`` for a physical NIC, ``False`` for a virtual one and
    ``None`` when sysfs cannot be consulted (non-Linux, container, missing
    permissions), so that the caller can fall back to name heuristics.
    """
    try:
        interface_dir = _SYSFS_NET_PATH / name
        if not interface_dir.is_dir():
            return None
        if "virtual" in interface_dir.resolve().parts:
            return False
        return (interface_dir / "device").exists()
    except (OSError, ValueError, RuntimeError):
        return None


def _classify_interface(name: str) -> tuple[bool, str, str]:
    """Return ``(included, reason, kind)`` for an interface name."""
    if name.lower() in {"lo", "loopback"}:
        return False, "loopback interface", ""

    name_is_virtual = _is_virtual_interface(name)
    reason = _virtual_interface_reason(name) if name_is_virtual else ""

    sysfs_kind = _sysfs_interface_is_physical(name)
    if sysfs_kind is True:
        # sysfs is authoritative: real hardware wins over an unusual name.
        return True, "", "physical Ethernet/Wi-Fi interface (sysfs device)"
    if sysfs_kind is False:
        return False, reason or "virtual interface (no physical device in sysfs)", ""
    if name_is_virtual:
        return False, reason, ""
    return True, "", "physical interface (name heuristic)"


def _network_hosts_for_interface(ip: str, netmask: str) -> list[str]:
    """Return usable hosts without shrinking legitimate LAN subnets."""
    try:
        address = ipaddress.IPv4Address(ip)
        if (
            address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_unspecified
        ):
            return []

        network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
        if network.prefixlen < _MIN_NETWORK_PREFIXLEN:
            _LOGGER.debug("Skipping excessively large network: %s", network)
            return []
        return [str(host) for host in network.hosts()]
    except ValueError:
        return []


def _process_interface(
    info: _InterfaceInfo,
    ips_to_scan: set[str],
    decisions: list[_InterfaceDecision],
) -> None:
    """Apply the selection rules to one interface and record its decision."""
    included, reason, kind = _classify_interface(info.name)
    if not included:
        decisions.append(_InterfaceDecision(info.name, False, reason))
        return
    if info.is_up is False:
        decisions.append(_InterfaceDecision(info.name, False, "interface is down"))
        return
    if not info.ipv4:
        decisions.append(_InterfaceDecision(info.name, False, "no IPv4 address"))
        return

    hosts: set[str] = set()
    networks: list[str] = []
    address = ""
    for ip, netmask in info.ipv4:
        if not ip or not netmask:
            continue
        address_hosts = _network_hosts_for_interface(ip, netmask)
        if not address_hosts:
            _LOGGER.debug(
                "Ignoring unusable IPv4 address %s/%s on %s", ip, netmask, info.name
            )
            continue
        network = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
        hosts.update(address_hosts)
        networks.append(str(network))
        if not address:
            address = f"{ip}/{netmask}"

    if not hosts:
        decisions.append(
            _InterfaceDecision(
                info.name,
                False,
                "no usable IPv4 network (loopback, link-local or too large)",
            )
        )
        return

    ips_to_scan.update(hosts)
    decisions.append(
        _InterfaceDecision(info.name, True, "", address, ", ".join(networks), kind)
    )


def _interfaces_from_psutil() -> list[_InterfaceInfo] | None:
    """Collect interface information through psutil, when available."""
    try:
        import psutil
    except Exception as err:
        _LOGGER.debug("psutil unavailable: %s", err)
        return None

    try:
        interface_stats = psutil.net_if_stats()
        interfaces: list[_InterfaceInfo] = []
        for name, addresses in psutil.net_if_addrs().items():
            stats = interface_stats.get(name)
            interfaces.append(
                _InterfaceInfo(
                    name=name,
                    is_up=None if stats is None else bool(stats.isup),
                    ipv4=[
                        (address.address, address.netmask)
                        for address in addresses
                        if address.family == socket.AF_INET
                        and address.address
                        and address.netmask
                    ],
                )
            )
        return interfaces
    except Exception as err:
        _LOGGER.debug("psutil network discovery failed: %s", err)
        return None


def _interfaces_from_netifaces() -> list[_InterfaceInfo] | None:
    """Collect interface information through netifaces, when available."""
    try:
        import netifaces
    except Exception as err:
        _LOGGER.debug("netifaces unavailable: %s", err)
        return None

    try:
        interfaces: list[_InterfaceInfo] = []
        for name in netifaces.interfaces():
            addresses = netifaces.ifaddresses(name).get(netifaces.AF_INET, [])
            interfaces.append(
                _InterfaceInfo(
                    name=name,
                    ipv4=[
                        (address["addr"], address["netmask"])
                        for address in addresses
                        if address.get("addr") and address.get("netmask")
                    ],
                )
            )
        return interfaces
    except Exception as err:
        _LOGGER.debug("netifaces discovery failed: %s", err)
        return None


def _add_route_fallback(
    ips_to_scan: set[str], decisions: list[_InterfaceDecision]
) -> None:
    """Last resort when no interface exposes a usable IPv4 network."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            local_ip = sock.getsockname()[0]
    except OSError as err:
        _LOGGER.debug("Socket route fallback failed: %s", err)
        return

    hosts = _network_hosts_for_interface(local_ip, "255.255.255.0")
    if not hosts:
        return
    ips_to_scan.update(hosts)
    decisions.append(
        _InterfaceDecision(
            "default route (fallback)",
            True,
            "",
            f"{local_ip}/24",
            "default route /24",
            "route fallback (no interface metadata)",
        )
    )


def _log_interface_report(
    decisions: list[_InterfaceDecision], address_count: int
) -> None:
    """Log every selection decision at DEBUG level, never at INFO."""
    if not _LOGGER.isEnabledFor(logging.DEBUG):
        return

    _LOGGER.debug("Network interfaces detected:")
    for decision in decisions:
        if decision.included:
            _LOGGER.debug("[INCLUDED] %s", decision.name)
            _LOGGER.debug("  Address : %s", decision.address)
            _LOGGER.debug("  Network : %s", decision.network)
            _LOGGER.debug("  Type    : %s", decision.kind)
        else:
            _LOGGER.debug("[EXCLUDED] %s", decision.name)
            _LOGGER.debug("  Reason  : %s", decision.reason)

    included = sum(1 for decision in decisions if decision.included)
    _LOGGER.debug("Summary:")
    _LOGGER.debug("  Included interfaces : %d", included)
    _LOGGER.debug("  Excluded interfaces : %d", len(decisions) - included)
    _LOGGER.debug("  Addresses to scan   : %d", address_count)


def get_local_ip_ranges() -> list[str]:
    """Retrieve IPv4 hosts on active, physical local network interfaces."""
    ips_to_scan: set[str] = set()
    decisions: list[_InterfaceDecision] = []

    interfaces = _interfaces_from_psutil()
    if interfaces:
        for info in interfaces:
            _process_interface(info, ips_to_scan, decisions)

    if not ips_to_scan:
        decisions = []
        interfaces = _interfaces_from_netifaces()
        if interfaces:
            for info in interfaces:
                _process_interface(info, ips_to_scan, decisions)

    if not ips_to_scan:
        decisions = []
        _add_route_fallback(ips_to_scan, decisions)

    _log_interface_report(decisions, len(ips_to_scan))
    return sorted(ips_to_scan)


async def async_scan_port(
    ip: str,
    port: int = DEFAULT_PORT,
    timeout: float = DEFAULT_PORT_SCAN_TIMEOUT,
) -> bool:
    """Asynchronously check if a TCP port is open."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (asyncio.TimeoutError, OSError):
        return False


async def async_scan_network(
    ips: list[str],
    port: int = DEFAULT_PORT,
    max_concurrent: int = DEFAULT_MAX_CONCURRENT_SCANS,
    timeout: float = DEFAULT_PORT_SCAN_TIMEOUT,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[str]:
    """Scan a list of IP addresses for an open port without blocking.

    A bounded pool of workers consumes the addresses instead of creating one
    task per IP, which keeps memory and scheduling overhead predictable even
    for large LANs. Results keep the order of ``ips``.
    """
    if not ips:
        return []

    pending: asyncio.Queue[str] = asyncio.Queue()
    for target_ip in ips:
        pending.put_nowait(target_ip)

    total_count = len(ips)
    scanned_count = 0
    open_ips: set[str] = set()

    async def _worker() -> None:
        nonlocal scanned_count
        while True:
            try:
                target_ip = pending.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                if await async_scan_port(target_ip, port=port, timeout=timeout):
                    open_ips.add(target_ip)
            except Exception as err:  # pragma: no cover - defensive guard
                _LOGGER.debug("Port scan failed for %s: %s", target_ip, err)
            finally:
                scanned_count += 1
                if progress_callback:
                    progress_callback(scanned_count, total_count)
                pending.task_done()

    worker_count = max(1, min(max_concurrent, total_count))
    workers = [asyncio.create_task(_worker()) for _ in range(worker_count)]
    await asyncio.gather(*workers, return_exceptions=True)
    return [ip for ip in ips if ip in open_ips]


def _has_vigipool_http_signature(
    ip: str,
    timeout: float = DEFAULT_HTTP_PROBE_TIMEOUT,
) -> bool:
    """Return True only when GET / returns the exact Vigipool signature.

    The Vigipool device currently answers with the body 'File does not exist'
    (often with HTTP status 404). HTTP status is deliberately not used as the
    classifier: the response body is the identifying signature.
    """
    request = Request(
        f"http://{ip}/",
        headers={"User-Agent": "HomeAssistant-Vigipool-Discovery"},
        method="GET",
    )
    try:
        try:
            response = urlopen(request, timeout=timeout)
        except HTTPError as err:
            # urllib raises for 4xx/5xx, but the response body is still useful.
            response = err

        with response:
            body = response.read(4096).decode("utf-8", errors="replace").strip()
        return body == VIGIPOOL_HTTP_SIGNATURE
    except (OSError, URLError, TimeoutError, ValueError) as err:
        _LOGGER.debug("HTTP signature check failed for %s: %s", ip, err)
        return False


async def async_check_vigipool_http_signature(
    ip: str,
    timeout: float = DEFAULT_HTTP_PROBE_TIMEOUT,
) -> bool:
    """Check the Vigipool HTTP signature without blocking the event loop."""
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _has_vigipool_http_signature, ip, timeout),
            timeout=timeout + 0.5,
        )
    except (asyncio.TimeoutError, OSError) as err:
        _LOGGER.debug("HTTP signature check timed out for %s: %s", ip, err)
        return False


async def async_probe_vigipool_broker(
    ip: str,
    port: int = DEFAULT_PORT,
    timeout: float = DEFAULT_MQTT_PROBE_TIMEOUT,
) -> DiscoveredVigipoolBroker | None:
    """Verify if an open MQTT port belongs to a broker exposing Vigipool topics."""
    if mqtt is None:
        _LOGGER.error("paho-mqtt is required for Vigipool discovery")
        return None

    loop = asyncio.get_running_loop()
    discovered_devices: dict[str, DiscoveredDevice] = {}

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            client.subscribe("#")

    def on_message(client, userdata, msg):
        match = VIGIPOOL_TOPIC_REGEX.match(msg.topic)
        if not match:
            return
        prefix = match.group(1).lower()
        mac = match.group(2).upper()
        device_id = f"{prefix}_{mac}"
        model_info = DEVICE_MODELS.get(
            prefix,
            {
                "model": f"Vigipool {prefix.capitalize()}",
                "url": "https://www.ccei-pool.com/fr/gamme-vigipool",
                "description": "Vigipool device",
            },
        )
        if device_id not in discovered_devices:
            discovered_devices[device_id] = DiscoveredDevice(
                device_id=device_id,
                prefix=prefix,
                mac=mac,
                model=model_info["model"],
                description=model_info["description"],
                url=model_info["url"],
            )

    client_id = f"vigipool_probe_{int(time.time() * 1000) % 100000}"
    client = get_mqtt_client(client_id, clean_session=True)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        await loop.run_in_executor(
            None, lambda: client.connect(ip, port, keepalive=10)
        )
        client.loop_start()
        try:
            await asyncio.sleep(timeout)
        finally:
            client.loop_stop()
            try:
                client.disconnect()
            except Exception:
                pass
    except Exception as err:
        _LOGGER.debug("Failed connecting to potential broker %s:%s - %s", ip, port, err)
        return None

    if not discovered_devices:
        return None

    primary_id = ""
    for pref in ("tild", "anteam", "vigipool"):
        for dev_id in discovered_devices:
            if dev_id.startswith(pref):
                primary_id = dev_id
                break
        if primary_id:
            break
    if not primary_id:
        primary_id = next(iter(discovered_devices))

    return DiscoveredVigipoolBroker(
        ip=ip,
        port=port,
        primary_device_id=primary_id,
        devices=discovered_devices,
    )


async def async_discover_vigipool_brokers(
    progress_callback: Callable[[int, int], None] | None = None,
    custom_ips: list[str] | None = None,
    port: int = DEFAULT_PORT,
) -> list[DiscoveredVigipoolBroker]:
    """Discover Vigipool devices by HTTP signature first, then MQTT topics."""
    ips_to_scan = custom_ips if custom_ips is not None else get_local_ip_ranges()
    if not ips_to_scan:
        _LOGGER.warning("No local network interfaces found to scan for Vigipool")
        return []

    _LOGGER.info("Scanning %d IPs for the Vigipool HTTP signature", len(ips_to_scan))
    http_open_ips = await async_scan_network(
        ips_to_scan,
        port=80,
        progress_callback=progress_callback,
    )
    if not http_open_ips:
        _LOGGER.info("No HTTP servers found during Vigipool discovery")
        return []

    signature_results = await asyncio.gather(
        *(async_check_vigipool_http_signature(ip) for ip in http_open_ips)
    )
    vigipool_ips = [
        ip for ip, matches in zip(http_open_ips, signature_results) if matches
    ]
    _LOGGER.debug(
        "%d/%d HTTP servers match the Vigipool signature: %s",
        len(vigipool_ips),
        len(http_open_ips),
        vigipool_ips,
    )
    if not vigipool_ips:
        return []

    mqtt_open_ips = await async_scan_network(vigipool_ips, port=port)
    discovered_brokers: list[DiscoveredVigipoolBroker] = []
    for open_ip in mqtt_open_ips:
        broker = await async_probe_vigipool_broker(open_ip, port=port)
        if broker:
            _LOGGER.info(
                "Discovered Vigipool broker at %s with devices: %s",
                open_ip,
                list(broker.devices),
            )
            discovered_brokers.append(broker)
        else:
            _LOGGER.debug(
                "IP %s matches the HTTP signature but has no Vigipool MQTT topics",
                open_ip,
            )
    return discovered_brokers
