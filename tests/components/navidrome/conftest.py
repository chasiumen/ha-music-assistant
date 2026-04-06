"""Fixtures for Navidrome tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME

from custom_components.navidrome.const import DOMAIN

MOCK_URL = "http://navidrome.local:4533"
MOCK_USERNAME = "testuser"
MOCK_PASSWORD = "testpass"

MOCK_CONFIG = {
    CONF_URL: MOCK_URL,
    CONF_USERNAME: MOCK_USERNAME,
    CONF_PASSWORD: MOCK_PASSWORD,
}

MOCK_SEARCH_RESULTS = {
    "artist": [
        {
            "id": "ar-1",
            "name": "The Beatles",
            "coverArt": "ar-1",
            "albumCount": 12,
        }
    ],
    "album": [
        {
            "id": "al-1",
            "name": "Abbey Road",
            "artist": "The Beatles",
            "artistId": "ar-1",
            "coverArt": "al-1",
            "songCount": 17,
            "duration": 2834,
        }
    ],
    "song": [
        {
            "id": "tr-1",
            "title": "Come Together",
            "artist": "The Beatles",
            "album": "Abbey Road",
            "albumId": "al-1",
            "coverArt": "al-1",
            "duration": 259,
            "contentType": "audio/mpeg",
            "suffix": "mp3",
            "track": 1,
        }
    ],
}

MOCK_ARTISTS = [
    {"id": "ar-1", "name": "The Beatles", "coverArt": "ar-1", "albumCount": 12},
    {"id": "ar-2", "name": "Pink Floyd", "coverArt": "ar-2", "albumCount": 15},
]

MOCK_ARTIST_DETAIL = {
    "id": "ar-1",
    "name": "The Beatles",
    "coverArt": "ar-1",
    "albumCount": 2,
    "album": [
        {
            "id": "al-1",
            "name": "Abbey Road",
            "artist": "The Beatles",
            "coverArt": "al-1",
            "songCount": 17,
        },
        {
            "id": "al-2",
            "name": "Let It Be",
            "artist": "The Beatles",
            "coverArt": "al-2",
            "songCount": 12,
        },
    ],
}

MOCK_ALBUM_DETAIL = {
    "id": "al-1",
    "name": "Abbey Road",
    "artist": "The Beatles",
    "coverArt": "al-1",
    "songCount": 2,
    "song": [
        {
            "id": "tr-1",
            "title": "Come Together",
            "artist": "The Beatles",
            "album": "Abbey Road",
            "coverArt": "al-1",
            "duration": 259,
            "contentType": "audio/mpeg",
            "track": 1,
            "discNumber": 1,
        },
        {
            "id": "tr-2",
            "title": "Something",
            "artist": "The Beatles",
            "album": "Abbey Road",
            "coverArt": "al-1",
            "duration": 182,
            "contentType": "audio/mpeg",
            "track": 2,
            "discNumber": 1,
        },
    ],
}

MOCK_PLAYLISTS = [
    {
        "id": "pl-1",
        "name": "Favorites",
        "songCount": 5,
        "duration": 1200,
        "coverArt": "pl-1",
    },
]

MOCK_PLAYLIST_DETAIL = {
    "id": "pl-1",
    "name": "Favorites",
    "songCount": 1,
    "coverArt": "pl-1",
    "entry": [
        {
            "id": "tr-1",
            "title": "Come Together",
            "artist": "The Beatles",
            "album": "Abbey Road",
            "coverArt": "al-1",
            "duration": 259,
            "contentType": "audio/mpeg",
        },
    ],
}

MOCK_SONG = {
    "id": "tr-1",
    "title": "Come Together",
    "artist": "The Beatles",
    "album": "Abbey Road",
    "albumId": "al-1",
    "coverArt": "al-1",
    "duration": 259,
    "contentType": "audio/mpeg",
    "suffix": "mp3",
    "track": 1,
}

MOCK_GENRES = [
    {"value": "Rock", "songCount": 100, "albumCount": 20},
    {"value": "Jazz", "songCount": 50, "albumCount": 10},
]

MOCK_ALBUM_LIST = [
    {
        "id": "al-1",
        "name": "Abbey Road",
        "artist": "The Beatles",
        "coverArt": "al-1",
        "songCount": 17,
    },
]


@pytest.fixture
def mock_navidrome_client() -> Generator[MagicMock]:
    """Mock the Navidrome API client."""
    with patch(
        "custom_components.navidrome.api.NavidromeClient", autospec=True
    ) as mock_cls:
        client = mock_cls.return_value
        client.ping = AsyncMock(return_value=True)
        client.search3 = AsyncMock(return_value=MOCK_SEARCH_RESULTS)
        client.get_artists = AsyncMock(return_value=MOCK_ARTISTS)
        client.get_artist = AsyncMock(return_value=MOCK_ARTIST_DETAIL)
        client.get_song = AsyncMock(return_value=MOCK_SONG)
        client.get_album = AsyncMock(return_value=MOCK_ALBUM_DETAIL)
        client.get_playlists = AsyncMock(return_value=MOCK_PLAYLISTS)
        client.get_playlist = AsyncMock(return_value=MOCK_PLAYLIST_DETAIL)
        client.get_genres = AsyncMock(return_value=MOCK_GENRES)
        client.get_album_list2 = AsyncMock(return_value=MOCK_ALBUM_LIST)
        client.scrobble = AsyncMock(return_value=None)
        client.stream_url = MagicMock(
            side_effect=lambda song_id: f"http://navidrome.local:4533/rest/stream?id={song_id}"
        )
        client.cover_art_url = MagicMock(
            side_effect=lambda item_id, size=300: f"http://navidrome.local:4533/rest/getCoverArt?id={item_id}&size={size}"
        )
        yield client
