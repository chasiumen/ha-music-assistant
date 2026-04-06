"""Constants for the Navidrome integration."""

from __future__ import annotations

import logging

DOMAIN = "navidrome"
LOGGER = logging.getLogger(__package__)

DEFAULT_PORT = 4533
CONF_VERIFY_SSL = "verify_ssl"
CONF_TARGET_PLAYER = "target_player"
CONF_SCROBBLE_ENABLED = "scrobble_enabled"

SUBSONIC_API_VERSION = "1.16.1"
SUBSONIC_CLIENT_NAME = "HomeAssistant"
