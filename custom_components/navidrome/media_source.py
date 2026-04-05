"""The Media Source implementation for the Navidrome integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import BrowseError, MediaClass, MediaType
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
)
from homeassistant.core import HomeAssistant

from . import NavidromeConfigEntry
from .api import NavidromeClient
from .const import DOMAIN, LOGGER

# Browse tree category identifiers
CAT_ARTISTS = "artists"
CAT_ALBUMS = "albums"
CAT_PLAYLISTS = "playlists"
CAT_GENRES = "genres"
CAT_RECENT = "recent"
CAT_MOST_PLAYED = "most_played"
CAT_RANDOM = "random"

# Item type prefixes for content IDs
PREFIX_ARTIST = "artist"
PREFIX_ALBUM = "album"
PREFIX_SONG = "song"
PREFIX_PLAYLIST = "playlist"
PREFIX_GENRE = "genre"


async def async_get_media_source(hass: HomeAssistant) -> MediaSource:
    """Set up Navidrome media source."""
    entry: NavidromeConfigEntry = hass.config_entries.async_entries(DOMAIN)[0]
    return NavidromeSource(hass, entry)


class NavidromeSource(MediaSource):
    """Represents a Navidrome music server."""

    name: str = "Navidrome"

    def __init__(self, hass: HomeAssistant, entry: NavidromeConfigEntry) -> None:
        """Initialize the Navidrome media source."""
        super().__init__(DOMAIN)
        self.hass = hass
        self.entry = entry

    @property
    def client(self) -> NavidromeClient:
        """Return the API client."""
        return self.entry.runtime_data

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """Resolve a media item to a playable URL."""
        identifier = item.identifier
        if not identifier:
            raise BrowseError("No identifier provided")

        item_type, item_id = _parse_identifier(identifier)

        if item_type == PREFIX_SONG:
            url = self.client.stream_url(item_id)
            return PlayMedia(url, "audio/mpeg")

        if item_type == PREFIX_ALBUM:
            album = await self.client.get_album(item_id)
            songs = album.get("song", [])
            if not songs:
                raise BrowseError("Album has no songs")
            url = self.client.stream_url(songs[0]["id"])
            return PlayMedia(url, "audio/mpeg")

        if item_type == PREFIX_PLAYLIST:
            playlist = await self.client.get_playlist(item_id)
            entries = playlist.get("entry", [])
            if not entries:
                raise BrowseError("Playlist is empty")
            url = self.client.stream_url(entries[0]["id"])
            return PlayMedia(url, "audio/mpeg")

        raise BrowseError(f"Cannot play item type: {item_type}")

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        """Return a browsable Navidrome media source."""
        identifier = item.identifier

        if not identifier:
            return self._build_root()

        # Category pages
        if identifier == CAT_ARTISTS:
            return await self._build_artists()
        if identifier == CAT_ALBUMS:
            return await self._build_album_list("alphabeticalByName", "Albums")
        if identifier == CAT_PLAYLISTS:
            return await self._build_playlists()
        if identifier == CAT_GENRES:
            return await self._build_genres()
        if identifier == CAT_RECENT:
            return await self._build_album_list("newest", "Recently Added")
        if identifier == CAT_MOST_PLAYED:
            return await self._build_album_list("frequent", "Most Played")
        if identifier == CAT_RANDOM:
            return await self._build_album_list("random", "Random")

        # Drill-down items
        item_type, item_id = _parse_identifier(identifier)

        if item_type == PREFIX_ARTIST:
            return await self._build_artist_detail(item_id)
        if item_type == PREFIX_ALBUM:
            return await self._build_album_detail(item_id)
        if item_type == PREFIX_PLAYLIST:
            return await self._build_playlist_detail(item_id)
        if item_type == PREFIX_GENRE:
            return await self._build_genre_albums(item_id)

        raise BrowseError(f"Unknown identifier: {identifier}")

    # -- Root --

    def _build_root(self) -> BrowseMediaSource:
        """Build the root browse page with categories."""
        base = BrowseMediaSource(
            domain=DOMAIN,
            identifier=None,
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.MUSIC,
            title=self.name,
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.DIRECTORY,
        )
        base.children = [
            self._category("Artists", CAT_ARTISTS),
            self._category("Albums", CAT_ALBUMS),
            self._category("Playlists", CAT_PLAYLISTS),
            self._category("Genres", CAT_GENRES),
            self._category("Recently Added", CAT_RECENT),
            self._category("Most Played", CAT_MOST_PLAYED),
            self._category("Random", CAT_RANDOM),
        ]
        return base

    def _category(self, title: str, identifier: str) -> BrowseMediaSource:
        """Build a category entry."""
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=identifier,
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.MUSIC,
            title=title,
            can_play=False,
            can_expand=True,
        )

    # -- Artists --

    async def _build_artists(self) -> BrowseMediaSource:
        """Build the artists listing."""
        artists = await self.client.get_artists()

        result = BrowseMediaSource(
            domain=DOMAIN,
            identifier=CAT_ARTISTS,
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.MUSIC,
            title="Artists",
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.ARTIST,
        )
        result.children = [
            BrowseMediaSource(
                domain=DOMAIN,
                identifier=f"{PREFIX_ARTIST}/{artist['id']}",
                media_class=MediaClass.ARTIST,
                media_content_type=MediaType.MUSIC,
                title=artist.get("name", "Unknown Artist"),
                can_play=False,
                can_expand=True,
                thumbnail=self.client.cover_art_url(artist["coverArt"])
                if artist.get("coverArt")
                else None,
            )
            for artist in artists
        ]
        return result

    async def _build_artist_detail(self, artist_id: str) -> BrowseMediaSource:
        """Build an artist detail page with albums."""
        artist = await self.client.get_artist(artist_id)
        albums = artist.get("album", [])

        result = BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"{PREFIX_ARTIST}/{artist_id}",
            media_class=MediaClass.ARTIST,
            media_content_type=MediaType.MUSIC,
            title=artist.get("name", "Unknown Artist"),
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.ALBUM,
            thumbnail=self.client.cover_art_url(artist["coverArt"])
            if artist.get("coverArt")
            else None,
        )
        result.children = [self._album_item(album) for album in albums]
        return result

    # -- Albums --

    async def _build_album_list(
        self, list_type: str, title: str
    ) -> BrowseMediaSource:
        """Build an album list page."""
        albums = await self.client.get_album_list2(list_type, size=50)

        identifier_map = {
            "alphabeticalByName": CAT_ALBUMS,
            "newest": CAT_RECENT,
            "frequent": CAT_MOST_PLAYED,
            "random": CAT_RANDOM,
        }
        result = BrowseMediaSource(
            domain=DOMAIN,
            identifier=identifier_map.get(list_type, CAT_ALBUMS),
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.MUSIC,
            title=title,
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.ALBUM,
        )
        result.children = [self._album_item(album) for album in albums]
        return result

    async def _build_album_detail(self, album_id: str) -> BrowseMediaSource:
        """Build an album detail page with songs."""
        album = await self.client.get_album(album_id)
        songs = album.get("song", [])

        result = BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"{PREFIX_ALBUM}/{album_id}",
            media_class=MediaClass.ALBUM,
            media_content_type=MediaType.MUSIC,
            title=album.get("name", "Unknown Album"),
            can_play=True,
            can_expand=True,
            children_media_class=MediaClass.TRACK,
            thumbnail=self.client.cover_art_url(album["coverArt"])
            if album.get("coverArt")
            else None,
        )
        result.children = [
            self._song_item(song)
            for song in sorted(songs, key=lambda s: (s.get("discNumber", 0), s.get("track", 0)))
        ]
        return result

    # -- Playlists --

    async def _build_playlists(self) -> BrowseMediaSource:
        """Build the playlists listing."""
        playlists = await self.client.get_playlists()

        result = BrowseMediaSource(
            domain=DOMAIN,
            identifier=CAT_PLAYLISTS,
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.MUSIC,
            title="Playlists",
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.PLAYLIST,
        )
        result.children = [
            BrowseMediaSource(
                domain=DOMAIN,
                identifier=f"{PREFIX_PLAYLIST}/{pl['id']}",
                media_class=MediaClass.PLAYLIST,
                media_content_type=MediaType.PLAYLIST,
                title=pl.get("name", "Unknown Playlist"),
                can_play=True,
                can_expand=True,
                thumbnail=self.client.cover_art_url(pl["coverArt"])
                if pl.get("coverArt")
                else None,
            )
            for pl in playlists
        ]
        return result

    async def _build_playlist_detail(self, playlist_id: str) -> BrowseMediaSource:
        """Build a playlist detail page with songs."""
        playlist = await self.client.get_playlist(playlist_id)
        entries = playlist.get("entry", [])

        result = BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"{PREFIX_PLAYLIST}/{playlist_id}",
            media_class=MediaClass.PLAYLIST,
            media_content_type=MediaType.PLAYLIST,
            title=playlist.get("name", "Unknown Playlist"),
            can_play=True,
            can_expand=True,
            children_media_class=MediaClass.TRACK,
            thumbnail=self.client.cover_art_url(playlist["coverArt"])
            if playlist.get("coverArt")
            else None,
        )
        result.children = [self._song_item(song) for song in entries]
        return result

    # -- Genres --

    async def _build_genres(self) -> BrowseMediaSource:
        """Build the genres listing."""
        genres = await self.client.get_genres()
        genres = sorted(genres, key=lambda g: g.get("value", ""))

        result = BrowseMediaSource(
            domain=DOMAIN,
            identifier=CAT_GENRES,
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.MUSIC,
            title="Genres",
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.GENRE,
        )
        result.children = [
            BrowseMediaSource(
                domain=DOMAIN,
                identifier=f"{PREFIX_GENRE}/{genre.get('value', '')}",
                media_class=MediaClass.GENRE,
                media_content_type=MediaType.MUSIC,
                title=genre.get("value", "Unknown Genre"),
                can_play=False,
                can_expand=True,
            )
            for genre in genres
            if genre.get("value")
        ]
        return result

    async def _build_genre_albums(self, genre_name: str) -> BrowseMediaSource:
        """Build a genre detail page with albums."""
        albums = await self.client.get_album_list2(
            "byGenre", size=50, genre=genre_name
        )

        result = BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"{PREFIX_GENRE}/{genre_name}",
            media_class=MediaClass.GENRE,
            media_content_type=MediaType.MUSIC,
            title=genre_name,
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.ALBUM,
        )
        result.children = [self._album_item(album) for album in albums]
        return result

    # -- Item builders --

    def _album_item(self, album: dict[str, Any]) -> BrowseMediaSource:
        """Build a single album browse item."""
        title = album.get("name", "Unknown Album")
        artist = album.get("artist")
        if artist:
            title = f"{title} - {artist}"

        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"{PREFIX_ALBUM}/{album['id']}",
            media_class=MediaClass.ALBUM,
            media_content_type=MediaType.MUSIC,
            title=title,
            can_play=True,
            can_expand=True,
            thumbnail=self.client.cover_art_url(album["coverArt"])
            if album.get("coverArt")
            else None,
        )

    def _song_item(self, song: dict[str, Any]) -> BrowseMediaSource:
        """Build a single song browse item."""
        title = song.get("title", "Unknown Track")
        artist = song.get("artist")
        if artist:
            title = f"{artist} - {title}"

        mime_type = song.get("contentType", "audio/mpeg")

        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=f"{PREFIX_SONG}/{song['id']}",
            media_class=MediaClass.TRACK,
            media_content_type=mime_type,
            title=title,
            can_play=True,
            can_expand=False,
            thumbnail=self.client.cover_art_url(song["coverArt"])
            if song.get("coverArt")
            else None,
        )


def _parse_identifier(identifier: str) -> tuple[str, str]:
    """Parse a type/id identifier string."""
    parts = identifier.split("/", 1)
    if len(parts) != 2:
        raise BrowseError(f"Invalid identifier format: {identifier}")
    return parts[0], parts[1]
