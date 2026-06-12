"""MediaPlayer platform for the Navidrome integration.

This is a lightweight wrapper that enables voice search and play intents.
It delegates actual audio playback to a user-configured target media player.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    RepeatMode,
    async_process_play_media_url,
)
from homeassistant.components.media_player.browse_media import (
    SearchMedia,
    SearchMediaQuery,
)
from homeassistant.const import CONF_URL, STATE_PAUSED, STATE_PLAYING
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from . import NavidromeConfigEntry, NavidromeData
from .api import NavidromeClient
from .const import (
    CONF_SCROBBLE_ENABLED,
    CONF_TARGET_PLAYER,
    DOMAIN,
    LOGGER,
    PLAYLIST_CACHE_TTL_SECONDS,
    TARGET_STATE_GRACE_SECONDS,
)

SERVICE_PLAY_MEDIA = "play_media"

_BASE_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.SEARCH_MEDIA
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.MEDIA_ENQUEUE
    | MediaPlayerEntityFeature.REPEAT_SET
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NavidromeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Navidrome media player."""
    async_add_entities([NavidromeMediaPlayer(entry)])


class NavidromeMediaPlayer(MediaPlayerEntity):
    """A Navidrome media player for voice search and play.

    This entity provides SEARCH_MEDIA and PLAY_MEDIA features so that
    HA voice intents (HassMediaSearchAndPlay) can search the Navidrome
    library and play results on a configured target media player.
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_state = MediaPlayerState.IDLE
    _attr_media_content_id: str | None = None
    _attr_media_content_type: str | None = None
    _attr_media_title: str | None = None
    _attr_media_artist: str | None = None
    _attr_media_album_name: str | None = None
    _attr_media_duration: int | None = None
    _attr_repeat: RepeatMode = RepeatMode.OFF
    _cover_art_url: str | None = None

    def __init__(self, entry: NavidromeConfigEntry) -> None:
        """Initialize the media player."""
        self._entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="Navidrome",
            model="Music Server",
            name=entry.title,
            configuration_url=entry.data.get(CONF_URL),
        )
        self._unsub_state_listener: callback | None = None
        self._optimistic_deadline: float = 0.0
        self._repeat_grace_deadline: float = 0.0
        self._playlist_cache: list[dict[str, Any]] | None = None
        self._playlist_cache_time: float = 0.0

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Return supported media player features."""
        return _BASE_FEATURES

    async def async_added_to_hass(self) -> None:
        """Start tracking target player state."""
        if self.data.repeat_mode and self.data.repeat_mode != "off":
            try:
                self._attr_repeat = RepeatMode(self.data.repeat_mode)
            except ValueError:
                pass
        self._setup_state_listener()

    async def async_will_remove_from_hass(self) -> None:
        """Cancel background tasks on unload."""
        self.data.cancel_enqueue()
        if self._unsub_state_listener:
            self._unsub_state_listener()
            self._unsub_state_listener = None

    def _setup_state_listener(self) -> None:
        """Set up a state change listener for the target player."""
        if self._unsub_state_listener:
            self._unsub_state_listener()
            self._unsub_state_listener = None

        target = self.target_player
        if not target:
            return

        self._unsub_state_listener = async_track_state_change_event(
            self.hass, [target], self._async_target_state_changed
        )

    @callback
    def _async_target_state_changed(self, event: Event) -> None:
        """Sync state and media metadata from the target player."""
        new_state = event.data.get("new_state")
        if not new_state:
            return

        state_str = new_state.state
        if state_str in (STATE_PLAYING, "buffering"):
            incoming = MediaPlayerState.PLAYING
        elif state_str == STATE_PAUSED:
            incoming = MediaPlayerState.PAUSED
        else:
            incoming = MediaPlayerState.IDLE

        now = time.monotonic()
        within_grace = now < self._optimistic_deadline

        if within_grace:
            if incoming == self._attr_state:
                self._optimistic_deadline = 0.0  # confirming — clear grace
            # contradicting — keep optimistic state; fall through to metadata sync
        else:
            self._attr_state = incoming

        # Sync media metadata regardless of grace window
        attrs = new_state.attributes
        target_title = attrs.get("media_title")
        target_artist = attrs.get("media_artist")

        if target_title:
            self._attr_media_title = target_title
            self._attr_media_artist = target_artist
            self._attr_media_duration = attrs.get("media_duration")
            self._attr_media_album_name = attrs.get("media_album_name")
            self._sync_queue_index(target_title, target_artist)

        # Sync repeat from target outside repeat grace window
        if now >= self._repeat_grace_deadline:
            target_repeat = attrs.get("repeat")
            if target_repeat is not None:
                try:
                    repeat_mode = RepeatMode(target_repeat)
                    if repeat_mode != self._attr_repeat:
                        self._attr_repeat = repeat_mode
                        self.data.repeat_mode = target_repeat
                except ValueError:
                    pass

        self.async_write_ha_state()

    def _set_optimistic_state(self, state: MediaPlayerState) -> None:
        """Set an optimistic state with a grace window to protect against stale target events."""
        self._attr_state = state
        self._optimistic_deadline = time.monotonic() + TARGET_STATE_GRACE_SECONDS
        self.async_write_ha_state()

    @property
    def data(self) -> NavidromeData:
        """Return the shared data."""
        return self._entry.runtime_data

    @property
    def client(self) -> NavidromeClient:
        """Return the API client."""
        return self.data.client

    @property
    def target_player(self) -> str | None:
        """Return the configured target media player entity ID."""
        return self._entry.options.get(CONF_TARGET_PLAYER)

    @property
    def scrobble_enabled(self) -> bool:
        """Return whether scrobbling is enabled."""
        return self._entry.options.get(CONF_SCROBBLE_ENABLED, False)

    async def _proxy_command(self, service: str, **kwargs: Any) -> None:
        """Forward a media player command to the target player (lock-protected)."""
        target = self.target_player
        if not target:
            return
        service_data = {"entity_id": target, **kwargs}
        async with self.data.target_lock:
            await self.hass.services.async_call(
                "media_player", service, service_data, blocking=True
            )

    async def async_media_play(self) -> None:
        """Send play command to target player."""
        self._set_optimistic_state(MediaPlayerState.PLAYING)
        await self._proxy_command("media_play")

    async def async_media_pause(self) -> None:
        """Send pause command to target player."""
        self._set_optimistic_state(MediaPlayerState.PAUSED)
        await self._proxy_command("media_pause")

    async def async_media_stop(self) -> None:
        """Send stop command to target player."""
        self._set_optimistic_state(MediaPlayerState.IDLE)
        await self._proxy_command("media_stop")

    async def async_media_next_track(self) -> None:
        """Send next track command to target player."""
        await self._proxy_command("media_next_track")

    async def async_media_previous_track(self) -> None:
        """Send previous track command to target player."""
        await self._proxy_command("media_previous_track")

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume on target player."""
        await self._proxy_command("volume_set", volume_level=volume)

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        """Set repeat mode, persist it, and proxy to target."""
        self._attr_repeat = repeat
        self._repeat_grace_deadline = time.monotonic() + TARGET_STATE_GRACE_SECONDS
        self.async_write_ha_state()
        self.data.repeat_mode = repeat.value
        self.hass.async_create_task(self.data.save_queue())
        await self._async_apply_repeat_to_target()

    async def _async_apply_repeat_to_target(self) -> None:
        """Re-assert the persisted repeat mode on the target after a queue rebuild."""
        target = self.target_player
        if not target or self.data.repeat_mode == "off":
            return
        try:
            await self.hass.services.async_call(
                "media_player", "repeat_set",
                {"entity_id": target, "repeat": self.data.repeat_mode},
                blocking=True,
            )
        except Exception as err:
            LOGGER.debug("Failed to re-assert repeat mode on target: %s", err)

    async def async_search_media(
        self,
        query: SearchMediaQuery,
    ) -> SearchMedia:
        """Search the Navidrome library (songs, albums, artists, playlists)."""
        results = await self.client.search3(
            query.search_query,
            song_count=500,
            album_count=500,
            artist_count=500,
        )

        items: list[BrowseMedia] = []

        for song in results.get("song", []):
            title = song.get("title", "Unknown")
            artist = song.get("artist", "")
            display = f"{artist} - {title}" if artist else title
            items.append(
                BrowseMedia(
                    media_class=MediaClass.TRACK,
                    media_content_id=self.client.stream_url(song["id"]),
                    media_content_type=MediaType.MUSIC,
                    title=display,
                    can_play=True,
                    can_expand=False,
                    thumbnail=self.client.cover_art_url(song["coverArt"])
                    if song.get("coverArt")
                    else None,
                )
            )

        for album in results.get("album", []):
            name = album.get("name", "Unknown Album")
            artist = album.get("artist", "")
            display = f"{name} - {artist}" if artist else name
            items.append(
                BrowseMedia(
                    media_class=MediaClass.ALBUM,
                    media_content_id=f"media-source://navidrome/album/{album['id']}",
                    media_content_type=MediaType.MUSIC,
                    title=display,
                    can_play=True,
                    can_expand=True,
                    thumbnail=self.client.cover_art_url(album["coverArt"])
                    if album.get("coverArt")
                    else None,
                )
            )

        for artist in results.get("artist", []):
            items.append(
                BrowseMedia(
                    media_class=MediaClass.ARTIST,
                    media_content_id=f"media-source://navidrome/artist/{artist['id']}",
                    media_content_type=MediaType.MUSIC,
                    title=artist.get("name", "Unknown Artist"),
                    can_play=False,
                    can_expand=True,
                    thumbnail=self.client.cover_art_url(artist["coverArt"])
                    if artist.get("coverArt")
                    else None,
                )
            )

        # Playlist search: filter by substring on cached playlist list.
        # The WS handler passes media_filter_classes=[] (not None) when the
        # caller doesn't filter, so treat any empty value as "no filter".
        filter_classes = getattr(query, "media_filter_classes", None)
        include_playlists = not filter_classes or MediaClass.PLAYLIST in filter_classes
        if include_playlists:
            now = time.monotonic()
            if (
                self._playlist_cache is None
                or now - self._playlist_cache_time > PLAYLIST_CACHE_TTL_SECONDS
            ):
                try:
                    self._playlist_cache = await self.client.get_playlists()
                    self._playlist_cache_time = now
                except Exception as err:
                    LOGGER.debug("Failed to fetch playlists for search: %s", err)
                    if self._playlist_cache is None:
                        self._playlist_cache = []

            query_lower = query.search_query.lower()
            for playlist in self._playlist_cache:
                if query_lower in playlist.get("name", "").lower():
                    items.append(
                        BrowseMedia(
                            media_class=MediaClass.PLAYLIST,
                            media_content_id=f"media-source://navidrome/playlist/{playlist['id']}",
                            media_content_type=MediaType.MUSIC,
                            title=playlist.get("name", "Unknown Playlist"),
                            can_play=True,
                            can_expand=True,
                            thumbnail=self.client.cover_art_url(playlist["coverArt"])
                            if playlist.get("coverArt")
                            else None,
                        )
                    )

        return SearchMedia(result=items)

    async def async_play_media(
        self,
        media_type: MediaType | str,
        media_id: str,
        **kwargs: Any,
    ) -> None:
        """Play a media item by forwarding to the target media player."""
        LOGGER.info("async_play_media called: type=%s, id=%s", media_type, media_id)
        target = self.target_player
        if not target:
            LOGGER.warning(
                "No target media player configured. "
                "Go to the Navidrome integration options to select one."
            )
            return

        # Song already in queue — jump to it
        queue_index = self._find_in_queue(media_id)
        if queue_index is not None:
            LOGGER.info("Song found in queue at index %d, jumping", queue_index)
            await self._play_from_queue_index(target, queue_index)
            return

        tracks = await self._resolve_to_tracks(media_id)
        if not tracks:
            LOGGER.warning("No playable tracks found for %s", media_id)
            return

        LOGGER.info(
            "Playing %d tracks on %s, first: %s",
            len(tracks), target, tracks[0].get("title", "unknown"),
        )

        # Cancel any in-flight background enqueue before rebuilding the queue
        self.data.cancel_enqueue()

        try:
            await self.hass.services.async_call(
                "media_player", "media_stop", {"entity_id": target}, blocking=True,
            )
        except Exception:
            pass

        try:
            await self.hass.services.async_call(
                "media_player", "clear_playlist", {"entity_id": target}, blocking=True,
            )
        except Exception:
            pass

        self.data.queue = tracks
        self.data.current_index = 0
        self.data.queue_dirty = False
        self.hass.async_create_task(self.data.save_queue())

        first = tracks[0]
        self._update_media_attributes(first)

        play_data: dict[str, Any] = {
            "entity_id": target,
            "media_content_id": async_process_play_media_url(self.hass, first["url"]),
            "media_content_type": "audio/mpeg",
        }
        if first.get("title") or first.get("coverArt"):
            play_data["extra"] = {
                "title": first.get("title"),
                "artist": first.get("artist"),
                "album": first.get("album"),
                "thumb": self.client.cover_art_url(first["coverArt"])
                if first.get("coverArt")
                else None,
            }
        await self.hass.services.async_call(
            "media_player", SERVICE_PLAY_MEDIA, play_data, blocking=True,
        )

        if self.scrobble_enabled and first.get("id"):
            try:
                await self.client.scrobble(first["id"], submission=False)
                LOGGER.info("Scrobble sent for %s", first.get("title", first["id"]))
            except Exception as err:
                LOGGER.error("Failed to scrobble for %s: %s", first["id"], err)

        # Enqueue remaining tracks in the background
        if len(tracks) > 1:
            self.data.enqueue_task = self.hass.async_create_task(
                self._enqueue_worker(target, 1)
            )

        self._set_optimistic_state(MediaPlayerState.PLAYING)
        LOGGER.info("Playing %s tracks on %s (tail enqueuing in background)", len(tracks), target)

        await self._async_apply_repeat_to_target()

    @property
    def entity_picture(self) -> str | None:
        """Return cover art via our local proxy to avoid SSL issues."""
        return self._cover_art_url

    def _update_media_attributes(self, track: dict[str, Any]) -> None:
        """Update entity media attributes from a track dict."""
        self._attr_media_content_id = track.get("url")
        self._attr_media_content_type = "audio/mpeg"
        self._attr_media_title = track.get("title")
        self._attr_media_artist = track.get("artist")
        self._attr_media_album_name = track.get("album")
        self._attr_media_duration = track.get("duration")
        cover_art = track.get("coverArt")
        self._cover_art_url = (
            f"/api/navidrome/cover_art/{cover_art}" if cover_art else None
        )

    async def _enqueue_worker(self, target: str, start_index: int) -> None:
        """Background task: enqueue data.queue[start_index:] on the target player.

        Iterates the live queue list so tracks added by handle_add_to_queue are
        automatically picked up. CancelledError propagates to stop the task.
        """
        i = start_index
        while i < len(self.data.queue):
            track = self.data.queue[i]
            try:
                async with self.data.target_lock:
                    await self.hass.services.async_call(
                        "media_player", SERVICE_PLAY_MEDIA,
                        {
                            "entity_id": target,
                            "media_content_id": async_process_play_media_url(
                                self.hass, track["url"]
                            ),
                            "media_content_type": "audio/mpeg",
                            "enqueue": "add",
                        },
                        blocking=True,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as err:
                LOGGER.warning(
                    "Failed to enqueue track %d (%s): %s", i, track.get("title"), err
                )
            i += 1
        LOGGER.info("Enqueue worker finished: %d tracks from index %d", i - start_index, start_index)

    async def _resolve_to_tracks(self, media_id: str) -> list[dict[str, Any]]:
        """Resolve a media ID to a list of track dicts.

        Each dict has: id, url, title, artist, album, duration, coverArt
        """
        if not media_source.is_media_source_id(media_id):
            song_id = self._extract_song_id_from_url(media_id)
            track: dict[str, Any] = {"id": song_id, "url": media_id}
            if song_id:
                try:
                    song = await self.client.get_song(song_id)
                    track.update({
                        "title": song.get("title"),
                        "artist": song.get("artist"),
                        "album": song.get("album"),
                        "duration": song.get("duration"),
                        "coverArt": song.get("coverArt"),
                    })
                except Exception:
                    LOGGER.debug("Failed to fetch metadata for %s", song_id)
            return [track]

        uri = media_id.replace("media-source://navidrome/", "")
        parts = uri.split("/", 1)
        if len(parts) != 2:
            play_item = await media_source.async_resolve_media(
                self.hass, media_id, self.entity_id
            )
            return [{"id": None, "url": play_item.url}]

        item_type, item_id = parts

        if item_type == "song":
            track = {"id": item_id, "url": self.client.stream_url(item_id)}
            try:
                song = await self.client.get_song(item_id)
                track.update({
                    "title": song.get("title"),
                    "artist": song.get("artist"),
                    "album": song.get("album"),
                    "duration": song.get("duration"),
                    "coverArt": song.get("coverArt"),
                })
            except Exception:
                LOGGER.debug("Failed to fetch metadata for %s", item_id)
            return [track]

        if item_type == "album":
            album = await self.client.get_album(item_id)
            songs = album.get("song", [])
            songs.sort(key=lambda s: (s.get("discNumber", 0), s.get("track", 0)))
            return [self._song_to_track(s) for s in songs]

        if item_type == "playlist":
            playlist = await self.client.get_playlist(item_id)
            entries = playlist.get("entry", [])
            return [self._song_to_track(e) for e in entries]

        play_item = await media_source.async_resolve_media(
            self.hass, media_id, self.entity_id
        )
        return [{"id": None, "url": play_item.url}]

    def _find_in_queue(self, media_id: str) -> int | None:
        """Return the queue index if media_id matches a song, else None."""
        if not self.data.queue:
            return None

        song_id = None
        if media_id.startswith("media-source://navidrome/song/"):
            song_id = media_id.replace("media-source://navidrome/song/", "")
        else:
            song_id = self._extract_song_id_from_url(media_id)

        if not song_id:
            return None

        for i, track in enumerate(self.data.queue):
            if track.get("id") == song_id:
                return i
        return None

    async def _play_from_queue_index(self, target: str, index: int) -> None:
        """Play from a specific position in the existing queue."""
        tracks = self.data.queue
        if index < 0 or index >= len(tracks):
            return

        self.data.cancel_enqueue()
        self.data.current_index = index
        self.data.queue_dirty = False
        self.hass.async_create_task(self.data.save_queue())

        first = tracks[index]
        self._update_media_attributes(first)

        try:
            await self.hass.services.async_call(
                "media_player", "media_stop", {"entity_id": target}, blocking=True,
            )
        except Exception:
            pass

        try:
            await self.hass.services.async_call(
                "media_player", "clear_playlist", {"entity_id": target}, blocking=True,
            )
        except Exception:
            pass

        await self.hass.services.async_call(
            "media_player", SERVICE_PLAY_MEDIA,
            {
                "entity_id": target,
                "media_content_id": async_process_play_media_url(self.hass, first["url"]),
                "media_content_type": "audio/mpeg",
            },
            blocking=True,
        )

        if self.scrobble_enabled and first.get("id"):
            try:
                await self.client.scrobble(first["id"], submission=False)
                LOGGER.info("Scrobble sent for %s", first.get("title", first["id"]))
            except Exception as err:
                LOGGER.error("Failed to scrobble for %s: %s", first["id"], err)

        if len(tracks) - index - 1 > 0:
            self.data.enqueue_task = self.hass.async_create_task(
                self._enqueue_worker(target, index + 1)
            )

        self._set_optimistic_state(MediaPlayerState.PLAYING)
        LOGGER.info("Playing from queue index %d, %d remaining tracks", index, len(tracks) - index - 1)

        await self._async_apply_repeat_to_target()

    def _sync_queue_index(self, title: str, artist: str | None) -> None:
        """Update queue current_index based on the currently playing track.

        When queue_dirty, also schedules a tail-rebuild at the track boundary
        so a pending reorder takes effect without interrupting the current track.
        """
        LOGGER.info("Sync queue: title=%s, artist=%s", title, artist)
        found = False
        for i, track in enumerate(self.data.queue):
            if track.get("title") == title and (
                not artist or track.get("artist") == artist
            ):
                if i != self.data.current_index:
                    LOGGER.info("Queue advanced to index %d: %s", i, title)
                    self.data.current_index = i
                    self.hass.async_create_task(self.data.save_queue())
                    cover_art = track.get("coverArt")
                    self._cover_art_url = (
                        f"/api/navidrome/cover_art/{cover_art}" if cover_art else None
                    )
                    if self.scrobble_enabled and track.get("id"):
                        self.hass.async_create_task(
                            self._scrobble_track(track["id"])
                        )

                    # Dirty-advance: if we reordered while music was playing,
                    # rebuild the target's tail now that the track boundary arrived.
                    if self.data.queue_dirty:
                        self.data.queue_dirty = False
                        target = self.target_player
                        if target:
                            self.hass.async_create_task(
                                self._play_from_queue_index(target, i)
                            )
                found = True
                break

        if not found and title:
            LOGGER.info("Track '%s' not found in queue, searching Navidrome", title)
            if self.scrobble_enabled:
                self.hass.async_create_task(
                    self._search_and_scrobble(title, artist)
                )

    async def _search_and_scrobble(self, title: str, artist: str | None) -> None:
        """Search for a track by title and scrobble it."""
        try:
            query = f"{artist} {title}" if artist else title
            results = await self.client.search3(query, song_count=1, album_count=0, artist_count=0)
            songs = results.get("song", [])
            if songs:
                song_id = songs[0]["id"]
                await self.client.scrobble(song_id, submission=False)
                LOGGER.info("Scrobble sent (via search) for %s - %s", artist, title)
            else:
                LOGGER.info("Could not find track to scrobble: %s - %s", artist, title)
        except Exception as err:
            LOGGER.error("Failed to search and scrobble: %s", err)

    async def _scrobble_track(self, song_id: str) -> None:
        """Send scrobble for a track."""
        try:
            await self.client.scrobble(song_id, submission=False)
            LOGGER.info("Scrobble sent for song_id=%s", song_id)
        except Exception as err:
            LOGGER.error("Failed to scrobble for %s: %s", song_id, err)

    def _song_to_track(self, song: dict[str, Any]) -> dict[str, Any]:
        """Convert a Subsonic song/entry dict to a track dict."""
        return {
            "id": song["id"],
            "url": self.client.stream_url(song["id"]),
            "title": song.get("title"),
            "artist": song.get("artist"),
            "album": song.get("album"),
            "duration": song.get("duration"),
            "coverArt": song.get("coverArt"),
        }

    @staticmethod
    def _extract_song_id_from_url(url: str) -> str | None:
        """Extract the song ID from a Navidrome stream URL."""
        from urllib.parse import parse_qs, urlparse

        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            ids = params.get("id", [])
            return ids[0] if ids else None
        except Exception:
            return None

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Return a BrowseMedia for the Navidrome library."""
        from homeassistant.components.media_source import (
            async_browse_media as ms_browse,
        )

        if media_content_id:
            if media_content_id.startswith("media-source://"):
                uri = media_content_id
            else:
                uri = f"media-source://navidrome/{media_content_id}"
        else:
            uri = "media-source://navidrome"

        return await ms_browse(self.hass, uri)
