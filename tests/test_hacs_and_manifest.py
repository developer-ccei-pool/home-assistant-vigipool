"""Tests for HACS compliance, manifest validation, strings, and diagnostics."""
import json
import os
from pathlib import Path
import re
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock

from custom_components.vigipool.const import CONF_BROKER, CONF_PORT, DOMAIN
from custom_components.vigipool.coordinator import VigipoolCoordinator
from custom_components.vigipool.diagnostics import async_get_config_entry_diagnostics
from custom_components.vigipool.discovery import DiscoveredDevice


class TestHacsAndManifest(IsolatedAsyncioTestCase):
    """Test HACS and Home Assistant architectural requirements."""

    def setUp(self):
        """Set up paths for testing."""
        self.root_dir = Path(__file__).parent.parent
        self.vigipool_dir = self.root_dir / "custom_components" / "vigipool"

    def test_manifest_json_validity(self):
        """Test manifest.json completeness and validity."""
        manifest_path = self.vigipool_dir / "manifest.json"
        self.assertTrue(manifest_path.exists(), "manifest.json must exist in custom_components/vigipool/")

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        required_keys = [
            "domain",
            "name",
            "codeowners",
            "config_flow",
            "documentation",
            "integration_type",
            "iot_class",
            "issue_tracker",
            "requirements",
            "version",
        ]
        for key in required_keys:
            self.assertIn(key, manifest, f"Key '{key}' is required in manifest.json")

        self.assertEqual(manifest["domain"], "vigipool")
        self.assertEqual(self.vigipool_dir.name, manifest["domain"])
        self.assertTrue(manifest["config_flow"])
        self.assertEqual(manifest["iot_class"], "local_push")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+", "Version must follow SemVer format")
        self.assertIsInstance(manifest["codeowners"], list)
        self.assertGreater(len(manifest["codeowners"]), 0)
        self.assertTrue(manifest["documentation"].startswith("http"))
        self.assertTrue(manifest["issue_tracker"].startswith("http"))
        self.assertIn("paho-mqtt", "".join(manifest["requirements"]))

    def test_hacs_json_validity(self):
        """Test hacs.json completeness and validity."""
        hacs_path = self.root_dir / "hacs.json"
        self.assertTrue(hacs_path.exists(), "hacs.json must exist at root")

        with open(hacs_path, "r", encoding="utf-8") as f:
            hacs_data = json.load(f)

        self.assertIn("name", hacs_data)
        self.assertEqual(hacs_data["name"], "CCEI Vigipool")
        self.assertTrue(hacs_data.get("render_readme", False))
        self.assertIn("homeassistant", hacs_data)

    def test_strings_and_translations_consistency(self):
        """Test strings.json and translations (en.json, fr.json) validity and key parity."""
        strings_path = self.vigipool_dir / "strings.json"
        en_path = self.vigipool_dir / "translations" / "en.json"
        fr_path = self.vigipool_dir / "translations" / "fr.json"

        self.assertTrue(strings_path.exists(), "strings.json must exist in custom_components/vigipool/")
        self.assertTrue(en_path.exists(), "translations/en.json must exist")
        self.assertTrue(fr_path.exists(), "translations/fr.json must exist")

        with open(strings_path, "r", encoding="utf-8") as f:
            strings_data = json.load(f)
        with open(en_path, "r", encoding="utf-8") as f:
            en_data = json.load(f)
        with open(fr_path, "r", encoding="utf-8") as f:
            fr_data = json.load(f)

        # Check top-level sections
        for section in ("config", "options", "entity"):
            self.assertIn(section, strings_data)
            self.assertIn(section, en_data)
            self.assertIn(section, fr_data)

        # Check config steps match
        for step in ("user", "select", "no_devices", "manual", "reconfigure"):
            self.assertIn(step, strings_data["config"]["step"])
            self.assertIn(step, en_data["config"]["step"])
            self.assertIn(step, fr_data["config"]["step"])

        # Check config errors match
        for err in ("cannot_connect", "not_vigipool", "no_devices_found"):
            self.assertIn(err, strings_data["config"]["error"])
            self.assertIn(err, en_data["config"]["error"])
            self.assertIn(err, fr_data["config"]["error"])

    async def test_diagnostics(self):
        """Test async_get_config_entry_diagnostics output."""
        mock_hass = MagicMock()
        mock_entry = MagicMock()
        mock_entry.entry_id = "entry_diag_123"
        mock_entry.domain = DOMAIN
        mock_entry.title = "Vigipool (192.168.1.50)"
        mock_entry.data = {
            CONF_BROKER: "192.168.1.50",
            CONF_PORT: 1883,
            "primary_device_id": "tild_84CCA89E2340",
        }
        mock_entry.options = {"discovery_interval": 300}

        coordinator = VigipoolCoordinator(
            hass=mock_hass,
            entry=mock_entry,
            host="192.168.1.50",
            port=1883,
            primary_device_id="tild_84CCA89E2340",
        )
        coordinator.devices["tild_84CCA89E2340"] = DiscoveredDevice(
            device_id="tild_84CCA89E2340",
            prefix="tild",
            mac="84CCA89E2340",
            model="Tild VP",
            description="Pool controller",
            url="https://ccei-pool.com/fr/produit/tild-vp",
        )
        coordinator.data["tild_84CCA89E2340"] = {
            "value_temp": 28.5,
            "filt_state": True,
        }

        mock_hass.data = {DOMAIN: {mock_entry.entry_id: coordinator}}

        diag = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

        self.assertIn("entry", diag)
        self.assertIn("coordinator", diag)
        self.assertIn("devices", diag)

        self.assertEqual(diag["entry"]["entry_id"], "entry_diag_123")
        self.assertEqual(diag["coordinator"]["host"], "192.168.1.50")
        self.assertEqual(diag["coordinator"]["devices_count"], 1)
        self.assertIn("tild_84CCA89E2340", diag["devices"])
        self.assertEqual(diag["devices"]["tild_84CCA89E2340"]["data"]["value_temp"], 28.5)
