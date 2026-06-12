"""Tests for the Navidrome media player."""

from __future__ import annotations

import asyncio
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from custom_components.navidrome import NavidromeData, apply_reorder
from custom_components.navidrome.media_player import NavidromeMediaPlayer

from .conftest import MOCK_ALBUM_DETAIL, MOCK_PLAYLISTS, MOCK_PLAYLIST_DETAIL, MOCK_SONG


def _make_player(
    target_player: str | None = "media_player.test_speaker",
    scrobble_enabled: bool = False,
) -> NavidromeMediaPlayer:
    """Create a NavidromeMediaPlayer with mock data and a real asyncio.Lock."""
    mock_client = MagicMock()
    mock_client.get_song = AsyncMock(return_value=MOCK_SONG)
    mock_client.get_album = AsyncMock(return_value=MOCK_ALBUM_DETAIL)
    mock_client.get_playlist = AsyncMock(return_value=MOCK_PLAYLIST_DETAIL)
    mock_client.get_playlists = AsyncMock(return_value=MOCK_PLAYLISTS)
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
    # Wire data.hass so save_queue can dispatch signals
    data.hass = player.hass
    data.entry_id = "test_entry_123"
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
        """Test that play_media calls stop → clear → play_media on target in order."""
        player = _make_player()
        player.async_write_ha_state = MagicMock()

        await player.async_play_media(
            "music",
            "media-source://navidrome/song/tr-1",
        )

        # Verify play_media service is called for the track (may not be index 0 due to stop/clear)
        player.hass.services.async_call.assert_any_call(
            "media_player", "play_media",
            {
                "entity_id": "media_player.test_speaker",
                "media_content_id": ANY,
                "media_content_type": "audio/mpeg",
            },
            blocking=True,
        )

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
        """Test play sets optimistic state and forwards to target."""
        from homeassistant.components.media_player import MediaPlayerState
        player = _make_player()
        player.async_write_ha_state = MagicMock()
        await player.async_media_play()

        assert player._attr_state == MediaPlayerState.PLAYING
        player.hass.services.async_call.assert_called_once_with(
            "media_player",
            "media_play",
            {"entity_id": "media_player.test_speaker"},
            blocking=True,
        )

    async def test_pause(self) -> None:
        """Test pause sets optimistic state and forwards to target."""
        from homeassistant.components.media_player import MediaPlayerState
        player = _make_player()
        player.async_write_ha_state = MagicMock()
        await player.async_media_pause()

        assert player._attr_state == MediaPlayerState.PAUSED
        player.hass.services.async_call.assert_called_once_with(
            "media_player",
            "media_pause",
            {"entity_id": "media_player.test_speaker"},
            blocking=True,
        )

    async def test_stop(self) -> None:
        """Test stop sets optimistic state and forwards to target."""
        from homeassistant.components.media_player import MediaPlayerState
        player = _make_player()
        player.async_write_ha_state = MagicMock()
        await player.async_media_stop()

        assert player._attr_state == MediaPlayerState.IDLE
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


class TestFindInQueue:
    """Test _find_in_queue method."""

    def test_find_by_media_source_uri(self) -> None:
        """Test finding a song by media-source URI."""
        player = _make_player()
        player.data.queue = [
            {"id": "tr-1", "title": "Track A"},
            {"id": "tr-2", "title": "Track B"},
        ]
        assert player._find_in_queue("media-source://navidrome/song/tr-2") == 1

    def test_find_by_stream_url(self) -> None:
        """Test finding a song by stream URL."""
        player = _make_player()
        player.data.queue = [
            {"id": "tr-1", "title": "Track A"},
            {"id": "tr-2", "title": "Track B"},
        ]
        url = "http://navidrome.local:4533/rest/stream?id=tr-1&u=admin"
        assert player._find_in_queue(url) == 0

    def test_not_found(self) -> None:
        """Test returns None when not in queue."""
        player = _make_player()
        player.data.queue = [{"id": "tr-1", "title": "Track A"}]
        assert player._find_in_queue("media-source://navidrome/song/tr-99") is None

    def test_empty_queue(self) -> None:
        """Test returns None with empty queue."""
        player = _make_player()
        assert player._find_in_queue("media-source://navidrome/song/tr-1") is None

    def test_album_uri_not_matched(self) -> None:
        """Test album URIs don't match queue songs."""
        player = _make_player()
        player.data.queue = [{"id": "tr-1", "title": "Track A"}]
        assert player._find_in_queue("media-source://navidrome/album/al-1") is None


