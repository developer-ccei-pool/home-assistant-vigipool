"""Network discovery and Vigipool MQTT broker detection."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import ipaddress
import logging
import socket
import time
from typing import Any, Callable

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None  # Handled during tests or mocks

from .const import (
    DEFAULT_MAX_CONCURRENT_SCANS,
    DEFAULT_MQTT_PROBE_TIMEOUT,
    DEFAULT_PORT,
    DEFAULT_PORT_SCAN_TIMEOUT,
    DEVICE_MODELS,
    VIGIPOOL_TOPIC_REGEX,
)

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


def get_local_ip_ranges() -> list[str]:
    """Retrieve list of accessible IPv4 addresses to scan on local networks.

    Avoids scanning excessively large subnets (> /24) by clamping each interface
    network to the enclosing /24 around the host IP.
    """
    ips_to_scan: set[str] = set()

    # Try netifaces first if available
    try:
        import netifaces

        for iface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(iface)
            if netifaces.AF_INET not in addrs:
                continue
            for addr_info in addrs[netifaces.AF_INET]:
                ip_str = addr_info.get("addr")
                netmask_str = addr_info.get("netmask")
                if not ip_str or not netmask_str:
                    continue
                try:
                    ip_obj = ipaddress.IPv4Address(ip_str)
                    if ip_obj.is_loopback or ip_obj.is_link_local:
                        continue
                    # Create network
                    net_obj = ipaddress.IPv4Network(f"{ip_str}/{netmask_str}", strict=False)
                    # Protect against /16 or /8: clamp to /24 around ip_obj
                    if net_obj.prefixlen < 24:
                        clamped_net = ipaddress.IPv4Network(f"{ip_str}/24", strict=False)
                    else:
                        clamped_net = net_obj

                    for host in clamped_net.hosts():
                        ips_to_scan.add(str(host))
                except ValueError:
                    continue
    except Exception as err:
        _LOGGER.debug("netifaces discovery failed or unavailable: %s", err)

    # Fallback using psutil or socket if netifaces didn't produce IPs
    if not ips_to_scan:
        try:
            import psutil

            for iface, snics in psutil.net_if_addrs().items():
                for snic in snics:
                    if snic.family == socket.AF_INET:
                        ip_str = snic.address
                        netmask_str = snic.netmask
                        if not ip_str or not netmask_str:
                            continue
                        try:
                            ip_obj = ipaddress.IPv4Address(ip_str)
                            if ip_obj.is_loopback or ip_obj.is_link_local:
                                continue
                            net_obj = ipaddress.IPv4Network(f"{ip_str}/{netmask_str}", strict=False)
                            if net_obj.prefixlen < 24:
                                clamped_net = ipaddress.IPv4Network(f"{ip_str}/24", strict=False)
                            else:
                                clamped_net = net_obj
                            for host in clamped_net.hosts():
                                ips_to_scan.add(str(host))
                        except ValueError:
                            continue
        except Exception as err:
            _LOGGER.debug("psutil discovery failed or unavailable: %s", err)

    # Final fallback: local hostname IP /24
    if not ips_to_scan:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                # Use public DNS to find default route interface IP without sending packet
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
            net = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
            for host in net.hosts():
                ips_to_scan.add(str(host))
        except Exception as err:
            _LOGGER.debug("Socket route check fallback failed: %s", err)

    return sorted(list(ips_to_scan))


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


async def async_probe_vigipool_broker(
    ip: str,
    port: int = DEFAULT_PORT,
    timeout: float = DEFAULT_MQTT_PROBE_TIMEOUT,
) -> DiscoveredVigipoolBroker | None:
    """Verify if an open MQTT port belongs to a genuine Vigipool broker.

    Connects, subscribes to '#', and checks for characteristic Vigipool topics.
    Does NOT consider generic MQTT brokers as Vigipool.
    """
    if mqtt is None:
        _LOGGER.error("paho-mqtt is required for Vigipool discovery")
        return None

    loop = asyncio.get_running_loop()
    discovered_devices: dict[str, DiscoveredDevice] = {}
    found_event = asyncio.Event()

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            client.subscribe("#")

    def on_message(client, userdata, msg):
        topic = msg.topic
        match = VIGIPOOL_TOPIC_REGEX.match(topic)
        if match:
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
            loop.call_soon_threadsafe(found_event.set)

    client_id = f"vigipool_probe_{int(time.time() * 1000) % 100000}"
    client = mqtt.Client(client_id=client_id, clean_session=True)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        # Run blocking connect in executor
        await loop.run_in_executor(None, lambda: client.connect(ip, port, keepalive=10))
        client.loop_start()

        # Wait for either discovery or timeout
        try:
            await asyncio.wait_for(found_event.wait(), timeout=timeout)
            # Give a brief moment to collect any other co-located devices
            await asyncio.sleep(0.3)
        except asyncio.TimeoutError:
            pass
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

    # Pick primary device id (prioritize main controllers like tild, anteam, then first)
    primary_id = ""
    for pref in ("tild", "anteam", "vigipool"):
        for dev_id in discovered_devices:
            if dev_id.startswith(pref):
                primary_id = dev_id
                break
        if primary_id:
            break
    if not primary_id and discovered_devices:
        primary_id = next(iter(discovered_devices.keys()))

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
    """Scan local networks and return verified Vigipool brokers."""
    ips_to_scan = custom_ips if custom_ips is not None else get_local_ip_ranges()
    if not ips_to_scan:
        _LOGGER.warning("No local network interfaces found to scan for Vigipool")
        return []

    _LOGGER.info("Scanning %d IPs for Vigipool brokers on port %d", len(ips_to_scan), port)
    open_ips = await async_scan_network(
        ips_to_scan,
        port=port,
        progress_callback=progress_callback,
    )
    _LOGGER.debug("Found %d open ports on 1883: %s", len(open_ips), open_ips)

    discovered_brokers: list[DiscoveredVigipoolBroker] = []
    for open_ip in open_ips:
        broker = await async_probe_vigipool_broker(open_ip, port=port)
        if broker:
            _LOGGER.info("Discovered Vigipool broker at %s with devices: %s", open_ip, list(broker.devices.keys()))
            discovered_brokers.append(broker)
        else:
            _LOGGER.debug("IP %s has port 1883 open but is not a Vigipool broker", open_ip)

    return discovered_brokers
