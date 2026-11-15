"""Shared entity helpers for the Navidrome integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import CONF_URL
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MANUFACTURER, MODEL

if TYPE_CHECKING:
    from . import NavidromeConfigEntry


def navidrome_device_info(entry: NavidromeConfigEntry) -> DeviceInfo:
    """Return the DeviceInfo shared by every Navidrome entity of an entry.

    sw_version is the Navidrome server version read at setup; the hourly
    refresh in __init__ keeps the device registry current after upgrades.
    """
    server_info = entry.runtime_data.server_info
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=entry.title,
        configuration_url=entry.data.get(CONF_URL),
        sw_version=server_info.server_version if server_info else None,
    )
