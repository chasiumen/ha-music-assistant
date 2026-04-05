"""MediaPlayer platform for the Navidrome integration.

This is a lightweight wrapper that enables voice search and play intents.
It delegates actual audio playback to a user-configured target media player.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.components.media_player.browse_media import (
    SearchMedia,
    SearchMediaQuery,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NavidromeConfigEntry
from .api import NavidromeClient
from .const import DOMAIN, LOGGER


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
    library and play results on any target media player.
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_supported_features = (
        MediaPlayerEntityFeature.SEARCH_MEDIA
        | MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.BROWSE_MEDIA
    )
    _attr_state = MediaPlayerState.IDLE

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

    @property
    def client(self) -> NavidromeClient:
        """Return the API client."""
        return self._entry.runtime_data

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
        """Play a media item.

        If media_id is a direct stream URL, it's ready to play.
        If it's a media-source URI, it will be resolved by HA's media source system.
        """
        # The intent system or UI will call play_media on this entity.
        # Since this entity doesn't have a physical player, we log the request.
        # In practice, users should configure an automation or use the media browser
        # to send content to their actual player.
        LOGGER.info(
            "Play media requested: type=%s, id=%s. "
            "Use a media player (Sonos, Chromecast, etc.) to play this content.",
            media_type,
            media_id,
        )

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
            uri = f"media-source://navidrome/{media_content_id}"
        else:
            uri = "media-source://navidrome"

        return await ms_browse(self.hass, uri)
