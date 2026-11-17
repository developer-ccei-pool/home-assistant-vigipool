"""Tests for Vigipool config flow."""
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.vigipool.config_flow import (
    ACTION_AUTO,
    VigipoolConfigFlow,
    VigipoolOptionsFlowHandler,
)
from custom_components.vigipool.const import CONF_BROKER, CONF_PORT
from custom_components.vigipool.discovery import DiscoveredDevice, DiscoveredVigipoolBroker


class TestConfigFlow(IsolatedAsyncioTestCase):
    async def test_flow_user_step_choose_auto(self):
        flow = VigipoolConfigFlow()
        flow.hass = MagicMock()
        with patch.object(flow, "async_step_scan", new_callable=AsyncMock) as mock_scan:
            mock_scan.return_value = {"type": "form", "step_id": "select"}
            result = await flow.async_step_user({"discovery_type": ACTION_AUTO})
            mock_scan.assert_called_once()
            self.assertEqual(result["step_id"], "select")

    async def test_flow_auto_discovery_success(self):
        flow = VigipoolConfigFlow()
        flow.hass = MagicMock()
        dev = DiscoveredDevice(
            device_id="tild_84CCA89E2340", prefix="tild", mac="84CCA89E2340",
            model="Tild VP", description="Pool controller", url="https://ccei-pool.com",
        )
        broker = DiscoveredVigipoolBroker(
            ip="192.168.1.50", port=1883,
            primary_device_id="tild_84CCA89E2340",
            devices={"tild_84CCA89E2340": dev},
        )
        with patch(
            "custom_components.vigipool.config_flow.async_discover_vigipool_brokers",
            return_value=[broker],
        ):
            result = await flow.async_step_scan()
            self.assertEqual(result["step_id"], "select")
            res_entry = await flow.async_step_select({"selected_broker": "192.168.1.50"})
            self.assertEqual(res_entry["title"], broker.display_name)
            self.assertEqual(res_entry["data"][CONF_BROKER], "192.168.1.50")
            self.assertEqual(res_entry["data"][CONF_PORT], 1883)

    async def test_flow_auto_discovery_no_devices(self):
        flow = VigipoolConfigFlow()
        flow.hass = MagicMock()
        with patch(
            "custom_components.vigipool.config_flow.async_discover_vigipool_brokers",
            return_value=[],
        ):
            result = await flow.async_step_scan()
            self.assertEqual(result["step_id"], "no_devices")
            self.assertEqual(result["errors"], {"base": "no_devices_found"})

    async def test_flow_manual_valid_ip(self):
        flow = VigipoolConfigFlow()
        flow.hass = MagicMock()
        broker = DiscoveredVigipoolBroker(
            ip="192.168.1.75", port=1883,
            primary_device_id="tild_84CCA89E2340",
            devices={"tild_84CCA89E2340": DiscoveredDevice(
                device_id="tild_84CCA89E2340", prefix="tild", mac="84CCA89E2340",
                model="Tild VP", description="Pool controller", url="https://ccei-pool.com",
            )},
        )
        with patch(
            "custom_components.vigipool.config_flow.async_check_vigipool_http_signature",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.vigipool.config_flow.async_probe_vigipool_broker",
            new_callable=AsyncMock, return_value=broker,
        ):
            result = await flow.async_step_manual({CONF_BROKER: "192.168.1.75", CONF_PORT: 1883})
            self.assertEqual(result["title"], broker.display_name)
            self.assertEqual(result["data"][CONF_BROKER], "192.168.1.75")

    async def test_flow_manual_rejects_non_vigipool_http(self):
        flow = VigipoolConfigFlow()
        flow.hass = MagicMock()
        with patch(
            "custom_components.vigipool.config_flow.async_check_vigipool_http_signature",
            new_callable=AsyncMock, return_value=False,
        ), patch(
            "custom_components.vigipool.config_flow.async_probe_vigipool_broker",
            new_callable=AsyncMock,
        ) as mock_probe:
            result = await flow.async_step_manual({CONF_BROKER: "192.168.41.121", CONF_PORT: 1883})
            self.assertEqual(result["step_id"], "manual")
            self.assertEqual(result["errors"], {"base": "not_vigipool"})
            mock_probe.assert_not_awaited()

    async def test_flow_manual_invalid_mqtt(self):
        flow = VigipoolConfigFlow()
        flow.hass = MagicMock()
        with patch(
            "custom_components.vigipool.config_flow.async_check_vigipool_http_signature",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.vigipool.config_flow.async_probe_vigipool_broker",
            new_callable=AsyncMock, return_value=None,
        ):
            result = await flow.async_step_manual({CONF_BROKER: "192.168.1.200", CONF_PORT: 1883})
            self.assertEqual(result["step_id"], "manual")
            self.assertEqual(result["errors"], {"base": "not_vigipool"})

    async def test_reconfigure_rejects_non_vigipool_http(self):
        flow = VigipoolConfigFlow()
        flow.hass = MagicMock()
        flow.context = {"entry_id": "entry"}
        entry = MagicMock()
        flow.hass.config_entries.async_get_entry.return_value = entry
        with patch(
            "custom_components.vigipool.config_flow.async_check_vigipool_http_signature",
            new_callable=AsyncMock, return_value=False,
        ), patch(
            "custom_components.vigipool.config_flow.async_probe_vigipool_broker",
            new_callable=AsyncMock,
        ) as mock_probe:
            result = await flow.async_step_reconfigure({CONF_BROKER: "192.168.41.121", CONF_PORT: 1883})
            self.assertEqual(result["step_id"], "reconfigure")
            self.assertEqual(result["errors"], {"base": "not_vigipool"})
            mock_probe.assert_not_awaited()

    async def test_options_flow(self):
        mock_entry = MagicMock()
        mock_entry.options = {"discovery_interval": 300}
        handler = VigipoolOptionsFlowHandler(mock_entry)
        form = await handler.async_step_init()
        self.assertEqual(form["step_id"], "init")
        res = await handler.async_step_init({"discovery_interval": 600})
        self.assertEqual(res["data"]["discovery_interval"], 600)
