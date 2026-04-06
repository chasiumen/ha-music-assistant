"""Tests for the Navidrome media source."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.components.media_player import MediaClass

from custom_components.navidrome.media_source import (
    CAT_ALBUMS,
    CAT_ARTISTS,
    CAT_GENRES,
    CAT_MOST_PLAYED,
    CAT_PLAYLISTS,
    CAT_RANDOM,
    CAT_RECENT,
    PREFIX_ALBUM,
    PREFIX_ARTIST,
    PREFIX_GENRE,
    PREFIX_PLAYLIST,
    PREFIX_SONG,
    NavidromeSource,
    _parse_identifier,
)

from .conftest import (
    MOCK_ALBUM_DETAIL,
    MOCK_ALBUM_LIST,
    MOCK_ARTIST_DETAIL,
    MOCK_ARTISTS,
    MOCK_GENRES,
    MOCK_PLAYLIST_DETAIL,
    MOCK_PLAYLISTS,
)


class TestParseIdentifier:
    """Test identifier parsing."""

    def test_valid_song(self) -> None:
        item_type, item_id = _parse_identifier("song/tr-123")
        assert item_type == "song"
        assert item_id == "tr-123"

    def test_valid_album(self) -> None:
        item_type, item_id = _parse_identifier("album/al-456")
        assert item_type == "album"
        assert item_id == "al-456"

    def test_valid_genre_with_spaces(self) -> None:
        item_type, item_id = _parse_identifier("genre/Classic Rock")
        assert item_type == "genre"
        assert item_id == "Classic Rock"

    def test_invalid_format(self) -> None:
        from homeassistant.components.media_player import BrowseError

        with pytest.raises(BrowseError):
            _parse_identifier("invalid")


class TestNavidromeSourceBrowse:
    """Test media source browse functionality."""

    def test_root_has_all_categories(self) -> None:
        """Test that root browse returns all category entries."""
        source = _make_source(MagicMock())
        root = source._build_root()

        assert root.title == "Navidrome"
        assert root.can_play is False
        assert root.can_expand is True
        assert len(root.children) == 7

        titles = [c.title for c in root.children]
        assert "Artists" in titles
        assert "Albums" in titles
        assert "Playlists" in titles
        assert "Genres" in titles
        assert "Recently Added" in titles
        assert "Most Played" in titles
        assert "Random" in titles


class TestNavidromeSourceBrowseAsync:
    """Test async browse methods."""

    async def test_browse_root(self, mock_navidrome_client: MagicMock) -> None:
        """Test browsing root returns categories."""
        source = _make_source(mock_navidrome_client)
        item = _make_item(None)
        result = await source.async_browse_media(item)
        assert result.title == "Navidrome"
        assert len(result.children) == 7

    async def test_browse_artists(self, mock_navidrome_client: MagicMock) -> None:
        """Test browsing artists category."""
        source = _make_source(mock_navidrome_client)
        item = _make_item(CAT_ARTISTS)
        result = await source.async_browse_media(item)
        assert result.title == "Artists"
        mock_navidrome_client.get_artists.assert_called_once()
        assert len(result.children) == 2

    async def test_browse_artist_detail(self, mock_navidrome_client: MagicMock) -> None:
        """Test browsing a specific artist shows albums."""
        source = _make_source(mock_navidrome_client)
        item = _make_item(f"{PREFIX_ARTIST}/ar-1")
        result = await source.async_browse_media(item)
        mock_navidrome_client.get_artist.assert_called_once_with("ar-1")
        assert len(result.children) == 2  # 2 albums in MOCK_ARTIST_DETAIL

    async def test_browse_album_detail(self, mock_navidrome_client: MagicMock) -> None:
        """Test browsing a specific album shows songs."""
        source = _make_source(mock_navidrome_client)
        item = _make_item(f"{PREFIX_ALBUM}/al-1")
        result = await source.async_browse_media(item)
        mock_navidrome_client.get_album.assert_called_once_with("al-1")
        assert len(result.children) == 2  # 2 songs in MOCK_ALBUM_DETAIL
        assert result.can_play is True

    async def test_browse_playlists(self, mock_navidrome_client: MagicMock) -> None:
        """Test browsing playlists category."""
        source = _make_source(mock_navidrome_client)
        item = _make_item(CAT_PLAYLISTS)
        result = await source.async_browse_media(item)
        assert result.title == "Playlists"
        mock_navidrome_client.get_playlists.assert_called_once()

    async def test_browse_playlist_detail(self, mock_navidrome_client: MagicMock) -> None:
        """Test browsing a specific playlist shows entries."""
        source = _make_source(mock_navidrome_client)
        item = _make_item(f"{PREFIX_PLAYLIST}/pl-1")
        result = await source.async_browse_media(item)
        mock_navidrome_client.get_playlist.assert_called_once_with("pl-1")
        assert len(result.children) == 1

    async def test_browse_genres(self, mock_navidrome_client: MagicMock) -> None:
        """Test browsing genres category."""
        source = _make_source(mock_navidrome_client)
        item = _make_item(CAT_GENRES)
        result = await source.async_browse_media(item)
        assert result.title == "Genres"
        mock_navidrome_client.get_genres.assert_called_once()
        assert len(result.children) == 2  # Rock, Jazz

    async def test_browse_genre_albums(self, mock_navidrome_client: MagicMock) -> None:
        """Test browsing a specific genre shows albums."""
        source = _make_source(mock_navidrome_client)
        item = _make_item(f"{PREFIX_GENRE}/Rock")
        result = await source.async_browse_media(item)
        mock_navidrome_client.get_album_list2.assert_called_once_with("byGenre", size=50, genre="Rock")

    async def test_browse_recent(self, mock_navidrome_client: MagicMock) -> None:
        """Test browsing Recently Added."""
        source = _make_source(mock_navidrome_client)
        item = _make_item(CAT_RECENT)
        result = await source.async_browse_media(item)
        assert result.title == "Recently Added"
        mock_navidrome_client.get_album_list2.assert_called_once()

    async def test_browse_most_played(self, mock_navidrome_client: MagicMock) -> None:
        """Test browsing Most Played."""
        source = _make_source(mock_navidrome_client)
        item = _make_item(CAT_MOST_PLAYED)
        result = await source.async_browse_media(item)
        assert result.title == "Most Played"

    async def test_browse_random(self, mock_navidrome_client: MagicMock) -> None:
        """Test browsing Random."""
        source = _make_source(mock_navidrome_client)
        item = _make_item(CAT_RANDOM)
        result = await source.async_browse_media(item)
        assert result.title == "Random"

    async def test_resolve_no_identifier(self, mock_navidrome_client: MagicMock) -> None:
        """Test resolving with no identifier raises error."""
        from homeassistant.components.media_player import BrowseError
        source = _make_source(mock_navidrome_client)
        item = _make_item(None)
        with pytest.raises(BrowseError):
            await source.async_resolve_media(item)


class TestNavidromeSourceResolve:
    """Test media source resolve functionality."""

    async def test_resolve_song(self, mock_navidrome_client: MagicMock) -> None:
        """Test resolving a song to a stream URL."""
        source = _make_source(mock_navidrome_client)
        item = _make_item(f"{PREFIX_SONG}/tr-1")

        result = await source.async_resolve_media(item)

        assert "stream" in result.url
        assert "id=tr-1" in result.url
        assert result.mime_type == "audio/mpeg"

    async def test_resolve_album(self, mock_navidrome_client: MagicMock) -> None:
        """Test resolving an album plays first song."""
        source = _make_source(mock_navidrome_client)
        item = _make_item(f"{PREFIX_ALBUM}/al-1")

        result = await source.async_resolve_media(item)

        mock_navidrome_client.get_album.assert_called_once_with("al-1")
        assert "stream" in result.url
        assert result.mime_type == "audio/mpeg"

    async def test_resolve_playlist(self, mock_navidrome_client: MagicMock) -> None:
        """Test resolving a playlist plays first entry."""
        source = _make_source(mock_navidrome_client)
        item = _make_item(f"{PREFIX_PLAYLIST}/pl-1")

        result = await source.async_resolve_media(item)

        mock_navidrome_client.get_playlist.assert_called_once_with("pl-1")
        assert "stream" in result.url
        assert result.mime_type == "audio/mpeg"


# -- Helpers --


def _make_source(client: MagicMock) -> NavidromeSource:
    """Create a NavidromeSource with a mocked entry."""
    from custom_components.navidrome import NavidromeData

    mock_entry = MagicMock()
    mock_entry.runtime_data = NavidromeData(client=client)

    source = NavidromeSource.__new__(NavidromeSource)
    source.domain = "navidrome"
    source.name = "Navidrome"
    source.hass = MagicMock()
    source.entry = mock_entry
    return source


def _make_item(identifier: str | None = None) -> MagicMock:
    """Create a mock MediaSourceItem."""
    item = MagicMock()
    item.identifier = identifier
    return item
