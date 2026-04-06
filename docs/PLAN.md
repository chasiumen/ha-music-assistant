# Implementation Plan

## Overview

Build a HACS custom component that integrates Navidrome music server with Home Assistant as a **media source**. This is the first Navidrome/Subsonic integration for HA — nothing exists in HA core or HACS.

## Architecture Decision

### Why media_source (not media_player)?

The Navidrome web UI handles all playback client-side:
- **Pause/Play**: HTML5 `<audio>` element — no server API
- **Shuffle**: Client-side Fisher-Yates algorithm in Redux — no server API
- **Repeat**: `navidrome-music-player` library loops locally — no server API
- **Queue**: Redux state in browser memory — no server API

The Subsonic Jukebox API exists for server-side playback (via MPV), but it's a separate mode — and its `stop` is actually a `pause` (calls `MPV.set("pause", true)`). Not what we need.

Since HA already has media players that handle playback, our integration is a **content provider** — browse, search, and resolve stream URLs from Navidrome's library.

### Component Roles

| Component | Role |
|---|---|
| `api.py` | Async Subsonic API client (aiohttp, no external deps) |
| `config_flow.py` | UI setup: URL + username + password + SSL option. Options flow for target player. |
| `media_source.py` | Browse library, resolve to stream URLs. Used by Media sidebar. |
| `media_player.py` | Voice search+play entity. Forwards playback, proxies controls, tracks queue. |
| `sensor.py` | Queue sensor exposing current playlist as track list attribute. |
| `__init__.py` | Setup, NavidromeData shared state, cover art proxy HTTP view. |

### Two Playback Paths

1. **Media sidebar** → user browses Navidrome via `media_source.py` → picks any speaker at play time
2. **Voice / Dashboard** → `media_player.py` searches Navidrome → forwards to configured target player

## Phases

### Phase 1: Foundation

**Files:** `const.py`, `api.py`, `config_flow.py`, `__init__.py`, `manifest.json`, `strings.json`

#### Subsonic API Client (`api.py`)

Auth: Token+salt per request — `token = MD5(password + salt)`, params `u`, `t`, `s`, `v=1.16.1`, `c=HomeAssistant`, `f=json`.

Methods:
- `ping()` — connectivity/auth check
- `search3(query)` — full-text search across songs, albums, artists
- `get_artists()` — all artists (ID3 format)
- `get_artist(id)` — artist with albums
- `get_album(id)` — album with songs
- `get_playlists()` / `get_playlist(id)` — playlist browsing
- `get_genres()` — genre listing
- `get_album_list2(type, size)` — curated lists (newest, random, frequent, starred, byGenre, byYear)
- `stream_url(id)` — build authenticated stream URL (no request)
- `cover_art_url(id, size)` — build cover art URL (no request)

Exceptions: `CannotConnect`, `AuthenticationFailed`, `NavidromeApiError`

#### Config Flow (`config_flow.py`)

- User step: URL, username, password
- Validates with `ping()`
- Unique ID: `host:port`
- Reauth flow for password changes

#### Setup (`__init__.py`)

- Creates `NavidromeClient` with `async_get_clientsession(hass)`
- Tests connection with `ping()`
- Stores client in `entry.runtime_data`
- `media_source.py` is auto-discovered (no platform forwarding needed)

### Phase 2: Media Source

**Files:** `media_source.py`

#### Browse Tree

```
Root (Navidrome)
├── Artists        → getArtists()
│   └── Artist     → getArtist(id) → albums
│       └── Album  → getAlbum(id) → songs (playable)
├── Albums         → getAlbumList2("alphabeticalByName")
│   └── Album      → songs (playable)
├── Playlists      → getPlaylists()
│   └── Playlist   → getPlaylist(id) → songs (playable)
├── Genres         → getGenres()
│   └── Genre      → getAlbumList2("byGenre") → albums
├── Recently Added → getAlbumList2("newest")
├── Most Played    → getAlbumList2("frequent")
└── Random         → getAlbumList2("random")
```

#### Content ID Scheme

`media-source://navidrome/{entry_id}/{type}/{navidrome_id}`

Examples:
- `media-source://navidrome/abc123/song/tr-456`
- `media-source://navidrome/abc123/album/al-789`
- `media-source://navidrome/abc123/playlist/pl-012`

#### Resolution

- Song → `PlayMedia(url=stream_url(id), mime_type="audio/mpeg")`
- Album → fetch album songs, resolve first song (or build M3U)
- Playlist → fetch playlist songs, resolve first song

### Phase 3: Voice Support (Media Player Wrapper)

**Files:** `media_player.py`

