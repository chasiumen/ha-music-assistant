"""The Navidrome integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthenticationFailed, CannotConnect, NavidromeClient
from .const import DOMAIN, LOGGER


@dataclass
class NavidromeData:
    """Shared data for the Navidrome integration."""

    client: NavidromeClient
    queue: list[dict[str, Any]] = field(default_factory=list)
    current_index: int = 0


type NavidromeConfigEntry = ConfigEntry[NavidromeData]

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.SENSOR]


async def async_setup_entry(
    hass: HomeAssistant, entry: NavidromeConfigEntry
) -> bool:
    """Set up Navidrome from a config entry."""
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, True)
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
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

    data = NavidromeData(client=client)
    entry.runtime_data = data

    # Register cover art proxy view
    hass.http.register_view(NavidromeCoverArtView(data))

    # Register custom queue card frontend resource
    await hass.http.async_register_static_paths(
        [StaticPathConfig(
            url_path="/navidrome/navidrome-queue-card.js",
            path=hass.config.path("custom_components/navidrome/www/navidrome-queue-card.js"),
            cache_headers=True,
        )]
    )
    # Register JS module with HA frontend so the card loads automatically
    from homeassistant.components.frontend import add_extra_js_url
    add_extra_js_url(hass, "/navidrome/navidrome-queue-card.js")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True



async def async_unload_entry(
    hass: HomeAssistant, entry: NavidromeConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


class NavidromeCoverArtView(HomeAssistantView):
    """Proxy cover art requests through HA to avoid SSL issues.

    The browser can't fetch cover art directly from Navidrome when using
    self-signed certs. This view fetches it server-side using our
    SSL-disabled aiohttp session and serves it to the frontend.
    """

    url = "/api/navidrome/cover_art/{item_id}"
    name = "api:navidrome:cover_art"
    requires_auth = False

    def __init__(self, data: NavidromeData) -> None:
        """Initialize the view."""
        self._data = data

    async def get(self, request: web.Request, item_id: str) -> web.Response:
        """Fetch cover art from Navidrome and return it."""
        client = self._data.client
        cover_url = client.cover_art_url(item_id)

        try:
            async with client._session.get(cover_url) as resp:
                if resp.status != 200:
                    return web.Response(status=resp.status)
                content_type = resp.content_type or "image/jpeg"
                body = await resp.read()
                return web.Response(
                    body=body,
                    content_type=content_type,
                    headers={"Cache-Control": "public, max-age=86400"},
                )
        except Exception:
            LOGGER.debug("Failed to fetch cover art for %s", item_id)
            return web.Response(status=502)
