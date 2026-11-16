"""Base entity class for CCEI Vigipool devices."""
from __future__ import annotations

import logging
from typing import Any

try:
    from homeassistant.helpers.entity import DeviceInfo, Entity
except ImportError:
    # Lightweight mock for standalone tests when Home Assistant core is not in sys.path
    class DeviceInfo(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.__dict__.update(kwargs)

    class Entity:
        def __init__(self):
            self.hass = None
            self._attr_unique_id = None
            self._attr_name = None
            self._attr_device_info = None
            self.entity_id = None

        @property
        def unique_id(self):
            return self._attr_unique_id

        async def async_added_to_hass(self):
            pass

        async def async_will_remove_from_hass(self):
            pass

        def async_write_ha_state(self):
            pass

from .const import DOMAIN, MANUFACTURER
from .coordinator import VigipoolCoordinator

_LOGGER = logging.getLogger(__name__)


class VigipoolBaseEntity(Entity):
    """Base entity representation for Vigipool devices."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: VigipoolCoordinator,
        device_id: str,
        entity_key: str,
    ) -> None:
        """Initialize the base entity."""
        super().__init__()
        self.coordinator = coordinator
        self.device_id = device_id
        self.entity_key = entity_key

        self._attr_unique_id = f"{device_id}_{entity_key}"
        self._unsub_listener = None

    @property
    def device(self):
        """Return the DiscoveredDevice object."""
        return self.coordinator.devices.get(self.device_id)

    @property
    def device_info(self) -> DeviceInfo:
        """Return DeviceInfo for Home Assistant device registry."""
        dev = self.device
        model_name = dev.model if dev else "Vigipool Device"
        url = dev.url if dev else "https://www.ccei-pool.com"
        sw_ver = dev.info.get("sw_version") if dev else None
        hw_ver = dev.info.get("hw_version") if dev else None
        serial_no = dev.info.get("serial_number") if dev else None

        info_kwargs = {
            "identifiers": {(DOMAIN, self.device_id)},
            "name": model_name,
            "manufacturer": MANUFACTURER,
            "model": model_name,
            "configuration_url": url,
        }
        if sw_ver:
            info_kwargs["sw_version"] = sw_ver
        if hw_ver:
            info_kwargs["hw_version"] = hw_ver
        if serial_no:
            info_kwargs["serial_number"] = serial_no

        # If this device is not the gateway itself, attach via the gateway
        if self.device_id != self.coordinator.broker_device_id:
            info_kwargs["via_device"] = (DOMAIN, self.coordinator.broker_device_id)

        return DeviceInfo(**info_kwargs)

    @property
    def available(self) -> bool:
        """Return True if coordinator is connected and device is known."""
        if not self.coordinator.is_connected:
            return False
        return self.device_id in self.coordinator.devices

    async def async_added_to_hass(self) -> None:
        """Register coordinator update callback when entity is added."""
        await super().async_added_to_hass()
        self._unsub_listener = self.coordinator.register_listener(
            self.device_id, self._handle_coordinator_update
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister coordinator callback when entity is removed."""
        if self._unsub_listener:
            self._unsub_listener()
            self._unsub_listener = None
        await super().async_will_remove_from_hass()

    def _handle_coordinator_update(self) -> None:
        """Handle state update from coordinator."""
        self.async_write_ha_state()

    def get_device_data(self, key: str, default: Any = None) -> Any:
        """Convenience method to retrieve parsed value for this device."""
        dev_data = self.coordinator.data.get(self.device_id, {})
        return dev_data.get(key, default)


class VigipoolHubBaseEntity(Entity):
    """Base entity representing diagnostic properties of the Vigipool Gateway itself."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: VigipoolCoordinator,
        entity_key: str,
    ) -> None:
        """Initialize gateway entity."""
        super().__init__()
        self.coordinator = coordinator
        self.entity_key = entity_key
        self.hub_id = coordinator.broker_device_id
        self._attr_unique_id = f"{self.hub_id}_{entity_key}"
        self._unsub_listener = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return DeviceInfo for the Vigipool Gateway."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.hub_id)},
            name=f"CCEI Vigipool Gateway ({self.coordinator.host})",
            manufacturer=MANUFACTURER,
            model="Vigipool Gateway",
            configuration_url="https://www.ccei-pool.com/fr/gamme-vigipool",
        )

    @property
    def available(self) -> bool:
        """Gateway diagnostics are always available to report status."""
        return True

    async def async_added_to_hass(self) -> None:
        """Register update callback."""
        await super().async_added_to_hass()
        self._unsub_listener = self.coordinator.register_listener(
            self.hub_id, self._handle_coordinator_update
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callback."""
        if self._unsub_listener:
            self._unsub_listener()
            self._unsub_listener = None
        await super().async_will_remove_from_hass()

    def _handle_coordinator_update(self) -> None:
        """Write state update to HA."""
        self.async_write_ha_state()
