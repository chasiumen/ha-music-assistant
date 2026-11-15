"""Sensor platform for the Navidrome integration.

Provides a queue sensor that shows the current playlist/queue, and a
diagnostic sensor with the Navidrome server version.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NavidromeConfigEntry, NavidromeData
from .const import SIGNAL_QUEUE_UPDATED, SIGNAL_SERVER_INFO_UPDATED
from .entity import navidrome_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NavidromeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Navidrome sensors."""
    async_add_entities(
        [NavidromeQueueSensor(entry), NavidromeServerVersionSensor(entry)]
    )


class NavidromeServerVersionSensor(SensorEntity):
    """Diagnostic sensor with the Navidrome server version.

    State is the version number (e.g. "0.53.3"); the build, server type,
    Subsonic API version and OpenSubsonic support are attributes. Updated at
    setup and by the hourly refresh in __init__ (via dispatcher), so it
    doesn't poll.
    """

    _attr_has_entity_name = True
    _attr_name = "Server version"
    _attr_icon = "mdi:information-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, entry: NavidromeConfigEntry) -> None:
        """Initialize the server version sensor."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_server_version"
        self._attr_device_info = navidrome_device_info(entry)

    async def async_added_to_hass(self) -> None:
        """Subscribe to server info refreshes."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_SERVER_INFO_UPDATED}_{self._entry.entry_id}",
                self.async_write_ha_state,
            )
        )

    @property
    def native_value(self) -> str | None:
        """Return the server version number."""
        info = self._entry.runtime_data.server_info
        return info.version if info else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return build, server type and API details."""
        info = self._entry.runtime_data.server_info
        if not info:
            return {}
        return {
            "build": info.build,
            "server_type": info.server_type,
            "api_version": info.api_version,
            "open_subsonic": info.open_subsonic,
        }


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
        self._attr_device_info = navidrome_device_info(entry)

    async def async_added_to_hass(self) -> None:
        """Subscribe to queue update signals."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_QUEUE_UPDATED}_{self._entry.entry_id}",
                self.async_write_ha_state,
            )
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
