"""Tests for the Navidrome queue sensor."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.navidrome import NavidromeData
from custom_components.navidrome.sensor import NavidromeQueueSensor


MOCK_TRACKS = [
    {
        "id": "tr-1",
        "url": "http://navidrome.local:4533/rest/stream?id=tr-1",
        "title": "Come Together",
        "artist": "The Beatles",
        "album": "Abbey Road",
        "duration": 259,
        "coverArt": "al-1",
    },
    {
        "id": "tr-2",
        "url": "http://navidrome.local:4533/rest/stream?id=tr-2",
        "title": "Something",
        "artist": "The Beatles",
        "album": "Abbey Road",
        "duration": 182,
        "coverArt": "al-1",
    },
    {
        "id": "tr-3",
        "url": "http://navidrome.local:4533/rest/stream?id=tr-3",
        "title": "Here Comes The Sun",
        "artist": "The Beatles",
        "album": "Abbey Road",
        "duration": 185,
        "coverArt": "al-1",
    },
]


def _make_sensor(queue: list = None, current_index: int = 0) -> NavidromeQueueSensor:
    """Create a NavidromeQueueSensor with mock data."""
    mock_client = MagicMock()
    data = NavidromeData(client=mock_client, queue=queue or [], current_index=current_index)

    mock_entry = MagicMock()
    mock_entry.entry_id = "test_entry_123"
    mock_entry.runtime_data = data
    mock_entry.data = {"url": "http://navidrome.local:4533"}
    mock_entry.title = "Navidrome (test)"

    return NavidromeQueueSensor(mock_entry)


class TestNavidromeQueueSensor:
    """Test the Navidrome queue sensor."""

    def test_empty_queue_value(self) -> None:
        """Test native_value when queue is empty."""
        sensor = _make_sensor()
        assert sensor.native_value == "Empty"

    def test_queue_value_with_tracks(self) -> None:
        """Test native_value with tracks in queue."""
        sensor = _make_sensor(queue=MOCK_TRACKS, current_index=0)
        assert sensor.native_value == "1/3"

    def test_queue_value_second_track(self) -> None:
        """Test native_value when second track is current."""
        sensor = _make_sensor(queue=MOCK_TRACKS, current_index=1)
        assert sensor.native_value == "2/3"

    def test_empty_queue_attributes(self) -> None:
        """Test attributes when queue is empty."""
        sensor = _make_sensor()
        attrs = sensor.extra_state_attributes
        assert attrs["tracks"] == []
        assert attrs["total_tracks"] == 0
        assert attrs["current_index"] == 0

    def test_queue_attributes_with_tracks(self) -> None:
        """Test attributes with tracks in queue."""
        sensor = _make_sensor(queue=MOCK_TRACKS, current_index=1)
        attrs = sensor.extra_state_attributes

        assert attrs["total_tracks"] == 3
        assert attrs["current_index"] == 2  # 1-based

        tracks = attrs["tracks"]
        assert len(tracks) == 3

        assert tracks[0]["index"] == 1
        assert tracks[0]["song_id"] == "tr-1"
        assert tracks[0]["title"] == "Come Together"
        assert tracks[0]["artist"] == "The Beatles"
        assert tracks[0]["album"] == "Abbey Road"
        assert tracks[0]["duration"] == 259
        assert tracks[0]["is_current"] is False

        assert tracks[1]["index"] == 2
        assert tracks[1]["title"] == "Something"
        assert tracks[1]["is_current"] is True

        assert tracks[2]["index"] == 3
        assert tracks[2]["title"] == "Here Comes The Sun"
        assert tracks[2]["is_current"] is False

    def test_queue_attributes_missing_metadata(self) -> None:
        """Test attributes with tracks missing some metadata."""
        tracks = [{"id": "tr-1", "url": "http://example.com/stream"}]
        sensor = _make_sensor(queue=tracks, current_index=0)
        attrs = sensor.extra_state_attributes

        assert attrs["tracks"][0]["title"] == "Unknown"
        assert attrs["tracks"][0]["artist"] == "Unknown"
        assert attrs["tracks"][0]["album"] == ""
        assert attrs["tracks"][0]["duration"] is None

    def test_unique_id(self) -> None:
        """Test unique_id is based on entry_id."""
        sensor = _make_sensor()
        assert sensor.unique_id == "test_entry_123_queue"

    def test_icon(self) -> None:
        """Test sensor icon."""
        sensor = _make_sensor()
        assert sensor.icon == "mdi:playlist-music"

    def test_name(self) -> None:
        """Test sensor name."""
        sensor = _make_sensor()
        assert sensor.name == "Queue"

    def test_has_async_added_to_hass(self) -> None:
        """Test sensor has async_added_to_hass for dispatcher subscription."""
        sensor = _make_sensor()
        assert hasattr(sensor, "async_added_to_hass")
        assert callable(sensor.async_added_to_hass)
