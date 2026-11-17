"""Tests for Vigipool config flow."""
import inspect
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.vigipool.config_flow import (
    ACTION_AUTO,
    VigipoolConfigFlow,
    VigipoolOptionsFlowHandler,
)
from custom_components.vigipool.const import CONF_BROKER, CONF_PORT
from custom_components.vigipool.discovery import DiscoveredDevice, DiscoveredVigipoolBroker


class _AbortFlowError(Exception):
    """Stand-in for homeassistant.data_entry_flow.AbortFlow in tests."""


def _make_broker(ip="192.168.1.50", device_id="tild_84CCA89E2340"):
    return DiscoveredVigipoolBroker(
        ip=ip, port=1883,
        primary_device_id=device_id,
        devices={device_id: DiscoveredDevice(
            device_id=device_id, prefix=device_id.split("_")[0],
            mac=device_id.split("_")[1], model="Tild VP",
            description="Pool controller", url="https://ccei-pool.com",
        )},
    )


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

    async def test_abort_if_unique_id_configured_is_synchronous(self):
        """Regression guard: HA's method is sync and must never be awaited."""
        self.assertFalse(
            inspect.iscoroutinefunction(
                VigipoolConfigFlow._abort_if_unique_id_configured
            )
        )

    async def test_flow_select_creates_entry_for_discovered_device(self):
        """Selecting a discovered broker creates the entry and sets unique_id."""
        flow = VigipoolConfigFlow()
        flow.hass = MagicMock()
        broker = _make_broker()
        flow._discovered_brokers = {broker.ip: broker}
        # A plain MagicMock is not awaitable: if the flow ever awaits this call
        # again, the test fails with a TypeError instead of passing silently.
        with patch.object(
            flow, "_abort_if_unique_id_configured", wraps=flow._abort_if_unique_id_configured
        ) as mock_abort:
            result = await flow.async_step_select({"selected_broker": broker.ip})
        mock_abort.assert_called_once_with()
        self.assertEqual(flow.unique_id, "tild_84CCA89E2340")
        self.assertEqual(result["title"], broker.display_name)
        self.assertEqual(result["data"][CONF_BROKER], "192.168.1.50")
        self.assertEqual(result["data"][CONF_PORT], 1883)

    async def test_flow_select_aborts_when_already_configured(self):
        """Duplicate detection still aborts the flow for configured devices."""
        flow = VigipoolConfigFlow()
        flow.hass = MagicMock()
        broker = _make_broker()
        flow._discovered_brokers = {broker.ip: broker}
        with patch.object(
            flow,
            "_abort_if_unique_id_configured",
            side_effect=_AbortFlowError("already_configured"),
        ) as mock_abort:
            with self.assertRaises(_AbortFlowError):
                await flow.async_step_select({"selected_broker": broker.ip})
        mock_abort.assert_called_once_with()

    async def test_flow_manual_aborts_when_already_configured(self):
        """The manual step runs the same duplicate check, synchronously."""
        flow = VigipoolConfigFlow()
        flow.hass = MagicMock()
        broker = _make_broker(ip="192.168.1.75")
        with patch(
            "custom_components.vigipool.config_flow.async_check_vigipool_http_signature",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "custom_components.vigipool.config_flow.async_probe_vigipool_broker",
            new_callable=AsyncMock, return_value=broker,
        ), patch.object(
            flow,
            "_abort_if_unique_id_configured",
            side_effect=_AbortFlowError("already_configured"),
        ) as mock_abort:
            with self.assertRaises(_AbortFlowError):
                await flow.async_step_manual({CONF_BROKER: "192.168.1.75", CONF_PORT: 1883})
        mock_abort.assert_called_once_with()

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
