"""Tests for removing tracks from the Navidrome queue."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

from homeassistant.components.media_player import MediaPlayerState

from custom_components.navidrome import SERVICE_SCHEMAS, NavidromeData, apply_remove
from custom_components.navidrome.const import SERVICE_REMOVE_FROM_QUEUE

from .test_media_player import _make_player

TARGET = "media_player.test_speaker"


def _tracks(n: int) -> list[dict]:
    return [{"id": f"tr-{i}", "title": f"T{i}", "url": f"http://a/{i}"} for i in range(n)]


def _ids(queue: list[dict]) -> list[str]:
    return [t["id"] for t in queue]


class TestApplyRemove:
    """The pure removal helper."""

    def test_remove_upcoming(self) -> None:
        queue = _tracks(5)
        assert apply_remove(queue, 1, [3]) == (1, False, True)
        assert _ids(queue) == ["tr-0", "tr-1", "tr-2", "tr-4"]

    def test_remove_played_shifts_current(self) -> None:
        queue = _tracks(5)
        assert apply_remove(queue, 3, [0, 1]) == (1, False, False)
        assert queue[1]["id"] == "tr-3"  # still the playing track

    def test_remove_current_points_at_follower(self) -> None:
        queue = _tracks(5)
        assert apply_remove(queue, 2, [2]) == (2, True, False)
        assert queue[2]["id"] == "tr-3"

    def test_remove_current_and_following(self) -> None:
        queue = _tracks(5)
        new_index, removed_current, tail_changed = apply_remove(queue, 2, [2, 3])
        assert (new_index, removed_current, tail_changed) == (2, True, True)
        assert queue[new_index]["id"] == "tr-4"

    def test_remove_last_current_points_past_end(self) -> None:
        queue = _tracks(3)
        assert apply_remove(queue, 2, [2]) == (2, True, False)
        assert len(queue) == 2  # index 2 == len → nothing left to play

    def test_mixed_unsorted_with_duplicates_and_out_of_range(self) -> None:
        queue = _tracks(6)
        assert apply_remove(queue, 2, [4, 0, 4, 99, -1]) == (1, False, True)
        assert _ids(queue) == ["tr-1", "tr-2", "tr-3", "tr-5"]

    def test_remove_everything(self) -> None:
        queue = _tracks(3)
        assert apply_remove(queue, 1, [0, 1, 2]) == (0, True, True)
        assert queue == []


def _data(n: int = 5, current: int = 1) -> NavidromeData:
    data = NavidromeData(client=MagicMock(), queue=_tracks(n), current_index=current)
    data.store = MagicMock()
    data.store.async_save = AsyncMock()
    return data


class TestRemoveTracks:
    """NavidromeData.remove_tracks: validation, flags and persistence."""

    async def test_upcoming_marks_dirty_and_cancels_worker(self) -> None:
        data = _data()
        worker = MagicMock()
        worker.done.return_value = False
        data.enqueue_task = worker

        assert await data.remove_tracks([3]) is None

        assert _ids(data.queue) == ["tr-0", "tr-1", "tr-2", "tr-4"]
        assert data.queue_dirty is True
        worker.cancel.assert_called_once()
        data.store.async_save.assert_awaited_once()

    async def test_played_only_is_bookkeeping(self) -> None:
        data = _data(current=3)
        worker = MagicMock()
        worker.done.return_value = False
        data.enqueue_task = worker

        assert await data.remove_tracks([0]) is None

        assert data.current_index == 2
        assert data.queue[data.current_index]["id"] == "tr-3"
        assert data.queue_dirty is False
        worker.cancel.assert_not_called()

    async def test_current_returns_play_index(self) -> None:
        data = _data(current=1)
        data.queue_dirty = True

        assert await data.remove_tracks([1]) == 1

        assert data.queue[1]["id"] == "tr-2"
        assert data.current_index == 1
        assert data.queue_dirty is False  # the restart rebuilds the whole tail

    async def test_last_current_clamps_index_and_signals_end(self) -> None:
        data = _data(n=3, current=2)

        assert await data.remove_tracks([2]) == 2  # == len(queue): nothing left

        assert data.current_index == 1

    async def test_song_id_mismatch_is_skipped(self) -> None:
        data = _data()

        result = await data.remove_tracks([2, 3], song_ids=["tr-2", "tr-999"])

        assert result is None
        assert _ids(data.queue) == ["tr-0", "tr-1", "tr-3", "tr-4"]

    async def test_nothing_valid_changes_nothing(self) -> None:
        data = _data()

        assert await data.remove_tracks([42], song_ids=["tr-42"]) is None

        assert len(data.queue) == 5
        data.store.async_save.assert_not_awaited()


class TestServiceSchema:
    """The remove_from_queue service schema."""

    schema = SERVICE_SCHEMAS[SERVICE_REMOVE_FROM_QUEUE]

    def test_single_index_becomes_list(self) -> None:
        assert self.schema({"indices": 3}) == {"indices": [3]}

    def test_list_with_song_ids(self) -> None:
        assert self.schema({"indices": ["1", 2], "song_ids": ["a", "b"]}) == {
            "indices": [1, 2],
            "song_ids": ["a", "b"],
        }

    def test_indices_required(self) -> None:
        with pytest.raises(vol.Invalid):
            self.schema({"song_ids": ["a"]})


def _player():
    player = _make_player()
    player.async_write_ha_state = MagicMock()
    player.data.queue = _tracks(4)
    player.data.current_index = 1
    player._play_from_queue_index = AsyncMock()
    return player


class TestPlayQueueIndexSignal:
    """The media player's reaction when the playing track was removed."""

    async def test_playing_continues_with_next_track(self) -> None:
        player = _player()
        player._attr_state = MediaPlayerState.PLAYING

        await player._async_play_queue_index(1)

        player._play_from_queue_index.assert_awaited_once_with(TARGET, 1)
        player.hass.services.async_call.assert_not_called()

    async def test_paused_stops_and_restarts_on_next_play(self) -> None:
        player = _player()
        player._attr_state = MediaPlayerState.PAUSED

        await player._async_play_queue_index(1)

        player._play_from_queue_index.assert_not_awaited()
        player.hass.services.async_call.assert_awaited_once_with(
            "media_player", "media_stop", {"entity_id": TARGET}, blocking=True
        )
        assert player._restart_queue_on_play is True

        await player.async_media_play()

        player._play_from_queue_index.assert_awaited_once_with(TARGET, 1)

    async def test_nothing_left_stops(self) -> None:
        player = _player()
        player._attr_state = MediaPlayerState.PLAYING

        await player._async_play_queue_index(len(player.data.queue))

        player._play_from_queue_index.assert_not_awaited()
        player.hass.services.async_call.assert_awaited_once_with(
            "media_player", "media_stop", {"entity_id": TARGET}, blocking=True
        )

    async def test_play_without_flag_just_resumes(self) -> None:
        player = _player()

        await player.async_media_play()

        player._play_from_queue_index.assert_not_awaited()
        player.hass.services.async_call.assert_awaited_once_with(
            "media_player", "media_play", {"entity_id": TARGET}, blocking=True
        )