A lightweight `MediaPlayerEntity` that enables voice intents:
- Declares `SEARCH_MEDIA | PLAY_MEDIA | BROWSE_MEDIA` features
- `async_search_media()` calls Subsonic `search3`, returns `SearchMedia` results
- `async_play_media()` resolves stream URL, forwards to configured target player
- Playback controls (pause, next, volume) proxied to target player

This enables `HassMediaSearchAndPlay` intent — "Play Beatles on navidrome" works via:
```
Wyoming STT → OpenAI agent → HassMediaSearchAndPlay intent
→ matches media_player.navidrome (SEARCH_MEDIA | PLAY_MEDIA)
→ search3("Beatles") → play first result on target player
```

Config: user selects a "Target media player" entity during setup.

### Phase 4: HACS Packaging

**Files:** `hacs.json`, `manifest.json`, `translations/en.json`

### Phase 5: Tests

**Files:** `tests/components/navidrome/`

- `test_config_flow.py` — success, cannot_connect, invalid_auth, reauth
- `test_init.py` — setup, auth fail, connect fail, unload
- `test_media_source.py` — browse root, categories, drill-down, resolve
- `test_api.py` — auth token generation, request building, error handling

## Key Reference Files

### HA Core Patterns

| File | Why |
|---|---|
| `homeassistant/components/jellyfin/media_source.py` | Best reference — self-hosted media server media_source |
| `homeassistant/components/media_source/__init__.py` | MediaSource base class, auto-discovery mechanism |
| `homeassistant/components/media_source/models.py` | PlayMedia, BrowseMediaSource, MediaSourceItem |
| `homeassistant/components/media_player/intent.py` | HassMediaSearchAndPlay — voice search+play intent |
| `homeassistant/components/immich/media_source.py` | Platinum quality media_source example |
| `homeassistant/components/radio_browser/media_source.py` | Streaming content media_source |
| `homeassistant/components/music_assistant/media_player.py` | Media player with search+browse pattern |

### Navidrome API Reference

| File | What |
|---|---|
| `server/subsonic/api.go` | API routing, all endpoint registrations |
| `server/subsonic/searching.go` | search2/search3 — full-text search |
| `server/subsonic/browsing.go` | getArtists, getArtist, getAlbum, getSong, getGenres |
| `server/subsonic/playlists.go` | getPlaylists, getPlaylist, createPlaylist, updatePlaylist |
| `server/subsonic/album_lists.go` | getAlbumList2 (newest, random, frequent, starred, byGenre, byYear) |
| `server/subsonic/media_retrieval.go` | stream, getCoverArt, download, getLyrics |
| `server/subsonic/responses/responses.go` | All response data structures (Child, AlbumID3, ArtistID3, etc.) |
| `server/subsonic/jukebox.go` | Jukebox API (not used, but documents server-side playback) |
| `core/playback/mpv/track.go` | MPV backend — Pause() is `set("pause", true)`, not destructive stop |
| `ui/src/audioplayer/Player.jsx` | Web UI player — all playback is client-side HTML5 audio |
| `ui/src/actions/player.js` | Shuffle is client-side Fisher-Yates, not a server API |
| `ui/src/reducers/playerReducer.js` | Repeat/shuffle mode stored in Redux, not persisted server-side |

## Navidrome Subsonic API Quick Reference

### Authentication

Every request includes: `u` (username), `t` (MD5 of password+salt), `s` (random salt), `v=1.16.1`, `c=HomeAssistant`, `f=json`

### Key Endpoints

```
GET /rest/ping                    → health check
GET /rest/search3                 → search (query, songCount, albumCount, artistCount)
GET /rest/getArtists              → all artists
GET /rest/getArtist?id=           → artist + albums
GET /rest/getAlbum?id=            → album + songs
GET /rest/getPlaylists            → all playlists
GET /rest/getPlaylist?id=         → playlist + songs
GET /rest/getGenres               → all genres
GET /rest/getAlbumList2?type=     → curated lists (newest|random|frequent|starred|byGenre|byYear)
GET /rest/getSong?id=             → single song metadata
GET /rest/stream?id=              → audio stream
GET /rest/getCoverArt?id=&size=   → album art
GET /rest/scrobble?id=&submission= → scrobble (now playing / listened)
```

### Response Format

```json
{
  "subsonic-response": {
    "status": "ok",
    "version": "1.16.1",
    "type": "navidrome",
    "openSubsonic": true,
    ...response data...
  }
}
```

### Search3 Response Shape

```json
{
  "searchResult3": {
    "artist": [{"id": "...", "name": "...", "albumCount": 5, "coverArt": "..."}],
    "album": [{"id": "...", "name": "...", "artist": "...", "songCount": 12, "coverArt": "..."}],
    "song": [{"id": "...", "title": "...", "artist": "...", "album": "...", "duration": 240, "coverArt": "..."}]
  }
}
```