class TestPlayFromQueueIndex:
    """Test _play_from_queue_index method."""

    async def test_plays_from_index_and_enqueues_rest(self) -> None:
        """Test playing from a queue index plays first track; tail goes to background worker."""
        player = _make_player()
        player.async_write_ha_state = MagicMock()
        player.data.queue = [
            {"id": "tr-1", "url": "http://a/1", "title": "A", "coverArt": None},
            {"id": "tr-2", "url": "http://a/2", "title": "B", "coverArt": None},
            {"id": "tr-3", "url": "http://a/3", "title": "C", "coverArt": None},
        ]

        await player._play_from_queue_index("media_player.test_speaker", 1)

        assert player.data.current_index == 1
        # stop + clear + play track B = 3 foreground calls; track C goes to background worker
        assert player.hass.services.async_call.call_count == 3
        # Background worker task was created
        player.hass.async_create_task.assert_called()

    async def test_updates_metadata(self) -> None:
        """Test playing from index updates media attributes."""
        player = _make_player()
        player.async_write_ha_state = MagicMock()
        player.data.queue = [
            {"id": "tr-1", "url": "http://a/1", "title": "A", "artist": "X", "coverArt": None},
            {"id": "tr-2", "url": "http://a/2", "title": "B", "artist": "Y", "coverArt": "ca-2"},
        ]

        await player._play_from_queue_index("media_player.test_speaker", 1)

        assert player._attr_media_title == "B"
        assert player._attr_media_artist == "Y"


class TestSearchAndScrobble:
    """Test _search_and_scrobble method."""

    async def test_search_and_scrobble_success(self) -> None:
        """Test searching for a track and scrobbling it."""
        player = _make_player(scrobble_enabled=True)
        player.client.search3 = AsyncMock(return_value={
            "song": [{"id": "tr-found", "title": "Found Track"}],
        })
        await player._search_and_scrobble("Found Track", "Some Artist")

        player.client.search3.assert_called_once()
        player.client.scrobble.assert_called_once_with("tr-found", submission=False)

    async def test_search_and_scrobble_not_found(self) -> None:
        """Test when search returns no results."""
        player = _make_player(scrobble_enabled=True)
        player.client.search3 = AsyncMock(return_value={"song": []})

        await player._search_and_scrobble("Unknown", "Nobody")

        player.client.scrobble.assert_not_called()

    async def test_search_and_scrobble_error(self) -> None:
        """Test search_and_scrobble handles errors."""
        player = _make_player(scrobble_enabled=True)
        player.client.search3 = AsyncMock(side_effect=Exception("Network error"))

        # Should not raise
        await player._search_and_scrobble("Track", "Artist")


class TestSearchMedia:
    """Test search_media functionality."""

    async def test_search_returns_songs_albums_artists(self) -> None:
        """Test search returns all result types."""
        player = _make_player()
        from homeassistant.components.media_player.browse_media import SearchMediaQuery
        query = SearchMediaQuery(search_query="Beatles")
        result = await player.async_search_media(query)

        assert len(result.result) == 3  # 1 song + 1 album + 1 artist
        # First result is a song
        assert result.result[0].can_play is True
        assert "The Beatles" in result.result[0].title
        # Second is album
        assert result.result[1].can_expand is True
        # Third is artist
        assert result.result[2].can_play is False


class TestScrobbleTrack:
    """Test _scrobble_track method."""

    async def test_scrobble_track_success(self) -> None:
        """Test scrobble_track calls client.scrobble."""
        player = _make_player(scrobble_enabled=True)
        await player._scrobble_track("tr-1")
        player.client.scrobble.assert_called_once_with("tr-1", submission=False)

    async def test_scrobble_track_failure_silent(self) -> None:
        """Test scrobble_track handles errors silently."""
        player = _make_player(scrobble_enabled=True)
        player.client.scrobble.side_effect = Exception("Network error")
        # Should not raise
        await player._scrobble_track("tr-1")


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
        assert features & MediaPlayerEntityFeature.REPEAT_SET


