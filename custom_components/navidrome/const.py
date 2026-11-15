"""Constants for the Navidrome integration.

Values here are the single source of truth. User-tunable values have a
CONF_* key and a DEFAULT_*; the options flow (Settings → Navidrome →
Configure) stores overrides in the config entry, and code reads them with
``entry.options.get(CONF_X, DEFAULT_X)`` so an unset option falls back to the
default below.
"""

from __future__ import annotations

from datetime import timedelta
import logging

DOMAIN = "navidrome"
LOGGER = logging.getLogger(__package__)

# -- Connection / config entry data --
DEFAULT_PORT = 4533
CONF_VERIFY_SSL = "verify_ssl"

# -- Options (Settings → Navidrome → Configure) --
CONF_TARGET_PLAYER = "target_player"
CONF_SCROBBLE_ENABLED = "scrobble_enabled"
CONF_SEARCH_RESULT_LIMIT = "search_result_limit"
CONF_PLAYLIST_CACHE_TTL = "playlist_cache_ttl"
CONF_CONTROL_GRACE_SECONDS = "control_grace_seconds"

DEFAULT_SCROBBLE_ENABLED = False
# Max songs/albums/artists fetched per search; the cards trim what they show.
DEFAULT_SEARCH_RESULT_LIMIT = 500
# How long the playlist list used for playlist search is cached.
DEFAULT_PLAYLIST_CACHE_TTL = 30
# After play/pause/stop/repeat, ignore contradicting target-player updates for
# this long so stale events don't flip the UI back.
DEFAULT_CONTROL_GRACE_SECONDS = 10

# (min, max) bounds enforced by the options flow
SEARCH_RESULT_LIMIT_RANGE = (10, 1000)
PLAYLIST_CACHE_TTL_RANGE = (0, 3600)
CONTROL_GRACE_SECONDS_RANGE = (0, 60)

# -- Subsonic API --
SUBSONIC_API_VERSION = "1.16.1"
SUBSONIC_CLIENT_NAME = "HomeAssistant"
API_TIMEOUT_SECONDS = 30
API_DEFAULT_RESULT_COUNT = 20
DEFAULT_COVER_ART_SIZE = 300
# Re-ping the server this often so a Navidrome upgrade shows up without an
# HA restart (device software version + server version sensor).
SERVER_INFO_REFRESH_INTERVAL = timedelta(hours=1)

# -- Media IDs: media-source://navidrome/<type>/<id> --
MEDIA_SOURCE_PREFIX = f"media-source://{DOMAIN}"
PREFIX_ARTIST = "artist"
PREFIX_ALBUM = "album"
PREFIX_SONG = "song"
PREFIX_PLAYLIST = "playlist"
PREFIX_GENRE = "genre"

# Fallback stream content type when Navidrome doesn't report one
DEFAULT_MIME_TYPE = "audio/mpeg"

# Albums listed per media-browser page (recent, random, genre, ...)
BROWSE_ALBUM_LIST_SIZE = 50

# -- Cover art proxy (avoids SSL / auth issues in the browser) --
COVER_ART_PROXY_PATH = f"/api/{DOMAIN}/cover_art"
COVER_ART_CACHE_MAX_AGE = 86400  # seconds

# -- Device registry --
MANUFACTURER = "Navidrome"
MODEL = "Music Server"

# -- Frontend cards (served from ./www, cache-busted by content hash) --
FRONTEND_URL_BASE = f"/{DOMAIN}"
FRONTEND_CARDS = ("navidrome-queue-card.js", "navidrome-search-card.js")

# -- Services --
SERVICE_CLEAR_QUEUE = "clear_queue"
SERVICE_SAVE_QUEUE_AS_PLAYLIST = "save_queue_as_playlist"
SERVICE_ADD_TO_PLAYLIST = "add_to_playlist"
SERVICE_ADD_TO_QUEUE = "add_to_queue"
SERVICE_REORDER_QUEUE = "reorder_queue"
SERVICE_REMOVE_FROM_QUEUE = "remove_from_queue"

# -- Dispatcher signals (suffixed with _<entry_id>) --
SIGNAL_QUEUE_UPDATED = f"{DOMAIN}_queue_updated"
SIGNAL_SERVER_INFO_UPDATED = f"{DOMAIN}_server_info_updated"
# Ask the media player to play the queue from an index (arg: int). Sent when
# the playing track is removed; an index past the end means "stop".
SIGNAL_PLAY_QUEUE_INDEX = f"{DOMAIN}_play_queue_index"
