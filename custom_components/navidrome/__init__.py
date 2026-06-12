"""The Navidrome integration."""

from __future__ import annotations

import asyncio
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
from homeassistant.helpers.dispatcher import async_dispatcher_send
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
    hass: Any | None = None
    entry_id: str | None = None
    repeat_mode: str = "off"
    queue_dirty: bool = False
    enqueue_task: Any | None = None  # asyncio.Task | None
    target_lock: Any = field(default_factory=asyncio.Lock)

    def cancel_enqueue(self) -> None:
        """Cancel any in-progress background enqueue task."""
        if self.enqueue_task and not self.enqueue_task.done():
            self.enqueue_task.cancel()
        self.enqueue_task = None

    async def save_queue(self) -> None:
        """Persist queue to disk and signal the sensor to refresh."""
        if self.store:
            await self.store.async_save({
                "queue": self.queue,
                "current_index": self.current_index,
                "repeat_mode": self.repeat_mode,
                "queue_dirty": self.queue_dirty,
            })
        if self.hass and self.entry_id:
            from .const import SIGNAL_QUEUE_UPDATED
            async_dispatcher_send(self.hass, f"{SIGNAL_QUEUE_UPDATED}_{self.entry_id}")

    async def load_queue(self) -> None:
        """Restore queue from disk."""
        if not self.store:
            return
        data = await self.store.async_load()
        if data:
            self.queue = data.get("queue", [])
            self.current_index = data.get("current_index", 0)
            self.repeat_mode = data.get("repeat_mode", "off")
            self.queue_dirty = data.get("queue_dirty", False)
            LOGGER.info("Restored queue: %d tracks, index %d", len(self.queue), self.current_index)

    async def clear_queue(self) -> None:
        """Clear the queue and persist."""
        self.cancel_enqueue()
        self.queue = []
        self.current_index = 0
        self.queue_dirty = False
        await self.save_queue()


type NavidromeConfigEntry = ConfigEntry[NavidromeData]

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.SENSOR]