class TestApplyReorder:
    """Test the apply_reorder pure helper."""

    def test_basic_reorder(self) -> None:
        """Test moving a track forward."""
        queue = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]
        new_idx, dirty = apply_reorder(queue, 0, 2, 3)
        assert [t["id"] for t in queue] == ["a", "b", "d", "c"]
        assert new_idx == 0
        assert dirty is True  # indices 2,3 > current 0

    def test_move_before_current(self) -> None:
        """Moving a track entirely before current position does not dirty the tail."""
        queue = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]
        new_idx, dirty = apply_reorder(queue, 2, 0, 1)
        assert [t["id"] for t in queue] == ["b", "a", "c", "d"]
        assert new_idx == 2
        assert dirty is False  # max(0,1)=1 <= 2

    def test_move_current_track(self) -> None:
        """Moving the current track changes current_index to the destination."""
        queue = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        new_idx, dirty = apply_reorder(queue, 1, 1, 2)
        assert [t["id"] for t in queue] == ["a", "c", "b"]
        assert new_idx == 2
        assert dirty is False  # new index is 2, max(1,2)=2 == new_idx, not >

    def test_noop_same_index(self) -> None:
        """No-op when from == to."""
        queue = [{"id": "a"}, {"id": "b"}]
        new_idx, dirty = apply_reorder(queue, 0, 1, 1)
        assert new_idx == 0
        assert dirty is False

    def test_current_shifts_left_when_item_before_current_moved_after(self) -> None:
        """When an item before current is moved after current, current shifts left."""
        queue = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]
        # current=2 (c), move index 0 (a) to index 3 → [b, c, d, a]
        new_idx, dirty = apply_reorder(queue, 2, 0, 3)
        assert [t["id"] for t in queue] == ["b", "c", "d", "a"]
        assert new_idx == 1  # c shifts from index 2 to index 1
        # max(0,3)=3 > new_idx(1) → tail changed
        assert dirty is True

    def test_dirty_flag_reflects_tail_change(self) -> None:
        """Tail is dirty when max(from,to) > new_current_index."""
        queue = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]
        new_idx, dirty = apply_reorder(queue, 1, 0, 3)
        # pop a from 0 → [b,c,d], current 1→0. insert a at 3 → [b,c,d,a]. 3>0 no shift. new=0
        assert new_idx == 0
        assert dirty is True  # max(0,3)=3 > 0


