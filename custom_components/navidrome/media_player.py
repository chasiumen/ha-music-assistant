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
    MediaPlayerEnqueue,
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
from homeassistant.const import STATE_PAUSED, STATE_PLAYING
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_state_change_event

from . import NavidromeConfigEntry, NavidromeData
from .api import NavidromeClient
from .const import (
    CONF_CONTROL_GRACE_SECONDS,
    CONF_PLAYLIST_CACHE_TTL,
    CONF_SCROBBLE_ENABLED,
    CONF_SEARCH_RESULT_LIMIT,
    CONF_TARGET_PLAYER,
    COVER_ART_PROXY_PATH,
    DEFAULT_CONTROL_GRACE_SECONDS,
    DEFAULT_MIME_TYPE,
    DEFAULT_PLAYLIST_CACHE_TTL,
    DEFAULT_SCROBBLE_ENABLED,
    DEFAULT_SEARCH_RESULT_LIMIT,
    LOGGER,
    MEDIA_SOURCE_PREFIX,
    PREFIX_ALBUM,
    PREFIX_ARTIST,
    PREFIX_PLAYLIST,
    PREFIX_SONG,
    SIGNAL_PLAY_QUEUE_INDEX,
)
from .entity import navidrome_device_info

SERVICE_PLAY_MEDIA = "play_media"


def _media_id(item_type: str, item_id: str) -> str:
    """Build a media-source://navidrome/<type>/<id> content ID."""
    return f"{MEDIA_SOURCE_PREFIX}/{item_type}/{item_id}"


