"""The Navidrome integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import voluptuous as vol
from aiohttp import web

from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME, CONF_VERIFY_SSL, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import AuthenticationFailed, CannotConnect, NavidromeClient
from .const import DOMAIN, LOGGER

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_queue"


@dataclass
class NavidromeData:
    """Shared data for the Navidrome integration."""

    client: NavidromeClient
    store: Store | None = None
    queue: list[dict[str, Any]] = field(default_factory=list)
    current_index: int = 0

    async def save_queue(self) -> None:
        """Persist queue to disk."""
        if self.store:
            await self.store.async_save({
                "queue": self.queue,
                "current_index": self.current_index,
            })

    async def load_queue(self) -> None:
        """Restore queue from disk."""
        if not self.store:
            return
        data = await self.store.async_load()
        if data:
            self.queue = data.get("queue", [])
            self.current_index = data.get("current_index", 0)
            LOGGER.info("Restored queue: %d tracks, index %d", len(self.queue), self.current_index)

    async def clear_queue(self) -> None:
        """Clear the queue and persist."""
        self.queue = []
        self.current_index = 0
        await self.save_queue()


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

    # Create shared data with persistent storage
    store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}")
    data = NavidromeData(client=client, store=store)

    # Restore queue from disk
    await data.load_queue()

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
    from homeassistant.components.frontend import add_extra_js_url
    add_extra_js_url(hass, "/navidrome/navidrome-queue-card.js")

    # Register clear_queue service
    async def handle_clear_queue(call: ServiceCall) -> None:
        """Handle clear_queue service call."""
        await data.clear_queue()
        # Also clear the target player
        target = entry.options.get("target_player")
        if target:
            try:
                await hass.services.async_call(
                    "media_player", "media_stop",
                    {"entity_id": target}, blocking=True,
                )
            except Exception:
                pass
            try:
                await hass.services.async_call(
                    "media_player", "clear_playlist",
                    {"entity_id": target}, blocking=True,
                )
            except Exception:
                pass
        LOGGER.info("Queue cleared")

    if not hass.services.has_service(DOMAIN, "clear_queue"):
        hass.services.async_register(
            DOMAIN, "clear_queue", handle_clear_queue, schema=vol.Schema({})
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: NavidromeConfigEntry
) -> bool:
    """Unload a config entry."""
    # Save queue before unloading
    await entry.runtime_data.save_queue()
    hass.services.async_remove(DOMAIN, "clear_queue")
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


class NavidromeCoverArtView(HomeAssistantView):
    """Proxy cover art requests through HA to avoid SSL issues."""

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