class TestRemovedTrackStartedAnyway:
    """Track-change sync when the target starts a track removed from the queue."""

    def _player(self, dirty: bool):
        player = _player()
        player._play_from_queue_index = MagicMock(return_value="play-coro")
        player._async_stop_and_restart_on_play = MagicMock(return_value="stop-coro")
        player.data.queue_dirty = dirty
        return player

    def test_dirty_and_unknown_title_skips_to_next(self) -> None:
        player = self._player(dirty=True)

        player._sync_queue_index("Removed Song", None)

        player._play_from_queue_index.assert_called_once_with(TARGET, 2)
        player.hass.async_create_task.assert_called_once_with("play-coro")
        assert player.data.queue_dirty is False

    def test_dirty_and_unknown_title_at_end_stops(self) -> None:
        player = self._player(dirty=True)
        player.data.current_index = 3  # last track

        player._sync_queue_index("Removed Song", None)

        player._play_from_queue_index.assert_not_called()
        player.hass.async_create_task.assert_called_once_with("stop-coro")

    def test_not_dirty_unknown_title_does_not_skip(self) -> None:
        player = self._player(dirty=False)

        player._sync_queue_index("Some Other Song", None)

        player._play_from_queue_index.assert_not_called()
        player._async_stop_and_restart_on_play.assert_not_called()
