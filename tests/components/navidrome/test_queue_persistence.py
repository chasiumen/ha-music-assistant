"""Tests for queue persistence and clear queue."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.navidrome import NavidromeData


def _make_data(queue: list = None, current_index: int = 0) -> NavidromeData:
    """Create NavidromeData with a mock store."""
    mock_client = MagicMock()
    mock_store = MagicMock()
    mock_store.async_save = AsyncMock()
    mock_store.async_load = AsyncMock(return_value=None)

    data = NavidromeData(
        client=mock_client,
        store=mock_store,
        queue=queue or [],
        current_index=current_index,
    )
    return data


class TestSaveQueue:
    """Test save_queue method."""

    async def test_save_persists_queue_and_index(self) -> None:
        """Test save_queue writes queue and current_index to store."""
        tracks = [
            {"id": "tr-1", "title": "Track A"},
            {"id": "tr-2", "title": "Track B"},
        ]
        data = _make_data(queue=tracks, current_index=1)

        await data.save_queue()

        data.store.async_save.assert_called_once_with({
            "queue": tracks,
            "current_index": 1,
        })

    async def test_save_empty_queue(self) -> None:
        """Test save_queue with empty queue."""
        data = _make_data()

        await data.save_queue()

        data.store.async_save.assert_called_once_with({
            "queue": [],
            "current_index": 0,
        })

    async def test_save_no_store(self) -> None:
        """Test save_queue does nothing without store."""
        data = NavidromeData(client=MagicMock(), store=None)
        # Should not raise
        await data.save_queue()


class TestLoadQueue:
    """Test load_queue method."""

    async def test_load_restores_queue(self) -> None:
        """Test load_queue restores queue from store."""
        tracks = [{"id": "tr-1", "title": "Track A"}]
        data = _make_data()
        data.store.async_load = AsyncMock(return_value={
            "queue": tracks,
            "current_index": 0,
        })

        await data.load_queue()

        assert data.queue == tracks
        assert data.current_index == 0

    async def test_load_empty_store(self) -> None:
        """Test load_queue with no stored data."""
        data = _make_data()
        data.store.async_load = AsyncMock(return_value=None)

        await data.load_queue()

        assert data.queue == []
        assert data.current_index == 0

    async def test_load_partial_data(self) -> None:
        """Test load_queue with missing fields."""
        data = _make_data()
        data.store.async_load = AsyncMock(return_value={"queue": []})

        await data.load_queue()

        assert data.queue == []
        assert data.current_index == 0

    async def test_load_no_store(self) -> None:
        """Test load_queue does nothing without store."""
        data = NavidromeData(client=MagicMock(), store=None)
        # Should not raise
        await data.load_queue()


class TestClearQueue:
    """Test clear_queue method."""

    async def test_clear_resets_queue_and_index(self) -> None:
        """Test clear_queue empties queue and resets index."""
        tracks = [{"id": "tr-1"}, {"id": "tr-2"}]
        data = _make_data(queue=tracks, current_index=1)

        await data.clear_queue()

        assert data.queue == []
        assert data.current_index == 0
        data.store.async_save.assert_called_once()

    async def test_clear_already_empty(self) -> None:
        """Test clear_queue on already empty queue."""
        data = _make_data()

        await data.clear_queue()

        assert data.queue == []
        assert data.current_index == 0