class TestEnqueueWorker:
    """Test the background enqueue worker."""

    async def test_worker_enqueues_all_tracks(self) -> None:
        """Worker calls play_media with enqueue=add for each track."""
        player = _make_player()
        player.data.queue = [
            {"id": "tr-1", "url": "http://a/1", "title": "A"},
            {"id": "tr-2", "url": "http://a/2", "title": "B"},
            {"id": "tr-3", "url": "http://a/3", "title": "C"},
        ]

        await player._enqueue_worker("media_player.test_speaker", 1)

        # Tracks at indices 1 and 2 enqueued (start_index=1)
        assert player.hass.services.async_call.call_count == 2
        for call in player.hass.services.async_call.call_args_list:
            assert call[0][2].get("enqueue") == "add"

    async def test_worker_continues_after_per_track_error(self) -> None:
        """A per-track service error does not abort the whole worker."""
        player = _make_player()
        player.data.queue = [
            {"url": "http://a/1", "title": "A"},
            {"url": "http://a/2", "title": "B"},
            {"url": "http://a/3", "title": "C"},
        ]

        call_count = 0

        async def fail_first(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Network blip")

        player.hass.services.async_call = fail_first

        await player._enqueue_worker("media_player.test_speaker", 0)

        assert call_count == 3  # All three tracks attempted

    async def test_worker_propagates_cancellation(self) -> None:
        """CancelledError propagates out of the worker (task can be cancelled)."""
        player = _make_player()
        player.data.queue = [
            {"url": "http://a/1", "title": "A"},
            {"url": "http://a/2", "title": "B"},
        ]

        ready = asyncio.Event()

        async def slow_call(*args, **kwargs):
            ready.set()
            await asyncio.sleep(10)  # hangs until cancelled

        player.hass.services.async_call = slow_call

        task = asyncio.ensure_future(
            player._enqueue_worker("media_player.test_speaker", 0)
        )
        await ready.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_live_queue_appends_picked_up(self) -> None:
        """Worker picks up tracks appended to data.queue after it started."""
        player = _make_player()
        player.data.queue = [{"url": "http://a/1", "title": "A"}]

        call_count = 0
        appended = False

        async def counting_call(*args, **kwargs):
            nonlocal call_count, appended
            call_count += 1
            if not appended:
                appended = True
                player.data.queue.append({"url": "http://a/2", "title": "B"})

        player.hass.services.async_call = counting_call

        await player._enqueue_worker("media_player.test_speaker", 0)

        assert call_count == 2  # Original + appended track


class TestOptimisticGrace:
    """Test the optimistic state grace window."""

    async def test_contradicting_state_ignored_within_grace(self) -> None:
        """Target reporting 'playing' while we hold optimistic 'paused' is ignored."""
        from homeassistant.components.media_player import MediaPlayerState
        player = _make_player()
        player.async_write_ha_state = MagicMock()

        player._set_optimistic_state(MediaPlayerState.PAUSED)
        assert player._attr_state == MediaPlayerState.PAUSED
        assert player._optimistic_deadline > 0

        new_state = MagicMock()
        new_state.state = "playing"
        new_state.attributes = {"media_title": None, "media_artist": None, "repeat": None}

        event = MagicMock()
        event.data = {"new_state": new_state}
        player._async_target_state_changed(event)

        assert player._attr_state == MediaPlayerState.PAUSED  # optimistic kept

    async def test_confirming_state_clears_grace(self) -> None:
        """Target confirming the optimistic state clears the grace window."""
        from homeassistant.components.media_player import MediaPlayerState
        player = _make_player()
        player.async_write_ha_state = MagicMock()

        player._set_optimistic_state(MediaPlayerState.PAUSED)

        new_state = MagicMock()
        new_state.state = "paused"
        new_state.attributes = {"media_title": None, "media_artist": None, "repeat": None}

        event = MagicMock()
        event.data = {"new_state": new_state}
        player._async_target_state_changed(event)

        assert player._attr_state == MediaPlayerState.PAUSED
        assert player._optimistic_deadline == 0.0  # grace cleared

    async def test_state_adopted_outside_grace(self) -> None:
        """State from target is adopted when no grace window is active."""
        from homeassistant.components.media_player import MediaPlayerState
        player = _make_player()
        player.async_write_ha_state = MagicMock()
        player._optimistic_deadline = 0.0  # no grace

        new_state = MagicMock()
        new_state.state = "paused"
        new_state.attributes = {"media_title": None, "media_artist": None, "repeat": None}

        event = MagicMock()
        event.data = {"new_state": new_state}
        player._async_target_state_changed(event)

        assert player._attr_state == MediaPlayerState.PAUSED

    async def test_buffering_maps_to_playing(self) -> None:
        """Target 'buffering' state maps to PLAYING, not IDLE."""
        from homeassistant.components.media_player import MediaPlayerState
        player = _make_player()
        player.async_write_ha_state = MagicMock()
        player._optimistic_deadline = 0.0

        new_state = MagicMock()
        new_state.state = "buffering"
        new_state.attributes = {"media_title": None, "media_artist": None, "repeat": None}

        event = MagicMock()
        event.data = {"new_state": new_state}
        player._async_target_state_changed(event)

        assert player._attr_state == MediaPlayerState.PLAYING


class TestRepeatFeature:
    """Test repeat mode support."""

    async def test_set_repeat_updates_attr_and_persists(self) -> None:
        """async_set_repeat stores mode and proxies to target."""
        from homeassistant.components.media_player import RepeatMode
        player = _make_player()
        player.async_write_ha_state = MagicMock()

        await player.async_set_repeat(RepeatMode.ALL)

        assert player._attr_repeat == RepeatMode.ALL
        assert player.data.repeat_mode == "all"
        player.hass.services.async_call.assert_called_with(
            "media_player", "repeat_set",
            {"entity_id": "media_player.test_speaker", "repeat": "all"},
            blocking=True,
        )

    async def test_set_repeat_off_does_not_proxy(self) -> None:
        """Setting repeat to off skips the re-assert call (nothing to assert)."""
        from homeassistant.components.media_player import RepeatMode
        player = _make_player()
        player.async_write_ha_state = MagicMock()

        await player.async_set_repeat(RepeatMode.OFF)

        assert player._attr_repeat == RepeatMode.OFF
        assert player.data.repeat_mode == "off"
        # repeat_set should not be called when mode is "off"
        for call in player.hass.services.async_call.call_args_list:
            assert call[0][1] != "repeat_set"

    async def test_repeat_re_asserted_after_play_media(self) -> None:
        """After a queue rebuild, repeat mode is re-asserted on the target."""
        from homeassistant.components.media_player import RepeatMode
        player = _make_player()
        player.async_write_ha_state = MagicMock()
        player.data.repeat_mode = "all"

        await player.async_play_media("music", "media-source://navidrome/song/tr-1")

        # repeat_set should have been called with "all"
        player.hass.services.async_call.assert_any_call(
            "media_player", "repeat_set",
            {"entity_id": "media_player.test_speaker", "repeat": "all"},
            blocking=True,
        )

    async def test_state_listener_syncs_repeat_outside_grace(self) -> None:
        """Repeat attribute from target is synced to entity outside grace window."""
        from homeassistant.components.media_player import RepeatMode
        player = _make_player()
        player.async_write_ha_state = MagicMock()
        player._repeat_grace_deadline = 0.0

        new_state = MagicMock()
        new_state.state = "playing"
        new_state.attributes = {
            "media_title": None,
            "media_artist": None,
            "repeat": "one",
        }

        event = MagicMock()
        event.data = {"new_state": new_state}
        player._async_target_state_changed(event)

        assert player._attr_repeat == RepeatMode.ONE
        assert player.data.repeat_mode == "one"


class TestPlaylistSearch:
    """Test playlist search results in async_search_media."""

    async def test_search_returns_playlists(self) -> None:
        """Playlist search results appear when query matches playlist name."""
        player = _make_player()
        from homeassistant.components.media_player.browse_media import SearchMediaQuery
        player.client.search3 = AsyncMock(return_value={"song": [], "album": [], "artist": []})

        query = SearchMediaQuery(search_query="Favorites")
        result = await player.async_search_media(query)

        playlist_results = [r for r in result.result if r.media_class.value == "playlist"]
        assert len(playlist_results) == 1
        assert playlist_results[0].title == "Favorites"
        assert "pl-1" in playlist_results[0].media_content_id

    async def test_search_no_playlist_match(self) -> None:
        """No playlist results when query does not match any playlist name."""
        player = _make_player()
        from homeassistant.components.media_player.browse_media import SearchMediaQuery
        player.client.search3 = AsyncMock(return_value={"song": [], "album": [], "artist": []})

        query = SearchMediaQuery(search_query="NonExistentXYZ")
        result = await player.async_search_media(query)

        playlist_results = [r for r in result.result if r.media_class.value == "playlist"]
        assert len(playlist_results) == 0

    async def test_playlist_fetch_failure_does_not_break_search(self) -> None:
        """A get_playlists failure leaves songs/albums in results unchanged."""
        player = _make_player()
        from homeassistant.components.media_player.browse_media import SearchMediaQuery
        player.client.search3 = AsyncMock(return_value={
            "song": [MOCK_SONG],
            "album": [],
            "artist": [],
        })
        player.client.get_playlists = AsyncMock(side_effect=Exception("Network error"))

        query = SearchMediaQuery(search_query="come")
        result = await player.async_search_media(query)

        # Songs still returned despite playlist failure
        song_results = [r for r in result.result if r.media_class.value == "track"]
        assert len(song_results) == 1

    async def test_playlist_cache_used_on_second_call(self) -> None:
        """get_playlists is only called once within the TTL window."""
        player = _make_player()
        from homeassistant.components.media_player.browse_media import SearchMediaQuery
        player.client.search3 = AsyncMock(return_value={"song": [], "album": [], "artist": []})

        query = SearchMediaQuery(search_query="Fav")
        await player.async_search_media(query)
        await player.async_search_media(query)

        assert player.client.get_playlists.call_count == 1  # cached after first call

    async def test_empty_filter_classes_includes_playlists(self) -> None:
        """The WS handler passes media_filter_classes=[] when unfiltered.

        Regression test: empty list must be treated as 'no filter', not as
        'exclude everything'.
        """
        player = _make_player()
        from homeassistant.components.media_player.browse_media import SearchMediaQuery
        player.client.search3 = AsyncMock(return_value={"song": [], "album": [], "artist": []})

        query = SearchMediaQuery(search_query="Favorites", media_filter_classes=[])
        result = await player.async_search_media(query)

        playlist_results = [r for r in result.result if r.media_class.value == "playlist"]
        assert len(playlist_results) == 1

    async def test_filter_classes_without_playlist_excludes_playlists(self) -> None:
        """An explicit filter that omits PLAYLIST excludes playlist results."""
        player = _make_player()
        from homeassistant.components.media_player import MediaClass
        from homeassistant.components.media_player.browse_media import SearchMediaQuery
        player.client.search3 = AsyncMock(return_value={"song": [], "album": [], "artist": []})

        query = SearchMediaQuery(
            search_query="Favorites", media_filter_classes=[MediaClass.TRACK]
        )
        result = await player.async_search_media(query)

        playlist_results = [r for r in result.result if r.media_class.value == "playlist"]
        assert len(playlist_results) == 0
        player.client.get_playlists.assert_not_called()
