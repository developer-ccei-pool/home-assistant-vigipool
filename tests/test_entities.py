"""Tests for Vigipool entity platforms."""
import asyncio
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.vigipool.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    VigipoolBinarySensor,
    VigipoolHubConnectivityBinarySensor,
)
from custom_components.vigipool.button import (
    VigipoolReconnectButton,
    VigipoolRefreshButton,
)
from custom_components.vigipool.coordinator import VigipoolCoordinator
from custom_components.vigipool.discovery import DiscoveredDevice
from custom_components.vigipool.mqtt import ConnectionState
from custom_components.vigipool.light import (
    VigipoolTildLight,
    VigipoolVigiBrioLight,
)
from custom_components.vigipool.number import (
    NUMBER_DESCRIPTIONS,
    VigipoolNumber,
)
from custom_components.vigipool.select import (
    SELECT_DESCRIPTIONS,
    VigipoolModeSelect,
    VigipoolTimerSelect,
)
from custom_components.vigipool.sensor import (
    SENSOR_DESCRIPTIONS,
    VigipoolHubDevicesSensor,
    VigipoolHubStatusSensor,
    VigipoolSensor,
)
from custom_components.vigipool.switch import (
    SWITCH_DESCRIPTIONS,
    VigipoolSwitch,
)


class TestEntities(IsolatedAsyncioTestCase):
    """Test all Vigipool entity platforms."""

    def setUp(self):
        """Set up test environment."""
        self.mock_hass = MagicMock()
        self.mock_entry = MagicMock()
        self.mock_entry.entry_id = "test_1"
        self.coordinator = VigipoolCoordinator(
            hass=self.mock_hass,
            entry=self.mock_entry,
            host="192.168.1.100",
            primary_device_id="tild_84CCA89E2340",
        )
        # Register a Tild device
        self.coordinator.devices["tild_84CCA89E2340"] = DiscoveredDevice(
            device_id="tild_84CCA89E2340",
            prefix="tild",
            mac="84CCA89E2340",
            model="Tild VP",
            description="Pool controller",
            url="https://ccei-pool.com/fr/produit/tild-vp",
        )
        self.coordinator.data["tild_84CCA89E2340"] = {}

    async def test_sensor_entity(self):
        """Test VigipoolSensor state and availability."""
        temp_desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "value_temp")
        sensor = VigipoolSensor(self.coordinator, "tild_84CCA89E2340", temp_desc)

        # Initially no data
        self.assertIsNone(sensor.native_value)

        # Update data via coordinator
        self.coordinator.data["tild_84CCA89E2340"]["value_temp"] = 26.2
        self.assertEqual(sensor.native_value, 26.2)
        self.assertEqual(sensor.unique_id, "tild_84CCA89E2340_value_temp")
        self.assertEqual(sensor.device_info["model"], "Tild VP")

    async def test_binary_sensor_entity(self):
        """Test VigipoolBinarySensor state."""
        flow_desc = next(d for d in BINARY_SENSOR_DESCRIPTIONS if d.key == "flow_on")
        bsensor = VigipoolBinarySensor(self.coordinator, "tild_84CCA89E2340", flow_desc)

        self.assertIsNone(bsensor.is_on)
        self.coordinator.data["tild_84CCA89E2340"]["flow_on"] = True
        self.assertTrue(bsensor.is_on)
        self.coordinator.data["tild_84CCA89E2340"]["flow_on"] = False
        self.assertFalse(bsensor.is_on)

    async def test_switch_entity(self):
        """Test VigipoolSwitch turn on / off."""
        filt_desc = next(d for d in SWITCH_DESCRIPTIONS if d.key == "filt_state")
        sw = VigipoolSwitch(self.coordinator, "tild_84CCA89E2340", filt_desc)

        with patch.object(self.coordinator, "async_send_command", new_callable=AsyncMock) as mock_cmd:
            await sw.async_turn_on()
            mock_cmd.assert_called_with("tild_84CCA89E2340", "u8_w", "filt_state", "info", "1")

            await sw.async_turn_off()
            mock_cmd.assert_called_with("tild_84CCA89E2340", "u8_w", "filt_state", "info", "0")

    async def test_light_entity(self):
        """Test Tild Light entity."""
        light = VigipoolTildLight(self.coordinator, "tild_84CCA89E2340")

        self.coordinator.data["tild_84CCA89E2340"]["light_state"] = True
        self.coordinator.data["tild_84CCA89E2340"]["light_bright"] = 80

        self.assertTrue(light.is_on)
        self.assertEqual(light.brightness, int((80 / 100.0) * 255))

        with patch.object(self.coordinator, "async_send_command", new_callable=AsyncMock) as mock_cmd:
            # Turn on with brightness
            await light.async_turn_on(brightness=128)
            # 128 / 255 * 100 = 50%
            mock_cmd.assert_any_call("tild_84CCA89E2340", "u8_w", "light_bright", "info", 50)
            mock_cmd.assert_any_call("tild_84CCA89E2340", "u8_w", "light_state", "info", "1")

            # Turn off
            await light.async_turn_off()
            mock_cmd.assert_called_with("tild_84CCA89E2340", "u8_w", "light_state", "info", "0")

    async def test_number_entity(self):
        """Test pH Setpoint number entity with scaling."""
        desc = next(d for d in NUMBER_DESCRIPTIONS if d.key == "consigne_ph")
        num = VigipoolNumber(self.coordinator, "tild_84CCA89E2340", desc)

        self.coordinator.data["tild_84CCA89E2340"]["consigne_ph"] = 7.2
        self.assertEqual(num.native_value, 7.2)

        with patch.object(self.coordinator, "async_send_command", new_callable=AsyncMock) as mock_cmd:
            await num.async_set_native_value(7.4)
            # 7.4 * 100 = 740
            mock_cmd.assert_called_with(
                "tild_84CCA89E2340", "u16_w", "consigne_ph", "consigne", "740"
            )

    async def test_select_mode_entity(self):
        """Test AnteaM Mode select entity."""
        desc = next(d for d in SELECT_DESCRIPTIONS if d.key == "filt_mode")
        sel = VigipoolModeSelect(self.coordinator, "tild_84CCA89E2340", desc)

        self.coordinator.data["tild_84CCA89E2340"]["filt_mode"] = "AUTO"
        self.assertEqual(sel.current_option, "AUTO")

        with patch.object(self.coordinator, "async_send_command", new_callable=AsyncMock) as mock_cmd:
            await sel.async_select_option("PROG")
            # PROG is code 2
            mock_cmd.assert_called_with(
                "tild_84CCA89E2340", "u8_w", "filt_mode", "info", "2"
            )

    async def test_hub_diagnostic_entities(self):
        """Test hub status and button entities."""
        status_sensor = VigipoolHubStatusSensor(self.coordinator)
        device_sensor = VigipoolHubDevicesSensor(self.coordinator)
        btn_refresh = VigipoolRefreshButton(self.coordinator)

        self.assertEqual(status_sensor.native_value, "disconnected")
        self.assertEqual(device_sensor.native_value, 1)

        with patch.object(self.coordinator.mqtt_client, "async_subscribe", new_callable=AsyncMock) as mock_sub:
            self.coordinator.mqtt_client._set_state(ConnectionState.CONNECTED)
            await btn_refresh.async_press()
            mock_sub.assert_called_with("#")
