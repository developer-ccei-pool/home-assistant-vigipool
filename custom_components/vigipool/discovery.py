"""Network discovery and Vigipool MQTT broker detection."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import ipaddress
import logging
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


def _is_virtual_interface(name: str) -> bool:
    """Return True for interfaces that should not be scanned."""
    name = name.lower()
    virtual_prefixes = (
        "lo", "docker", "br-", "br_", "veth", "virbr",
        "wg", "tun", "tap", "tailscale", "ham",
        "zt", "podman", "cni",
    )
    return name.startswith(virtual_prefixes)


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
        if network.prefixlen < 20:
            _LOGGER.debug("Skipping excessively large network: %s", network)
            return []
        return [str(host) for host in network.hosts()]
    except ValueError:
        return []


def get_local_ip_ranges() -> list[str]:
    """Retrieve IPv4 hosts on active, relevant local network interfaces."""
    ips_to_scan: set[str] = set()

    try:
        import psutil

        interface_stats = psutil.net_if_stats()
        for iface, addresses in psutil.net_if_addrs().items():
            stats = interface_stats.get(iface)
            if _is_virtual_interface(iface) or stats is None or not stats.isup:
                continue
            for address in addresses:
                if address.family != socket.AF_INET:
                    continue
                if not address.address or not address.netmask:
                    continue
                ips_to_scan.update(
                    _network_hosts_for_interface(address.address, address.netmask)
                )
    except Exception as err:
        _LOGGER.debug("psutil network discovery failed: %s", err)

    if not ips_to_scan:
        try:
            import netifaces

            for iface in netifaces.interfaces():
                if _is_virtual_interface(iface):
                    continue
                addrs = netifaces.ifaddresses(iface)
                for address in addrs.get(netifaces.AF_INET, []):
                    ip = address.get("addr")
                    mask = address.get("netmask")
                    if ip and mask:
                        ips_to_scan.update(_network_hosts_for_interface(ip, mask))
        except Exception as err:
            _LOGGER.debug("netifaces discovery failed: %s", err)

    if not ips_to_scan:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                local_ip = sock.getsockname()[0]
            ips_to_scan.update(
                _network_hosts_for_interface(local_ip, "255.255.255.0")
            )
        except Exception as err:
            _LOGGER.debug("Socket route fallback failed: %s", err)

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
    """Scan a list of IP addresses for an open port without blocking."""
    semaphore = asyncio.Semaphore(max_concurrent)
    scanned_count = 0
    total_count = len(ips)
    open_ips: list[str] = []

    async def _worker(target_ip: str) -> None:
        nonlocal scanned_count
        async with semaphore:
            is_open = await async_scan_port(target_ip, port=port, timeout=timeout)
            if is_open:
                open_ips.append(target_ip)
            scanned_count += 1
            if progress_callback:
                progress_callback(scanned_count, total_count)

    tasks = [asyncio.create_task(_worker(ip)) for ip in ips]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    return open_ips


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
