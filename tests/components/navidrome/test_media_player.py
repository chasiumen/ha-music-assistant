"""Tests for the Navidrome media player."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.navidrome import NavidromeData
from custom_components.navidrome.media_player import NavidromeMediaPlayer

from .conftest import MOCK_ALBUM_DETAIL, MOCK_PLAYLIST_DETAIL, MOCK_SONG


def _make_player(
    target_player: str | None = "media_player.test_speaker",
    scrobble_enabled: bool = False,
) -> NavidromeMediaPlayer:
    """Create a NavidromeMediaPlayer with mock data."""
    mock_client = MagicMock()
    mock_client.get_song = AsyncMock(return_value=MOCK_SONG)
    mock_client.get_album = AsyncMock(return_value=MOCK_ALBUM_DETAIL)
    mock_client.get_playlist = AsyncMock(return_value=MOCK_PLAYLIST_DETAIL)
    mock_client.scrobble = AsyncMock(return_value=None)
    mock_client.stream_url = MagicMock(
        side_effect=lambda song_id: f"http://navidrome.local:4533/rest/stream?id={song_id}"
    )
    mock_client.cover_art_url = MagicMock(
        side_effect=lambda item_id, size=300: f"http://navidrome.local:4533/rest/getCoverArt?id={item_id}&size={size}"
    )

    data = NavidromeData(client=mock_client)

    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry_123"
    mock_entry.runtime_data = data
    mock_entry.data = {"url": "http://navidrome.local:4533"}
    mock_entry.title = "Navidrome (test)"
    mock_entry.options = {
        "target_player": target_player,
        "scrobble_enabled": scrobble_enabled,
    }

    player = NavidromeMediaPlayer(mock_entry)
    player.hass = MagicMock()
    player.hass.services = MagicMock()
    player.hass.services.async_call = AsyncMock()
    return player


class TestSongToTrack:
    """Test the _song_to_track helper."""

    def test_converts_song_dict(self) -> None:
        """Test converting a Subsonic song dict to a track dict."""
        player = _make_player()
        track = player._song_to_track(MOCK_SONG)

        assert track["id"] == "tr-1"
        assert "stream" in track["url"]
        assert "id=tr-1" in track["url"]
        assert track["title"] == "Come Together"
        assert track["artist"] == "The Beatles"
        assert track["album"] == "Abbey Road"
        assert track["duration"] == 259
        assert track["coverArt"] == "al-1"

    def test_missing_optional_fields(self) -> None:
        """Test with minimal song dict."""
        player = _make_player()
        track = player._song_to_track({"id": "tr-99"})

        assert track["id"] == "tr-99"
        assert track["url"] is not None
        assert track["title"] is None
        assert track["artist"] is None


class TestExtractSongIdFromUrl:
    """Test the _extract_song_id_from_url helper."""

    def test_valid_stream_url(self) -> None:
        """Test extracting ID from a valid stream URL."""
        url = "http://navidrome.local:4533/rest/stream?id=tr-123&u=admin&t=abc&s=def"
        assert NavidromeMediaPlayer._extract_song_id_from_url(url) == "tr-123"

    def test_no_id_param(self) -> None:
        """Test URL without id parameter."""
        url = "http://navidrome.local:4533/rest/stream?u=admin"
        assert NavidromeMediaPlayer._extract_song_id_from_url(url) is None

    def test_invalid_url(self) -> None:
        """Test with invalid URL."""
        assert NavidromeMediaPlayer._extract_song_id_from_url("not a url") is None

    def test_empty_string(self) -> None:
        """Test with empty string."""
        assert NavidromeMediaPlayer._extract_song_id_from_url("") is None


class TestUpdateMediaAttributes:
    """Test the _update_media_attributes method."""

    def test_sets_all_attributes(self) -> None:
        """Test all media attributes are set from track dict."""
        player = _make_player()
        track = {
            "url": "http://example.com/stream",
            "title": "Test Song",
            "artist": "Test Artist",
            "album": "Test Album",
            "duration": 180,
            "coverArt": "al-123",
        }
        player._update_media_attributes(track)

        assert player._attr_media_content_id == "http://example.com/stream"
        assert player._attr_media_content_type == "audio/mpeg"
        assert player._attr_media_title == "Test Song"
        assert player._attr_media_artist == "Test Artist"
        assert player._attr_media_album_name == "Test Album"
        assert player._attr_media_duration == 180
        assert player._cover_art_url == "/api/navidrome/cover_art/al-123"

    def test_no_cover_art(self) -> None:
        """Test when coverArt is missing."""
        player = _make_player()
        track = {"url": "http://example.com/stream", "title": "No Art"}
        player._update_media_attributes(track)

        assert player._cover_art_url is None

    def test_entity_picture_property(self) -> None:
        """Test entity_picture returns the cover art URL."""
        player = _make_player()
        assert player.entity_picture is None

        player._cover_art_url = "/api/navidrome/cover_art/al-123"
        assert player.entity_picture == "/api/navidrome/cover_art/al-123"


class TestResolveToTracks:
    """Test the _resolve_to_tracks method."""

    async def test_resolve_single_song(self) -> None:
        """Test resolving a single song media-source URI."""
        player = _make_player()
        tracks = await player._resolve_to_tracks("media-source://navidrome/song/tr-1")

        assert len(tracks) == 1
        assert tracks[0]["id"] == "tr-1"
        assert tracks[0]["title"] == "Come Together"
        player.client.get_song.assert_called_once_with("tr-1")

    async def test_resolve_album(self) -> None:
        """Test resolving an album to all its songs."""
        player = _make_player()
        tracks = await player._resolve_to_tracks("media-source://navidrome/album/al-1")

        assert len(tracks) == 2
        assert tracks[0]["title"] == "Come Together"
        assert tracks[1]["title"] == "Something"
        player.client.get_album.assert_called_once_with("al-1")

    async def test_resolve_playlist(self) -> None:
        """Test resolving a playlist to all its entries."""
        player = _make_player()
        tracks = await player._resolve_to_tracks("media-source://navidrome/playlist/pl-1")

        assert len(tracks) == 1
        assert tracks[0]["title"] == "Come Together"
        player.client.get_playlist.assert_called_once_with("pl-1")

    async def test_resolve_direct_stream_url(self) -> None:
        """Test resolving a direct stream URL with song ID extraction."""
        player = _make_player()
        url = "http://navidrome.local:4533/rest/stream?id=tr-1&u=admin&t=abc&s=def"
        tracks = await player._resolve_to_tracks(url)

        assert len(tracks) == 1
        assert tracks[0]["id"] == "tr-1"
        assert tracks[0]["url"] == url
        assert tracks[0]["title"] == "Come Together"
        player.client.get_song.assert_called_once_with("tr-1")

    async def test_resolve_direct_url_no_id(self) -> None:
        """Test resolving a URL without song ID."""
        player = _make_player()
        url = "http://example.com/audio.mp3"
        tracks = await player._resolve_to_tracks(url)

        assert len(tracks) == 1
        assert tracks[0]["id"] is None
        assert tracks[0]["url"] == url


class TestQueueStorage:
    """Test that queue is stored in NavidromeData."""

    async def test_play_media_stores_queue(self) -> None:
        """Test that playing media stores the queue in shared data."""
        player = _make_player()
        player.async_write_ha_state = MagicMock()

        await player.async_play_media(
            "music",
            "media-source://navidrome/album/al-1",
        )

        assert len(player.data.queue) == 2
        assert player.data.current_index == 0
        assert player.data.queue[0]["title"] == "Come Together"
        assert player.data.queue[1]["title"] == "Something"

    async def test_play_media_calls_target(self) -> None:
        """Test that play_media forwards to target player."""
        player = _make_player()
        player.async_write_ha_state = MagicMock()

        await player.async_play_media(
            "music",
            "media-source://navidrome/song/tr-1",
        )

        player.hass.services.async_call.assert_called()
        call_args = player.hass.services.async_call.call_args_list[0]
        assert call_args[0][0] == "media_player"
        assert call_args[0][1] == "play_media"
        assert call_args[0][2]["entity_id"] == "media_player.test_speaker"

    async def test_play_media_no_target(self) -> None:
        """Test play_media logs warning when no target configured."""
        player = _make_player(target_player=None)
        player.async_write_ha_state = MagicMock()

        await player.async_play_media("music", "media-source://navidrome/song/tr-1")

        player.hass.services.async_call.assert_not_called()


class TestScrobble:
    """Test scrobble behavior."""

    async def test_scrobble_when_enabled(self) -> None:
        """Test scrobble is called when enabled."""
        player = _make_player(scrobble_enabled=True)
        player.async_write_ha_state = MagicMock()

        await player.async_play_media(
            "music",
            "media-source://navidrome/song/tr-1",
        )

        player.client.scrobble.assert_called_once_with("tr-1", submission=False)

    async def test_no_scrobble_when_disabled(self) -> None:
        """Test scrobble is not called when disabled."""
        player = _make_player(scrobble_enabled=False)
        player.async_write_ha_state = MagicMock()

        await player.async_play_media(
            "music",
            "media-source://navidrome/song/tr-1",
        )

        player.client.scrobble.assert_not_called()


class TestPlaybackControls:
    """Test playback control proxying."""

    async def test_play(self) -> None:
        """Test play forwards to target."""
        player = _make_player()
        player.async_write_ha_state = MagicMock()
        await player.async_media_play()

        player.hass.services.async_call.assert_called_once_with(
            "media_player",
            "media_play",
            {"entity_id": "media_player.test_speaker"},
            blocking=True,
        )

    async def test_pause(self) -> None:
        """Test pause forwards to target."""
        player = _make_player()
        player.async_write_ha_state = MagicMock()
        await player.async_media_pause()

        player.hass.services.async_call.assert_called_once_with(
            "media_player",
            "media_pause",
            {"entity_id": "media_player.test_speaker"},
            blocking=True,
        )

    async def test_stop(self) -> None:
        """Test stop forwards to target."""
        player = _make_player()
        player.async_write_ha_state = MagicMock()
        await player.async_media_stop()

        player.hass.services.async_call.assert_called_once_with(
            "media_player",
            "media_stop",
            {"entity_id": "media_player.test_speaker"},
            blocking=True,
        )

    async def test_next_track(self) -> None:
        """Test next_track forwards to target."""
        player = _make_player()
        await player.async_media_next_track()

        player.hass.services.async_call.assert_called_once_with(
            "media_player",
            "media_next_track",
            {"entity_id": "media_player.test_speaker"},
            blocking=True,
        )

    async def test_previous_track(self) -> None:
        """Test previous_track forwards to target."""
        player = _make_player()
        await player.async_media_previous_track()

        player.hass.services.async_call.assert_called_once_with(
            "media_player",
            "media_previous_track",
            {"entity_id": "media_player.test_speaker"},
            blocking=True,
        )

    async def test_volume(self) -> None:
        """Test volume_set forwards to target."""
        player = _make_player()
        await player.async_set_volume_level(0.5)

        player.hass.services.async_call.assert_called_once_with(
            "media_player",
            "volume_set",
            {"entity_id": "media_player.test_speaker", "volume_level": 0.5},
            blocking=True,
        )

    async def test_no_target_does_nothing(self) -> None:
        """Test proxy commands do nothing when no target configured."""
        player = _make_player(target_player=None)
        await player.async_media_play()

        player.hass.services.async_call.assert_not_called()


class TestSyncQueueIndex:
    """Test queue index syncing from target player."""

    def test_sync_finds_matching_track(self) -> None:
        """Test _sync_queue_index matches by title and artist."""
        player = _make_player(scrobble_enabled=False)
        player.data.queue = [
            {"title": "Track A", "artist": "Artist 1", "coverArt": "ca-1", "id": "t1"},
            {"title": "Track B", "artist": "Artist 2", "coverArt": "ca-2", "id": "t2"},
            {"title": "Track C", "artist": "Artist 1", "coverArt": "ca-3", "id": "t3"},
        ]
        player.data.current_index = 0

        player._sync_queue_index("Track B", "Artist 2")

        assert player.data.current_index == 1
        assert player._cover_art_url == "/api/navidrome/cover_art/ca-2"

    def test_sync_no_match_keeps_index(self) -> None:
        """Test _sync_queue_index does nothing when no match."""
        player = _make_player(scrobble_enabled=False)
        player.data.queue = [
            {"title": "Track A", "artist": "Artist 1", "id": "t1"},
        ]
        player.data.current_index = 0

        player._sync_queue_index("Unknown Track", "Unknown Artist")

        assert player.data.current_index == 0

    def test_sync_empty_queue(self) -> None:
        """Test _sync_queue_index with empty queue."""
        player = _make_player(scrobble_enabled=False)
        player.data.queue = []
        player.data.current_index = 0

        player._sync_queue_index("Track A", "Artist 1")

        assert player.data.current_index == 0

    def test_sync_title_only_no_artist(self) -> None:
        """Test _sync_queue_index matches by title when artist is None."""
        player = _make_player(scrobble_enabled=False)
        player.data.queue = [
            {"title": "Track A", "artist": "Artist 1", "coverArt": "ca-1", "id": "t1"},
            {"title": "Track B", "artist": "Artist 2", "coverArt": "ca-2", "id": "t2"},
        ]
        player.data.current_index = 0

        player._sync_queue_index("Track B", None)

        assert player.data.current_index == 1


class TestSupportedFeatures:
    """Test supported features declaration."""

    def test_has_required_features(self) -> None:
        """Test all required features are declared."""
        from homeassistant.components.media_player import MediaPlayerEntityFeature

        player = _make_player()
        features = player.supported_features

        assert features & MediaPlayerEntityFeature.PLAY
        assert features & MediaPlayerEntityFeature.PAUSE
        assert features & MediaPlayerEntityFeature.STOP
        assert features & MediaPlayerEntityFeature.NEXT_TRACK
        assert features & MediaPlayerEntityFeature.PREVIOUS_TRACK
        assert features & MediaPlayerEntityFeature.VOLUME_SET
        assert features & MediaPlayerEntityFeature.SEARCH_MEDIA
        assert features & MediaPlayerEntityFeature.PLAY_MEDIA
        assert features & MediaPlayerEntityFeature.BROWSE_MEDIA
        assert features & MediaPlayerEntityFeature.MEDIA_ENQUEUE
