"""Tests for Vigipool coordinator and data handling."""
import asyncio
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.vigipool.coordinator import VigipoolCoordinator


class TestVigipoolCoordinator(IsolatedAsyncioTestCase):
    """Test data update coordinator."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_hass = MagicMock()
        self.mock_entry = MagicMock()
        self.mock_entry.entry_id = "test_entry_123"
        self.mock_entry.options = {}
        self.coordinator = VigipoolCoordinator(
            hass=self.mock_hass,
            entry=self.mock_entry,
            host="192.168.1.50",
            port=1883,
            primary_device_id="tild_84CCA89E2340",
        )

    async def test_dynamic_device_discovery_and_parsing(self):
        """Test that devices and metrics are registered on incoming MQTT messages."""
        listener_called = False

        def on_update():
            nonlocal listener_called
            listener_called = True

        # Register listener before device even exists
        self.coordinator.register_listener("tild_84CCA89E2340", on_update)

        # 1. Temperature message
        self.coordinator._handle_mqtt_message(
            "tild_84CCA89E2340/u16_r/value_temp/value/reported", "255"
        )
        self.assertTrue(listener_called)
        self.assertIn("tild_84CCA89E2340", self.coordinator.devices)
        device = self.coordinator.devices["tild_84CCA89E2340"]
        self.assertEqual(device.model, "Tild VP")
        # 255 should be scaled to 25.5 °C
        self.assertEqual(self.coordinator.data["tild_84CCA89E2340"]["value_temp"], 25.5)

        # 2. Temperature error code (> 65530)
        self.coordinator._handle_mqtt_message(
            "tild_84CCA89E2340/u16_r/value_temp/value/reported", "65534"
        )
        # Should be None (unavailable/error) rather than fabricated value
        self.assertIsNone(self.coordinator.data["tild_84CCA89E2340"]["value_temp"])

        # 3. Filtration switch state
        self.coordinator._handle_mqtt_message(
            "tild_84CCA89E2340/u8_w/filt_state/info/reported", "1"
        )
        self.assertTrue(self.coordinator.data["tild_84CCA89E2340"]["filt_state"])

        self.coordinator._handle_mqtt_message(
            "tild_84CCA89E2340/u8_w/filt_state/info/reported", "0"
        )
        self.assertFalse(self.coordinator.data["tild_84CCA89E2340"]["filt_state"])

        # 4. Auxiliary bitmask (bit 0 = on/off)
        self.coordinator._handle_mqtt_message(
            "tild_84CCA89E2340/u16_w/aux_conf/info/reported", "3"  # odd -> True
        )
        self.assertTrue(self.coordinator.data["tild_84CCA89E2340"]["aux_conf"])

        self.coordinator._handle_mqtt_message(
            "tild_84CCA89E2340/u16_w/aux_conf/info/reported", "2"  # even -> False
        )
        self.assertFalse(self.coordinator.data["tild_84CCA89E2340"]["aux_conf"])

        # 5. pH device & scaling
        self.coordinator._handle_mqtt_message(
            "phileox_30AEA4071850/u16_r/value_ph/value/reported", "720"
        )
        self.assertIn("phileox_30AEA4071850", self.coordinator.devices)
        self.assertEqual(self.coordinator.data["phileox_30AEA4071850"]["value_ph"], 7.20)

        # 6. pH error code (65534 -> None)
        self.coordinator._handle_mqtt_message(
            "phileox_30AEA4071850/u16_r/value_ph/value/reported", "65534"
        )
        self.assertIsNone(self.coordinator.data["phileox_30AEA4071850"]["value_ph"])

        # 7. VigiWatt electrical measurements
        self.coordinator._handle_mqtt_message(
            "vigiwatt_90380CFDB954/u16_r/amp/value/reported", "35"
        )
        # 35 * 0.1 = 3.5 A
        self.assertEqual(self.coordinator.data["vigiwatt_90380CFDB954"]["amp"], 3.5)

        # 8. AnteaM Mode selects
        self.coordinator._handle_mqtt_message(
            "anteam_AABBCCDDEEFF/u8_w/filt_mode/info/reported", "3"
        )
        # 3 -> AUTO
        self.assertEqual(self.coordinator.data["anteam_AABBCCDDEEFF"]["filt_mode"], "AUTO")

    async def test_send_command(self):
        """Test publishing a command to the desired topic."""
        with patch.object(self.coordinator.mqtt_client, "async_publish", new_callable=AsyncMock) as mock_pub:
            mock_pub.return_value = True

            ok = await self.coordinator.async_send_command(
                device_id="tild_84CCA89E2340",
                data_type_rw="u8_w",
                field_name="filt_state",
                category="info",
                value="1",
            )
            self.assertTrue(ok)
            mock_pub.assert_called_once_with(
                "tild_84CCA89E2340/u8_w/filt_state/info/desired", "1"
            )

    async def test_invalid_topics_ignored(self):
        """Test that malformed or non-Vigipool topics are ignored."""
        # Non-matching topics
        self.coordinator._handle_mqtt_message("homeassistant/sensor/foo", "123")
        self.coordinator._handle_mqtt_message("invalid/topic/format", "abc")
        self.assertEqual(len(self.coordinator.devices), 0)

    async def test_vigiwatt_parameters(self):
        """Test parsing all VigiWatt electrical parameters."""
        dev_id = "vigiwatt_90380CFDB954"
        self.coordinator._handle_mqtt_message(f"{dev_id}/u32_r/watt_ind/value/reported", "1500")
        self.coordinator._handle_mqtt_message(f"{dev_id}/u8_r/volt/value/reported", "230")
        self.coordinator._handle_mqtt_message(f"{dev_id}/u8_r/freq/value/reported", "50")
        self.coordinator._handle_mqtt_message(f"{dev_id}/u8_r/pf/value/reported", "95")

        self.assertEqual(self.coordinator.data[dev_id]["watt_ind"], 1500.0)
        self.assertEqual(self.coordinator.data[dev_id]["volt"], 230.0)
        self.assertEqual(self.coordinator.data[dev_id]["freq"], 50.0)
        self.assertEqual(self.coordinator.data[dev_id]["pf"], 95.0)

    async def test_x312_timer_and_color(self):
        """Test VigiBrio timer and color parsing."""
        dev_id = "x312_AABBCCDDEEFF"
        self.coordinator._handle_mqtt_message(f"{dev_id}/s128_w/x3_color/info/reported", "Ocean")
        self.coordinator._handle_mqtt_message(f"{dev_id}/u8_w/x3_bright/info/reported", "75")
        self.coordinator._handle_mqtt_message(f"{dev_id}/u8_w/x3_speed/info/reported", "100")

        self.assertEqual(self.coordinator.data[dev_id]["x3_color"], "Ocean")
        self.assertEqual(self.coordinator.data[dev_id]["x3_bright"], 75)
        self.assertEqual(self.coordinator.data[dev_id]["x3_speed"], 100)

