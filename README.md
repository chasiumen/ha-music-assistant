# Navidrome Integration for Home Assistant

A [HACS](https://hacs.xyz/) custom component that integrates [Navidrome](https://www.navidrome.org/) music server with Home Assistant.

Browse your Navidrome music library, search for songs/albums/artists, and stream audio to any HA media player (Sonos, Chromecast, MPD, etc.) — with full voice control support.

## Architecture

```
User (voice/UI) --> HA Media Browser / Voice Intent
  --> Navidrome integration (browse, search, resolve stream URL)
  --> Target media_player (Sonos, Chromecast, MPD, etc.)
  --> Audio output
```

The integration provides two components:

- **Media Source** — makes your Navidrome library browsable from any HA media player's media browser
- **Media Player entity** — enables voice search and play via HA's built-in `HassMediaSearchAndPlay` intent

Playback controls (pause, play, next, shuffle, repeat, volume) are handled by the target media player — Navidrome only provides the music content.

### Why this approach?

Navidrome's web UI handles all playback client-side (HTML5 `<audio>` element). Shuffle, repeat, and pause are browser-side JavaScript with no server API. Since HA already has media players that handle playback, this integration focuses on being a **music library provider** — just like Jellyfin and Plex integrations in HA.

## Features

- Browse your Navidrome library: Artists, Albums, Playlists, Genres
- Browse curated lists: Recently Added, Most Played, Random
- Search songs, albums, and artists via voice or UI
- Stream audio to any HA media player
- Album art thumbnails in the media browser
- Voice control via Wyoming STT + OpenAI conversation agent
- Full playlist and album playback (all tracks enqueued, not just the first)
- Album art, title, artist, and duration shown in the media player card
- Queue sensor with track list for dashboard display
- Playback controls (play/pause/stop/next/prev/volume) proxied to target player
- Cover art served via local proxy (avoids SSL issues with self-signed certs)
- Queue persists across HA restarts
- Clear queue service (`navidrome.clear_queue`) and card button
- Search card — search songs, albums, artists from the dashboard
- Playlist management — save queue as playlist, add songs to playlists
- Drag-to-reorder tracks in the queue card
- Optional scrobbling — sends "now playing" to Navidrome for Discord status, Last.fm, etc.
- Re-authentication flow when credentials change
- Subsonic API token+salt authentication (passwords never sent in plaintext)

## Installation

### HACS (Recommended)

1. Open HACS in your HA instance
2. Click the three dots menu > **Custom repositories**
3. Add `https://github.com/chasiumen/ha-music-assistant` with category **Integration**
4. Search for "Navidrome" and install
5. Restart Home Assistant
6. Go to **Settings > Devices & Services > Add Integration > Navidrome**
7. Enter your Navidrome server URL, username, and password

### Manual

1. Copy `custom_components/navidrome/` to your HA `config/custom_components/` directory
2. Restart Home Assistant
3. Add the integration via **Settings > Devices & Services > Add Integration > Navidrome**

## Configuration

### Initial Setup

| Field | Description | Example |
|-------|-------------|---------|
| URL | Navidrome server URL | `https://navidrome.example.com:4533` |
| Username | Navidrome username | `admin` |
| Password | Navidrome password | `***` |
| Verify SSL | Verify SSL certificate (disable for self-signed certs) | `true` |

### Options (after setup)

Go to **Settings > Devices & Services > Navidrome > Configure** to set:

| Option | Description |
|--------|-------------|
| Target media player | The media player to play audio on (e.g., a Sonos speaker, Chromecast, or browser player). Required for voice control and dashboard playback. |
| Enable scrobbling | Send "now playing" status to Navidrome when music plays. Enables Discord status, Last.fm, and other scrobble-based plugins. Off by default. |

## Usage

### Media Browser (plays on any speaker)

Go to **Media** in the HA sidebar. You'll see **Navidrome** as a media source. Browse by:

- **Artists** > Artist > Albums > Songs
- **Albums** > Album > Songs
- **Playlists** > Playlist > Songs
- **Genres** > Genre > Albums
- **Recently Added** / **Most Played** / **Random**

Select a song, then choose which player to use — **"This Browser"** for local playback through your computer's speakers, or any other media player (Sonos, Chromecast, etc.).

### Dashboard Playback (plays on target player)

Add the `media_player.navidrome` entity to your dashboard. When you browse and play from the dashboard card, audio is sent to the **target media player** you configured in the integration options.

Recommended dashboard setup with the built-in queue card:

```yaml
type: vertical-stack
cards:
  - type: media-control
    entity: media_player.navidrome_ryosukemorino_com
  - type: custom:navidrome-search-card
    entity: media_player.navidrome_ryosukemorino_com
  - type: custom:navidrome-queue-card
    entity: sensor.navidrome_ryosukemorino_com_queue
    max_height: 400
```

### Search Card

The search card lets you find and play music without browsing:

```yaml
type: custom:navidrome-search-card
entity: media_player.navidrome_ryosukemorino_com
```

- Type to search — results appear grouped by Songs, Albums, Artists
- Click ▶ to play immediately
- Click ➕ to add to the current queue
- Click 💾 to save to a Navidrome playlist

### Services

| Service | Description |
|---|---|
| `navidrome.clear_queue` | Clear the playback queue and stop player |
| `navidrome.save_queue_as_playlist` | Save current queue as a new Navidrome playlist (param: `name`) |
| `navidrome.add_to_playlist` | Add a song to an existing playlist (params: `playlist_id`, `song_id`) |
| `navidrome.add_to_queue` | Append a song to the queue (param: `song_id`) |
| `navidrome.reorder_queue` | Move a track in the queue (params: `from_index`, `to_index`) |

The queue card is bundled with the integration — no extra HACS installations needed. It shows a scrollable list of tracks with the current track highlighted. Click any track to play it. The list auto-scrolls to the current track.

Card options:

| Option | Default | Description |
|--------|---------|-------------|
| `entity` | (required) | Queue sensor entity ID |
| `player_entity` | (auto-detected) | Navidrome media player entity for click-to-play |
| `max_height` | `400` | Maximum height in pixels (scrollable) |
| `title` | `Queue` | Card header text |

Search card options:

| Option | Default | Description |
|--------|---------|-------------|
| `entity` | (required) | Navidrome media player entity ID |
| `max_songs` | `20` | Max songs to display in results |
| `max_albums` | `10` | Max albums to display in results |
| `max_artists` | `5` | Max artists to display in results |
| `max_height` | `500` | Max height in pixels (scrollable) |
| `debounce_ms` | `400` | Search delay in milliseconds |

### Voice Control (plays on target player)

With a voice pipeline configured (Wyoming STT + OpenAI conversation agent), the integration registers a `media_player.navidrome` entity that supports voice search:

| Voice Command | What Happens |
|---|---|
| "Play Beatles on navidrome" | Searches Navidrome library, plays first result |
| "Play Abbey Road on navidrome" | Searches for the album, plays it |
| "Pause the music" | Pauses the target media player |
| "Next song" | Skips to next track on the target player |
| "Set volume to 50%" | Adjusts target player volume |
| "Shuffle" / "Repeat" | Handled by the target media player |

The voice search works via HA's built-in `HassMediaSearchAndPlay` intent. The Navidrome entity declares `SEARCH_MEDIA` and `PLAY_MEDIA` features, which HA's intent system matches automatically.

## Development

### Project Structure

```
ha-music-assistant/
├── custom_components/
│   └── navidrome/
│       ├── __init__.py           # Integration setup, config entry lifecycle
│       ├── api.py                # Async Subsonic API client (aiohttp, no external deps)
│       ├── config_flow.py        # Config flow: URL + credentials + reauth
│       ├── const.py              # Domain, logger, constants
│       ├── media_source.py       # MediaSource: browse library + resolve stream URLs
│       ├── media_player.py       # Media player entity: search, play, queue, proxy controls
│       ├── sensor.py             # Queue sensor for dashboard display
│       ├── services.yaml         # Service definitions
│       ├── manifest.json         # Integration manifest
│       ├── strings.json          # UI strings
│       └── translations/
│           └── en.json           # English translations
├── tests/
│   └── components/
│       └── navidrome/
│           ├── conftest.py       # Test fixtures, mock API client
│           ├── test_api.py       # API client tests (auth, endpoints, errors)
│           ├── test_config_flow.py  # Config flow tests
│           ├── test_media_source.py # Media source browse + resolve tests
│           ├── test_media_player.py # Media player controls, queue, scrobble tests
│           ├── test_sensor.py       # Queue sensor tests
│           └── test_queue_persistence.py # Queue save/load/clear tests
├── docs/
│   └── PLAN.md                   # Implementation plan and API reference
├── hacs.json                     # HACS configuration
└── README.md
```

### Key Navidrome APIs Used

All endpoints use the Subsonic REST API with token+salt authentication (`/rest/<endpoint>?u=...&t=...&s=...&f=json`).

| Endpoint | Purpose |
|---|---|
| `ping` | Connection and auth validation |
| `search3` | Full-text search across songs, albums, artists |
| `getArtists` | List all artists (ID3 format) |
| `getArtist` | Artist detail with albums |
| `getAlbum` | Album detail with songs |
| `getPlaylists` / `getPlaylist` | Playlist browsing |
| `getGenres` | Genre listing |
| `getAlbumList2` | Curated lists (newest, random, frequent, starred, byGenre, byYear) |
| `stream` | Audio streaming (builds authenticated URL) |
| `getCoverArt` | Album art thumbnails (builds authenticated URL) |

### Running Tests

```bash
pytest tests/components/navidrome/ -v
```

## Requirements

- Home Assistant 2024.1.0 or later
- Navidrome server with Subsonic API enabled (enabled by default)
- A media player configured in HA (Sonos, Chromecast, MPD, etc.) for audio output

## License

MIT
