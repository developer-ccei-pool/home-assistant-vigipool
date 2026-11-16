"""Tests for Vigipool __init__ setup and unload."""
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.vigipool import async_reload_entry, async_setup_entry, async_unload_entry
from custom_components.vigipool.const import CONF_BROKER, CONF_PORT, DOMAIN


class TestInit(IsolatedAsyncioTestCase):
    """Test component initialization and unloading."""

    async def test_setup_and_unload_entry(self):
        """Test setting up and cleanly unloading a config entry."""
        hass = MagicMock()
        hass.data = {}
        hass.config_entries = MagicMock()
        hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

        entry = MagicMock()
        entry.entry_id = "test_entry_456"
        entry.data = {CONF_BROKER: "192.168.1.50", CONF_PORT: 1883}
        entry.options = {}

        with patch("custom_components.vigipool.coordinator.VigipoolCoordinator.async_start", new_callable=AsyncMock) as mock_start, \
             patch("custom_components.vigipool.coordinator.VigipoolCoordinator.async_stop", new_callable=AsyncMock) as mock_stop:
            mock_start.return_value = True
            mock_stop.return_value = None

            # Setup entry
            ok = await async_setup_entry(hass, entry)
            self.assertTrue(ok)
            self.assertIn(DOMAIN, hass.data)
            self.assertIn(entry.entry_id, hass.data[DOMAIN])
            mock_start.assert_called_once()
            hass.config_entries.async_forward_entry_setups.assert_called_once()

            # Unload entry
            unload_ok = await async_unload_entry(hass, entry)
            self.assertTrue(unload_ok)
            mock_stop.assert_called_once()
            self.assertNotIn(entry.entry_id, hass.data[DOMAIN])

    async def test_reload_entry(self):
        """Test reload entry callback."""
        hass = MagicMock()
        hass.config_entries = MagicMock()
        hass.config_entries.async_reload = AsyncMock()

        entry = MagicMock()
        entry.entry_id = "test_reload_1"

        await async_reload_entry(hass, entry)
        hass.config_entries.async_reload.assert_called_once_with("test_reload_1")
