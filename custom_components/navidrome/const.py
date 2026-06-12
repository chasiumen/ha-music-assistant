"""Constants for the Navidrome integration."""

from __future__ import annotations

import logging

DOMAIN = "navidrome"
LOGGER = logging.getLogger(__package__)

DEFAULT_PORT = 4533
CONF_VERIFY_SSL = "verify_ssl"
CONF_TARGET_PLAYER = "target_player"
CONF_SCROBBLE_ENABLED = "scrobble_enabled"

SIGNAL_QUEUE_UPDATED = f"{DOMAIN}_queue_updated"

SUBSONIC_API_VERSION = "1.16.1"
SUBSONIC_CLIENT_NAME = "HomeAssistant"

TARGET_STATE_GRACE_SECONDS = 10.0
PLAYLIST_CACHE_TTL_SECONDS = 30.0