def _cover_art_proxy_url(cover_art: str | None) -> str | None:
    """Return the local cover-art proxy URL for a coverArt ID, if any."""
    return f"{COVER_ART_PROXY_PATH}/{cover_art}" if cover_art else None

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
        self._attr_device_info = navidrome_device_info(entry)
        self._unsub_state_listener: callback | None = None
        self._optimistic_deadline: float = 0.0
        self._repeat_grace_deadline: float = 0.0
        self._playlist_cache: list[dict[str, Any]] | None = None
        self._playlist_cache_time: float = 0.0
        # Set when the target was stopped because its current track was
        # removed from the queue: the next Play restarts the target from the
        # queue position instead of resuming the (removed) track.
        self._restart_queue_on_play = False

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
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_PLAY_QUEUE_INDEX}_{self._entry.entry_id}",
                self._async_play_queue_index,
            )
        )

    async def _async_play_queue_index(self, index: int) -> None:
        """Move playback after the current track was removed from the queue.

        While playing, continue with the track at ``index``. When paused or
        stopped, or nothing is left after the removed track, stop the target
        (so the removed track can't resume) and let the next Play start the
        queue from the current position.
        """
        target = self.target_player
        if not target:
            return
        if index < len(self.data.queue) and self.state == MediaPlayerState.PLAYING:
            await self._play_from_queue_index(target, index)
            return
        await self._async_stop_and_restart_on_play()

    async def _async_stop_and_restart_on_play(self) -> None:
        """Stop the target; the next Play restarts from the queue position."""
        self.data.cancel_enqueue()
        self._set_optimistic_state(MediaPlayerState.IDLE)
        await self._proxy_command("media_stop")
        self._restart_queue_on_play = bool(self.data.queue)

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
        self._optimistic_deadline = time.monotonic() + self.control_grace_seconds
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
        return self._entry.options.get(CONF_SCROBBLE_ENABLED, DEFAULT_SCROBBLE_ENABLED)

    # Tunables: an option set in Configure overrides the const.py default.
    # Options are read on every use, so changes apply without a reload.

    @property
    def search_result_limit(self) -> int:
        """Return the max songs/albums/artists fetched per search."""
        return int(
            self._entry.options.get(CONF_SEARCH_RESULT_LIMIT, DEFAULT_SEARCH_RESULT_LIMIT)
        )

    @property
    def playlist_cache_ttl(self) -> float:
        """Return how long (s) the playlist list for search is cached."""
        return float(
            self._entry.options.get(CONF_PLAYLIST_CACHE_TTL, DEFAULT_PLAYLIST_CACHE_TTL)
        )

    @property
    def control_grace_seconds(self) -> float:
        """Return the optimistic-state grace window (s) after a control action."""
        return float(
            self._entry.options.get(
                CONF_CONTROL_GRACE_SECONDS, DEFAULT_CONTROL_GRACE_SECONDS
            )
        )

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
        target = self.target_player
        if self._restart_queue_on_play and target and self.data.queue:
            await self._play_from_queue_index(target, self.data.current_index)
            return
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
        self._repeat_grace_deadline = time.monotonic() + self.control_grace_seconds
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
        limit = self.search_result_limit
        results = await self.client.search3(
            query.search_query,
            song_count=limit,
            album_count=limit,
            artist_count=limit,
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
                    media_content_id=_media_id(PREFIX_ALBUM, album["id"]),
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
                    media_content_id=_media_id(PREFIX_ARTIST, artist["id"]),
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
                or now - self._playlist_cache_time >= self.playlist_cache_ttl
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
                            media_content_id=_media_id(PREFIX_PLAYLIST, playlist["id"]),
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

        # enqueue=add appends to the existing queue without interrupting
        # playback. With an empty queue there is nothing to append to, so
        # fall through and play normally.
        if kwargs.get("enqueue") == MediaPlayerEnqueue.ADD and self.data.queue:
            await self._async_append_to_queue(target, media_id)
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
        self._restart_queue_on_play = False

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
            "media_content_type": DEFAULT_MIME_TYPE,
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

    async def _async_append_to_queue(self, target: str, media_id: str) -> None:
        """Append a song, album or playlist to the end of the queue.

        Playback is not interrupted. The new tracks reach the target via the
        background enqueue worker:
        - worker already running: it iterates the live queue and picks them up;
        - reorder pending (queue_dirty): the tail rebuild at the next track
          boundary re-enqueues everything after the current track, including
          the new tracks, so enqueueing now would only duplicate them;
        - otherwise: start a worker from the first appended track.
        """
        tracks = await self._resolve_to_tracks(media_id)
        if not tracks:
            LOGGER.warning("No playable tracks found for %s", media_id)
            return

        start_index = len(self.data.queue)
        self.data.queue.extend(tracks)
        self.hass.async_create_task(self.data.save_queue())

        worker_running = (
            self.data.enqueue_task is not None and not self.data.enqueue_task.done()
        )
        if not worker_running and not self.data.queue_dirty:
            self.data.enqueue_task = self.hass.async_create_task(
                self._enqueue_worker(target, start_index)
            )

        LOGGER.info(
            "Appended %d tracks from %s to queue (now %d tracks)",
            len(tracks), media_id, len(self.data.queue),
        )

    @property
    def entity_picture(self) -> str | None:
        """Return cover art via our local proxy to avoid SSL issues."""
        return self._cover_art_url

    def _update_media_attributes(self, track: dict[str, Any]) -> None:
        """Update entity media attributes from a track dict."""
        self._attr_media_content_id = track.get("url")
        self._attr_media_content_type = DEFAULT_MIME_TYPE
        self._attr_media_title = track.get("title")
        self._attr_media_artist = track.get("artist")
        self._attr_media_album_name = track.get("album")
        self._attr_media_duration = track.get("duration")
        self._cover_art_url = _cover_art_proxy_url(track.get("coverArt"))

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
                            "media_content_type": DEFAULT_MIME_TYPE,
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

        uri = media_id.replace(f"{MEDIA_SOURCE_PREFIX}/", "")
        parts = uri.split("/", 1)
        if len(parts) != 2:
            play_item = await media_source.async_resolve_media(
                self.hass, media_id, self.entity_id
            )
            return [{"id": None, "url": play_item.url}]

        item_type, item_id = parts

        if item_type == PREFIX_SONG:
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

        if item_type == PREFIX_ALBUM:
            album = await self.client.get_album(item_id)
            songs = album.get("song", [])
            songs.sort(key=lambda s: (s.get("discNumber", 0), s.get("track", 0)))
            return [self._song_to_track(s) for s in songs]

        if item_type == PREFIX_PLAYLIST:
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

        song_prefix = _media_id(PREFIX_SONG, "")
        if media_id.startswith(song_prefix):
            song_id = media_id.removeprefix(song_prefix)
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
        self._restart_queue_on_play = False
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
                "media_content_type": DEFAULT_MIME_TYPE,
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
                    self._cover_art_url = _cover_art_proxy_url(track.get("coverArt"))
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

        if not found and title and self.data.queue_dirty and self.data.queue:
            # The target started a track that's no longer in the queue: it was
            # removed after being enqueued on the target (e.g. it was the very
            # next track). Skip to the track that should follow the current one
            # and rebuild the tail there.
            self.data.queue_dirty = False
            next_index = self.data.current_index + 1
            target = self.target_player
            LOGGER.info(
                "Target started removed track '%s'; skipping to queue index %d",
                title, next_index,
            )
            if target:
                if next_index < len(self.data.queue):
                    self.hass.async_create_task(
                        self._play_from_queue_index(target, next_index)
                    )
                else:
                    self.hass.async_create_task(self._async_stop_and_restart_on_play())
            return

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
            if media_source.is_media_source_id(media_content_id):
                uri = media_content_id
            else:
                uri = f"{MEDIA_SOURCE_PREFIX}/{media_content_id}"
        else:
            uri = MEDIA_SOURCE_PREFIX

        return await ms_browse(self.hass, uri)
