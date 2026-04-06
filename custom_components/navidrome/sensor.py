"""Sensor platform for the Navidrome integration.

Provides a queue sensor that shows the current playlist/queue.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NavidromeConfigEntry, NavidromeData
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NavidromeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Navidrome queue sensor."""
    async_add_entities([NavidromeQueueSensor(entry)])


class NavidromeQueueSensor(SensorEntity):
    """Sensor that exposes the current Navidrome playback queue."""

    _attr_has_entity_name = True
    _attr_name = "Queue"
    _attr_icon = "mdi:playlist-music"
    _unrecorded_attributes = frozenset({"tracks"})

    def __init__(self, entry: NavidromeConfigEntry) -> None:
        """Initialize the queue sensor."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_queue"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="Navidrome",
            model="Music Server",
            name=entry.title,
            configuration_url=entry.data.get(CONF_URL),
        )

    @property
    def data(self) -> NavidromeData:
        """Return the shared data."""
        return self._entry.runtime_data

    @property
    def native_value(self) -> str:
        """Return the number of tracks in the queue."""
        count = len(self.data.queue)
        if count == 0:
            return "Empty"
        current = self.data.current_index + 1
        return f"{current}/{count}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the queue as an attribute."""
        tracks = []
        for i, track in enumerate(self.data.queue):
            tracks.append({
                "index": i + 1,
                "song_id": track.get("id"),
                "title": track.get("title", "Unknown"),
                "artist": track.get("artist", "Unknown"),
                "album": track.get("album", ""),
                "duration": track.get("duration"),
                "is_current": i == self.data.current_index,
            })
        return {
            "tracks": tracks,
            "total_tracks": len(self.data.queue),
            "current_index": self.data.current_index + 1 if self.data.queue else 0,
        }
