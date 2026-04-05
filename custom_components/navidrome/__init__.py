"""The Navidrome integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthenticationFailed, CannotConnect, NavidromeClient
from .const import DOMAIN

type NavidromeConfigEntry = ConfigEntry[NavidromeClient]

PLATFORMS = [Platform.MEDIA_PLAYER]


async def async_setup_entry(
    hass: HomeAssistant, entry: NavidromeConfigEntry
) -> bool:
    """Set up Navidrome from a config entry."""
    session = async_get_clientsession(hass)
    client = NavidromeClient(
        session,
        entry.data[CONF_URL],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )

    try:
        await client.ping()
    except AuthenticationFailed as err:
        raise ConfigEntryAuthFailed(err) from err
    except CannotConnect as err:
        raise ConfigEntryNotReady(
            f"Cannot connect to Navidrome server: {err}"
        ) from err

    entry.runtime_data = client

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: NavidromeConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
