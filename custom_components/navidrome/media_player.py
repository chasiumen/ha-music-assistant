"""MediaPlayer platform for the Navidrome integration.

This is a lightweight wrapper that enables voice search and play intents.
It delegates actual audio playback to a user-configured target media player.
"""

from __future__ import annotations

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
    async_process_play_media_url,
)
from homeassistant.components.media_player.browse_media import (
    SearchMedia,
    SearchMediaQuery,
)
from homeassistant.const import CONF_URL, STATE_PLAYING, STATE_PAUSED, STATE_IDLE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from . import NavidromeConfigEntry
from .api import NavidromeClient
from .const import CONF_SCROBBLE_ENABLED, CONF_TARGET_PLAYER, DOMAIN, LOGGER

SERVICE_PLAY_MEDIA = "play_media"


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
    _attr_supported_features = (
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
    )
    _attr_state = MediaPlayerState.IDLE
    _attr_media_content_id: str | None = None
    _attr_media_content_type: str | None = None
    _attr_media_title: str | None = None
    _attr_media_artist: str | None = None
    _attr_media_album_name: str | None = None
    _attr_media_image_url: str | None = None
    _attr_media_duration: int | None = None

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

    async def async_added_to_hass(self) -> None:
        """Start tracking target player state."""
        self._setup_state_listener()

    def _setup_state_listener(self) -> None:
        """Set up a state change listener for the target player."""
        if self._unsub_state_listener:
            self._unsub_state_listener()
            self._unsub_state_listener = None

        target = self.target_player
        if not target:
            return

        @callback
        def _handle_target_state_change(event: Event) -> None:
            """Sync state from target player."""
            new_state = event.data.get("new_state")
            if not new_state:
                return
            state = new_state.state
            if state == STATE_PLAYING:
                self._attr_state = MediaPlayerState.PLAYING
            elif state == STATE_PAUSED:
                self._attr_state = MediaPlayerState.PAUSED
            else:
                self._attr_state = MediaPlayerState.IDLE
            self.async_write_ha_state()

        self._unsub_state_listener = async_track_state_change_event(
            self.hass, [target], _handle_target_state_change
        )

    @property
    def client(self) -> NavidromeClient:
        """Return the API client."""
        return self._entry.runtime_data

    @property
    def target_player(self) -> str | None:
        """Return the configured target media player entity ID."""
        return self._entry.options.get(CONF_TARGET_PLAYER)

    @property
    def scrobble_enabled(self) -> bool:
        """Return whether scrobbling is enabled."""
        return self._entry.options.get(CONF_SCROBBLE_ENABLED, False)

    async def _proxy_command(self, service: str, **data: Any) -> None:
        """Forward a media player command to the target player."""
        target = self.target_player
        if not target:
            return
        service_data = {"entity_id": target, **data}
        await self.hass.services.async_call(
            "media_player", service, service_data, blocking=True
        )

    async def async_media_play(self) -> None:
        """Send play command to target player."""
        await self._proxy_command("media_play")
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    async def async_media_pause(self) -> None:
        """Send pause command to target player."""
        await self._proxy_command("media_pause")
        self._attr_state = MediaPlayerState.PAUSED
        self.async_write_ha_state()

    async def async_media_stop(self) -> None:
        """Send stop command to target player."""
        await self._proxy_command("media_stop")
        self._attr_state = MediaPlayerState.IDLE
        self.async_write_ha_state()

    async def async_media_next_track(self) -> None:
        """Send next track command to target player."""
        await self._proxy_command("media_next_track")

    async def async_media_previous_track(self) -> None:
        """Send previous track command to target player."""
        await self._proxy_command("media_previous_track")

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume on target player."""
        await self._proxy_command("volume_set", volume_level=volume)

    async def async_search_media(
        self,
        query: SearchMediaQuery,
    ) -> SearchMedia:
        """Search the Navidrome library."""
        results = await self.client.search3(
            query.search_query,
            song_count=10,
            album_count=5,
            artist_count=5,
        )

        items: list[BrowseMedia] = []

        # Add song results
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

        # Add album results
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

        # Add artist results
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

        return SearchMedia(result=items)

    async def async_play_media(
        self,
        media_type: MediaType | str,
        media_id: str,
        **kwargs: Any,
    ) -> None:
        """Play a media item by forwarding to the target media player."""
        target = self.target_player
        if not target:
            LOGGER.warning(
                "No target media player configured. "
                "Go to the Navidrome integration options to select one."
            )
            return

        # Collect all tracks to play
        tracks = await self._resolve_to_tracks(media_id)

        if not tracks:
            LOGGER.warning("No playable tracks found for %s", media_id)
            return

        # Update entity metadata from the first track
        first = tracks[0]
        self._update_media_attributes(first)

        # Play the first track with metadata
        play_data: dict[str, Any] = {
            "entity_id": target,
            "media_content_id": async_process_play_media_url(
                self.hass, first["url"]
            ),
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
            "media_player",
            SERVICE_PLAY_MEDIA,
            play_data,
            blocking=True,
        )

        # Scrobble "now playing" for the first track
        if self.scrobble_enabled and first.get("id"):
            try:
                await self.client.scrobble(first["id"], submission=False)
            except Exception:
                LOGGER.debug("Failed to scrobble now playing for %s", first["id"])

        # Enqueue remaining tracks
        for track in tracks[1:]:
            await self.hass.services.async_call(
                "media_player",
                SERVICE_PLAY_MEDIA,
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

        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    def _update_media_attributes(self, track: dict[str, Any]) -> None:
        """Update entity media attributes from a track dict."""
        self._attr_media_content_id = track.get("url")
        self._attr_media_content_type = "audio/mpeg"
        self._attr_media_title = track.get("title")
        self._attr_media_artist = track.get("artist")
        self._attr_media_album_name = track.get("album")
        self._attr_media_duration = track.get("duration")
        cover_art = track.get("coverArt")
        self._attr_media_image_url = (
            self.client.cover_art_url(cover_art) if cover_art else None
        )

    async def _resolve_to_tracks(self, media_id: str) -> list[dict[str, Any]]:
        """Resolve a media ID to a list of track dicts.

        Each dict has: id, url, title, artist, album, duration, coverArt
        """
        # Direct stream URL (single song from search results)
        if not media_source.is_media_source_id(media_id):
            song_id = self._extract_song_id_from_url(media_id)
            track: dict[str, Any] = {"id": song_id, "url": media_id}
            # Fetch metadata if we have a song ID
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

        # Parse the media-source URI to get type and ID
        # Format: media-source://navidrome/{type}/{id}
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

        # Unknown type — try single resolve
        play_item = await media_source.async_resolve_media(
            self.hass, media_id, self.entity_id
        )
        return [{"id": None, "url": play_item.url}]

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
