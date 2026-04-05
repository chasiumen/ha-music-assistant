# Navidrome Integration for Home Assistant

A [HACS](https://hacs.xyz/) custom component that integrates [Navidrome](https://www.navidrome.org/) music server with Home Assistant as a **media source**.

Navidrome provides the music library (browse, search, stream URLs); your existing HA media players (Sonos, Chromecast, MPD, etc.) handle actual playback — including pause, play, next, shuffle, repeat, and volume.

## Architecture

```
User (voice/UI) --> HA Media Browser / Voice Intent
  --> Navidrome media_source (browse, search, resolve stream URL)
  --> Target media_player (Sonos, Chromecast, MPD, etc.)
  --> Audio output
```

- **Navidrome integration** = content provider (media_source)
- **Existing HA media_player** = playback controller (pause, play, next, shuffle, repeat, volume)
- **Subsonic API** = library access (search, browse, stream)
- No Jukebox API needed — HA is the client, not Navidrome's server-side player

### Why media_source, not media_player?

Navidrome's web UI handles all playback client-side (HTML5 `<audio>` element). Shuffle, repeat, and pause are all browser-side JavaScript — no server API for these. The Subsonic Jukebox API exists for server-side playback but is a separate mode.

Since HA already has media players (Sonos, Chromecast, etc.) that handle playback perfectly, this integration focuses on being a **music library provider** — just like Jellyfin, Plex, and Immich integrations in HA.

## Features

- Browse your Navidrome library: Artists, Albums, Playlists, Genres
- Browse curated lists: Recently Added, Most Played, Random
- Search songs, albums, and artists
- Stream audio to any HA media player
- Album art thumbnails in the media browser
- Voice control via Wyoming STT + OpenAI conversation agent

## Installation

### HACS (Recommended)

1. Add this repository as a custom repository in HACS
2. Search for "Navidrome" and install
3. Restart Home Assistant
4. Go to **Settings > Devices & Services > Add Integration > Navidrome**
5. Enter your Navidrome server URL, username, and password

### Manual

1. Copy `custom_components/navidrome/` to your HA `config/custom_components/` directory
2. Restart Home Assistant
3. Add the integration via the UI

## Configuration

| Field | Description | Example |
|-------|-------------|---------|
| URL | Navidrome server URL | `http://navidrome.local:4533` |
| Username | Navidrome username | `admin` |
| Password | Navidrome password | `***` |

## Usage

### Media Browser

After setup, open any media player's media browser in the HA UI. You'll see **Navidrome** as a media source. Browse by:
- Artists > Artist > Albums > Songs
- Albums > Album > Songs
- Playlists > Playlist > Songs
- Genres > Genre > Albums
- Recently Added / Most Played / Random

Click any song to play it on the selected media player.

### Voice Control

With the media_player wrapper enabled and a voice pipeline configured (Wyoming STT + OpenAI conversation agent):

| Voice Command | What Happens |
|---|---|
| "Play Beatles on navidrome" | Searches Navidrome, plays first result on target player |
| "Pause the music" | Pauses the target media player |
| "Next song" | Skips to next track on the target player |
| "Set volume to 50%" | Adjusts target player volume |
| "Shuffle" / "Repeat" | Handled by the target media player |

## Development

### Prerequisites

- Home Assistant core source (for reference): `/path/to/core/`
- Navidrome source (for API reference): `/path/to/navidrome/`

### Project Structure

```
ha-music-assistant/
├── custom_components/
│   └── navidrome/
│       ├── __init__.py           # Setup, config entry lifecycle
│       ├── api.py                # Async Subsonic API client (aiohttp)
│       ├── config_flow.py        # Config flow: URL + credentials
│       ├── const.py              # Domain, constants
│       ├── media_source.py       # MediaSource: browse + search + resolve
│       ├── media_player.py       # Voice support wrapper (optional)
│       ├── manifest.json
│       ├── strings.json
│       └── translations/
│           └── en.json
├── tests/
│   └── components/
│       └── navidrome/
├── hacs.json
└── README.md
```

### Key Navidrome APIs Used

| Endpoint | Purpose |
|---|---|
| `ping` | Connection/auth validation |
| `search3` | Full-text search (songs, albums, artists) |
| `getArtists` | List all artists |
| `getArtist` | Artist detail with albums |
| `getAlbum` | Album detail with songs |
| `getPlaylists` / `getPlaylist` | Playlist browsing |
| `getGenres` | Genre listing |
| `getAlbumList2` | Curated lists (newest, random, frequent, etc.) |
| `stream` | Audio streaming URL |
| `getCoverArt` | Album art URL |

All via Subsonic API with token+salt authentication.

## License

MIT
