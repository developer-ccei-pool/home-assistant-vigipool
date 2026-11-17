"""Tests for dynamic entity creation from really received MQTT fields."""
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock, patch

from custom_components.vigipool.binary_sensor import VigipoolBinarySensor
from custom_components.vigipool.capabilities import (
    FIELD_SPECS,
    field_already_covered,
    is_metadata_field,
)
from custom_components.vigipool.const import (
    DEVICE_MODELS,
    DOMAIN,
    SIGNAL_VIGIPOOL_NEW_DEVICE,
    SIGNAL_VIGIPOOL_NEW_FIELD,
)
from custom_components.vigipool.coordinator import VigipoolCoordinator
from custom_components.vigipool.select import SELECT_DESCRIPTIONS
from custom_components.vigipool.sensor import VigipoolSensor


def _topic(device_id: str, data_type: str, field: str, category: str) -> str:
    return f"{device_id}/{data_type}/{field}/{category}/reported"


class TestDynamicEntities(IsolatedAsyncioTestCase):
    """Entities must be created from MQTT fields actually received."""

    def setUp(self):
        self.mock_hass = MagicMock()
        self.mock_entry = MagicMock()
        self.mock_entry.entry_id = "test_dyn"
        self.coordinator = VigipoolCoordinator(
            hass=self.mock_hass,
            entry=self.mock_entry,
            host="192.168.1.100",
            primary_device_id="tild_84CCA89E2340",
        )
        # Entity platforms fetch the coordinator from hass.data[DOMAIN][entry_id].
        self.mock_hass.data = {DOMAIN: {self.mock_entry.entry_id: self.coordinator}}

    async def _setup_platform(self, module):
        """Run a platform setup and return the added entities."""
        added: list = []
        await module.async_setup_entry(
            self.mock_hass, self.mock_entry, lambda entities, **_: added.extend(entities)
        )
        return added

    async def test_tildrc_device_registered_and_sensor_created(self):
        """A Tildrc publishing its water temperature gets a real sensor."""
        device_id = "tildrc_ABCDEF123456"
        self.coordinator._handle_mqtt_message(
            _topic(device_id, "u16_r", "value_temp", "value"), "245"
        )

        # The device is registered with a proper model name.
        self.assertEqual(self.coordinator.devices[device_id].model, "Tildrc")
        self.assertIn("tildrc", DEVICE_MODELS)
        self.assertEqual(self.coordinator.data[device_id]["value_temp"], 24.5)

        added = await self._setup_platform(_sensor_module())
        sensors = [e for e in added if isinstance(e, VigipoolSensor)]
        temp = next(s for s in sensors if s.unique_id == f"{device_id}_value_temp")
        self.assertEqual(temp.native_value, 24.5)
        self.assertEqual(temp.native_unit_of_measurement, "°C")
        self.assertEqual(temp.device_class, "temperature")
        self.assertEqual(temp.device_info["model"], "Tildrc")

    async def test_dynamic_binary_sensor_when_no_writable_entity_exists(self):
        """A binary state is created only when no switch/light covers it."""
        device_id = "ziphox_112233445566"
        self.coordinator._handle_mqtt_message(
            _topic(device_id, "u8_r", "light_state", "info"), "1"
        )
        sensors_and_bs = await self._setup_platform(_binary_module())
        light = next(
            e
            for e in sensors_and_bs
            if isinstance(e, VigipoolBinarySensor) and e.unique_id == f"{device_id}_light_state"
        )
        self.assertTrue(light.is_on)
        self.assertEqual(light.device_class, "power")

    async def test_writable_fields_are_not_duplicated(self):
        """filt_state on a Tild is already a switch: no dynamic duplicate."""
        device_id = "tild_84CCA89E2340"
        self.coordinator.devices[device_id] = MagicMock(prefix="tild")
        self.coordinator.data[device_id] = {
            "filt_state": True,
            "value_temp": 26.0,
            "value_temp_raw": "260",
            "value_temp_ts": 0.0,
            "value_temp_direction": "reported",
        }
        self.assertTrue(field_already_covered("tild", "filt_state"))
        binary = await self._setup_platform(_binary_module())
        self.assertFalse(
            any(getattr(e, "unique_id", "") == f"{device_id}_filt_state" for e in binary)
        )

    def test_metadata_fields_never_exposed(self):
        """Coordinator bookkeeping keys are never turned into entities."""
        self.assertTrue(is_metadata_field("value_temp_raw"))
        self.assertTrue(is_metadata_field("value_temp_ts"))
        self.assertTrue(is_metadata_field("value_temp_direction"))
        self.assertFalse(is_metadata_field("value_temp"))

    async def test_unknown_field_creates_no_entity(self):
        """Fields outside the documented catalogue create nothing (no fakes)."""
        device_id = "tildrc_ABCDEF123456"
        self.coordinator._handle_mqtt_message(
            _topic(device_id, "u8_r", "totally_unknown_metric", "info"), "42"
        )
        self.assertIn("totally_unknown_metric", self.coordinator.data[device_id])
        entities = await self._setup_platform(_sensor_module()) + await self._setup_platform(_binary_module())
        self.assertFalse(
            any(
                getattr(e, "unique_id", "").startswith(device_id)
                and "unknown" in getattr(e, "unique_id", "")
                for e in entities
            )
        )

    def test_new_field_signal_dispatched_once_per_device_field(self):
        """The creation signal fires exactly once per (device, field) pair."""
        device_id = "tildrc_ABCDEF123456"
        dispatched: list[tuple] = []
        with patch(
            "custom_components.vigipool.coordinator.async_dispatcher_send",
            side_effect=lambda hass, signal, *args: dispatched.append((signal, args)),
        ):
            for _ in range(2):
                self.coordinator._handle_mqtt_message(
                    _topic(device_id, "u16_r", "value_temp", "value"), "245"
                )
        field_signals = [d for d in dispatched if d[0] == SIGNAL_VIGIPOOL_NEW_FIELD.format("test_dyn")]
        device_signals = [d for d in dispatched if d[0] == SIGNAL_VIGIPOOL_NEW_DEVICE.format("test_dyn")]
        self.assertEqual(len(field_signals), 1)
        self.assertEqual(field_signals[0][1], (device_id, "value_temp"))
        self.assertEqual(len(device_signals), 1)

    def test_anteavs_gets_filtration_mode_select(self):
        """AnteaVS is covered by the documented filtration mode selector."""
        desc = next(d for d in SELECT_DESCRIPTIONS if d.key == "filt_mode")
        self.assertIn("anteavs", desc.supported_prefixes)
        self.assertTrue(field_already_covered("anteavs", "filt_mode"))

    def test_catalogue_matches_real_fields(self):
        """Every catalogue field maps to a read-only platform only."""
        for field_name, spec in FIELD_SPECS.items():
            with self.subTest(field=field_name):
                self.assertIn(spec.platform, ("sensor", "binary_sensor"))


def _sensor_module():
    from custom_components.vigipool import sensor

    return sensor


def _binary_module():
    from custom_components.vigipool import binary_sensor

    return binary_sensor
