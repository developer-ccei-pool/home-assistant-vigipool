"""Config flow for CCEI Vigipool integration."""
from __future__ import annotations

import logging
from typing import Any

try:
    import voluptuous as vol
except ImportError:
    class vol:
        @staticmethod
        def Schema(schema_dict):
            return schema_dict
        @staticmethod
        def Required(key, default=None):
            return key
        @staticmethod
        def Optional(key, default=None):
            return key
        @staticmethod
        def In(choices):
            return lambda x: x
        @staticmethod
        def All(*validators):
            return lambda x: x
        @staticmethod
        def Coerce(typ):
            return typ
        @staticmethod
        def Clamp(**kwargs):
            return lambda x: x

try:
    from homeassistant import config_entries
    from homeassistant.core import callback
    from homeassistant.data_entry_flow import FlowResult
except ImportError:
    class FlowResult(dict):
        pass

    class config_entries:
        class ConfigFlow:
            VERSION = 1
            def __init_subclass__(cls, **kwargs):
                pass
            def async_show_form(self, **kwargs):
                return kwargs
            def async_create_entry(self, **kwargs):
                return kwargs
            def async_abort(self, **kwargs):
                return kwargs
            async def _abort_if_unique_id_configured(self, updates=None):
                pass
            async def async_set_unique_id(self, uid):
                self.unique_id = uid

        class OptionsFlow:
            def __init__(self, entry):
                self.entry = entry
            def async_show_form(self, **kwargs):
                return kwargs
            def async_create_entry(self, **kwargs):
                return kwargs

    def callback(f):
        return f

from .const import (
    CONF_BROKER,
    CONF_DISCOVERY_INTERVAL,
    CONF_PORT,
    CONF_PRIMARY_DEVICE_ID,
    DEFAULT_DISCOVERY_INTERVAL,
    DEFAULT_PORT,
    DOMAIN,
)
from .discovery import (
    DiscoveredVigipoolBroker,
    async_check_vigipool_http_signature,
    async_discover_vigipool_brokers,
    async_probe_vigipool_broker,
)

_LOGGER = logging.getLogger(__name__)

ACTION_AUTO = "auto"
ACTION_MANUAL = "manual"
ACTION_RESCAN = "rescan"


class VigipoolConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for CCEI Vigipool."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_brokers: dict[str, DiscoveredVigipoolBroker] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Choose between automatic discovery and manual entry."""
        if user_input is not None:
            if user_input.get("discovery_type") == ACTION_AUTO:
                return await self.async_step_scan()
            return await self.async_step_manual()

        schema = vol.Schema({
            vol.Required("discovery_type", default=ACTION_AUTO): vol.In({
                ACTION_AUTO: "Rechercher automatiquement les équipements Vigipool",
                ACTION_MANUAL: "Saisie manuelle de l'adresse IP",
            })
        })
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_scan(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Scan local subnets for Vigipool brokers."""
        _LOGGER.info("Starting automatic discovery of Vigipool equipment...")
        discovered = await async_discover_vigipool_brokers()
        self._discovered_brokers = {b.ip: b for b in discovered}
        if not self._discovered_brokers:
            return await self.async_step_no_devices()
        return await self.async_step_select()

    async def async_step_no_devices(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle scenario when no Vigipool equipment is discovered."""
        if user_input is not None:
            if user_input.get("action") == ACTION_RESCAN:
                return await self.async_step_scan()
            return await self.async_step_manual()

        schema = vol.Schema({
            vol.Required("action", default=ACTION_RESCAN): vol.In({
                ACTION_RESCAN: "Relancer la recherche",
                ACTION_MANUAL: "Saisie manuelle de l'adresse IP",
            })
        })
        return self.async_show_form(
            step_id="no_devices",
            data_schema=schema,
            errors={"base": "no_devices_found"},
        )

    async def async_step_select(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Present discovered Vigipool brokers for user selection."""
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input.get("selected_broker")
            if selected == ACTION_RESCAN:
                return await self.async_step_scan()
            if selected == ACTION_MANUAL:
                return await self.async_step_manual()
            broker = self._discovered_brokers.get(selected)
            if broker:
                unique_id = broker.primary_device_id or broker.ip
                await self.async_set_unique_id(unique_id)
                await self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=broker.display_name,
                    data={
                        CONF_BROKER: broker.ip,
                        CONF_PORT: broker.port,
                        CONF_PRIMARY_DEVICE_ID: broker.primary_device_id,
                    },
                )
            errors["base"] = "cannot_connect"

        options = {b.ip: b.display_name for b in self._discovered_brokers.values()}
        options[ACTION_RESCAN] = "🔄 Relancer la recherche"
        options[ACTION_MANUAL] = "✏️ Saisie manuelle de l'adresse IP"
        schema = vol.Schema({
            vol.Required(
                "selected_broker",
                default=next(iter(self._discovered_brokers.keys())),
            ): vol.In(options)
        })
        return self.async_show_form(
            step_id="select",
            data_schema=schema,
            errors=errors,
            description_placeholders={"count": str(len(self._discovered_brokers))},
        )

    async def _async_validate_vigipool_host(self, host: str, port: int):
        """Validate the HTTP identity first, then inspect the MQTT topics."""
        if not await async_check_vigipool_http_signature(host):
            return None
        return await async_probe_vigipool_broker(host, port=port)

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle manual IP configuration."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_BROKER].strip()
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            broker = await self._async_validate_vigipool_host(host, port)
            if broker is None:
                errors["base"] = "not_vigipool"
            else:
                unique_id = broker.primary_device_id or host
                await self.async_set_unique_id(unique_id)
                await self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=broker.display_name,
                    data={
                        CONF_BROKER: host,
                        CONF_PORT: port,
                        CONF_PRIMARY_DEVICE_ID: broker.primary_device_id,
                    },
                )

        schema = vol.Schema({
            vol.Required(CONF_BROKER): str,
            vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        })
        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle reconfiguration of gateway IP."""
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if user_input is not None:
            host = user_input[CONF_BROKER].strip()
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            broker = await self._async_validate_vigipool_host(host, port)
            if broker is None:
                errors["base"] = "not_vigipool"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        CONF_BROKER: host,
                        CONF_PORT: port,
                        CONF_PRIMARY_DEVICE_ID: broker.primary_device_id,
                    },
                )

        current_host = entry.data.get(CONF_BROKER, "")
        schema = vol.Schema({
            vol.Required(CONF_BROKER, default=current_host): str,
            vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        })
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> config_entries.OptionsFlow:
        return VigipoolOptionsFlowHandler(config_entry)


class VigipoolOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Vigipool options."""

    def __init__(self, config_entry: Any) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage Vigipool options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current_interval = self.config_entry.options.get(
            CONF_DISCOVERY_INTERVAL, DEFAULT_DISCOVERY_INTERVAL
        )
        schema = vol.Schema({
            vol.Optional(
                CONF_DISCOVERY_INTERVAL,
                default=current_interval,
            ): vol.All(vol.Coerce(int), vol.Clamp(min=0, max=86400)),
        })
        return self.async_show_form(step_id="init", data_schema=schema)