def apply_reorder(
    queue: list[dict[str, Any]],
    current_index: int,
    from_idx: int,
    to_idx: int,
) -> tuple[int, bool]:
    """Reorder queue in-place; return (new_current_index, tail_changed).

    tail_changed is True when at least one reordered track is after current_index,
    meaning the upcoming play sequence has changed.
    """
    if from_idx == to_idx:
        return current_index, False

    track = queue.pop(from_idx)
    queue.insert(to_idx, track)

    if from_idx == current_index:
        new_index = to_idx
    else:
        new_index = current_index
        if from_idx < current_index:
            new_index -= 1
        if to_idx <= new_index:
            new_index += 1

    tail_changed = max(from_idx, to_idx) > new_index
    return new_index, tail_changed


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
    data.hass = hass
    data.entry_id = entry.entry_id

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
    await hass.http.async_register_static_paths(
        [StaticPathConfig(
            url_path="/navidrome/navidrome-search-card.js",
            path=hass.config.path("custom_components/navidrome/www/navidrome-search-card.js"),
            cache_headers=True,
        )]
    )
    from homeassistant.components.frontend import add_extra_js_url
    add_extra_js_url(hass, "/navidrome/navidrome-queue-card.js?v=2")
    add_extra_js_url(hass, "/navidrome/navidrome-search-card.js?v=2")

    # Register clear_queue service
    async def handle_clear_queue(call: ServiceCall) -> None:
        """Handle clear_queue service call."""
        await data.clear_queue()
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

    # Register save_queue_as_playlist service
    async def handle_save_queue_as_playlist(call: ServiceCall) -> None:
        """Save the current queue as a new Navidrome playlist."""
        name = call.data["name"]
        song_ids = [t["id"] for t in data.queue if t.get("id")]
        if not song_ids:
            LOGGER.warning("Cannot save empty queue as playlist")
            return
        await data.client.create_playlist(name, song_ids)
        LOGGER.info("Saved queue as playlist '%s' with %d tracks", name, len(song_ids))

    # Register add_to_playlist service
    async def handle_add_to_playlist(call: ServiceCall) -> None:
        """Add a song to an existing Navidrome playlist."""
        playlist_id = call.data["playlist_id"]
        song_id = call.data["song_id"]
        await data.client.update_playlist(playlist_id, songs_to_add=[song_id])
        LOGGER.info("Added song %s to playlist %s", song_id, playlist_id)

    # Register add_to_queue service
    async def handle_add_to_queue(call: ServiceCall) -> None:
        """Add a song to the current queue without replacing."""
        from homeassistant.components.media_player import async_process_play_media_url
        song_id = call.data["song_id"]
        song = await data.client.get_song(song_id)
        track = {
            "id": song_id,
            "url": data.client.stream_url(song_id),
            "title": song.get("title"),
            "artist": song.get("artist"),
            "album": song.get("album"),
            "duration": song.get("duration"),
            "coverArt": song.get("coverArt"),
        }
        data.queue.append(track)
        await data.save_queue()

        # If background worker is active it will pick up the appended track
        # (worker iterates data.queue as a live reference). Only enqueue
        # directly when no worker is running.
        target = entry.options.get("target_player")
        if target and not (data.enqueue_task and not data.enqueue_task.done()):
            async with data.target_lock:
                await hass.services.async_call(
                    "media_player", "play_media",
                    {
                        "entity_id": target,
                        "media_content_id": async_process_play_media_url(hass, track["url"]),
                        "media_content_type": "audio/mpeg",
                        "enqueue": "add",
                    },
                    blocking=True,
                )
        LOGGER.info("Added '%s' to queue", track.get("title", song_id))

    # Register reorder_queue service
    async def handle_reorder_queue(call: ServiceCall) -> None:
        """Reorder a track in the queue.

        Cancels the background enqueue worker (the tail is now stale) and
        sets queue_dirty so the dirty-advance hook in the state listener
        rebuilds the target's upcoming queue at the next track boundary.
        """
        from_idx = call.data["from_index"]
        to_idx = call.data["to_index"]

        if (
            from_idx < 0 or from_idx >= len(data.queue)
            or to_idx < 0 or to_idx >= len(data.queue)
        ):
            LOGGER.warning(
                "Reorder indices out of range: %d -> %d (queue size %d)",
                from_idx, to_idx, len(data.queue),
            )
            return

        if from_idx == to_idx:
            return

        data.cancel_enqueue()

        new_index, tail_changed = apply_reorder(
            data.queue, data.current_index, from_idx, to_idx
        )
        data.current_index = new_index
        if tail_changed:
            data.queue_dirty = True

        await data.save_queue()
        LOGGER.info(
            "Reordered queue: %d -> %d (dirty=%s)", from_idx, to_idx, data.queue_dirty
        )

    # Register all services
    services = {
        "clear_queue": (handle_clear_queue, vol.Schema({})),
        "save_queue_as_playlist": (handle_save_queue_as_playlist, vol.Schema({
            vol.Required("name"): str,
        })),
        "add_to_playlist": (handle_add_to_playlist, vol.Schema({
            vol.Required("playlist_id"): str,
            vol.Required("song_id"): str,
        })),
        "add_to_queue": (handle_add_to_queue, vol.Schema({
            vol.Required("song_id"): str,
        })),
        "reorder_queue": (handle_reorder_queue, vol.Schema({
            vol.Required("from_index"): int,
            vol.Required("to_index"): int,
        })),
    }
    for name, (handler, schema) in services.items():
        if not hass.services.has_service(DOMAIN, name):
            hass.services.async_register(DOMAIN, name, handler, schema=schema)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: NavidromeConfigEntry
) -> bool:
    """Unload a config entry."""
    entry.runtime_data.cancel_enqueue()
    await entry.runtime_data.save_queue()
    for svc in ("clear_queue", "save_queue_as_playlist", "add_to_playlist", "add_to_queue", "reorder_queue"):
        hass.services.async_remove(DOMAIN, svc)
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
