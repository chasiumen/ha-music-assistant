# Plan: Repeat Buttons, Playlist Search, Control-Delay Fix + Code Issue Report

Status: approved plan, not yet implemented (2026-06-11)

## Context

Setup (verified live): Navidrome custom integration (HA) → proxies playback to target player `fvm-win10` = a **Music Assistant** snapcast player → **external snapserver addon** (`ha-addon-snapserver`, host `24c8c63c-snapserver`) → `snapclient.exe` on a Windows 11 machine (latency 0, snapcast 0.35).

Three asks:
1. Loop/repeat buttons (single song + whole playlist) with an indicator — **feasible** (target MA entity natively supports `repeat_set` off/one/all).
2. Search box should also find playlists — **feasible & easy** (`api.get_playlists()` already exists; playlist playback already implemented).
3. Fix ~1 min control delay (pause/next/prev after playback starts) — **root cause found** (below); fix is an MA setting + integration hardening.

## Root cause of the ~1 minute control delay (verified in MA source)

- MA's snapcast player derives its state **only from the snapserver stream status**: `status == "idle" → IDLE else PLAYING` (`music_assistant/providers/snapcast/player.py`).
- When playback stops feeding audio (pause/stop/track end), snapserver keeps the stream status `playing` until **`idle_threshold` ms of silence** pass. MA creates its streams with `idle_threshold=60000` (`DEFAULT_SNAPSTREAM_IDLE_THRESHOLD = 60000` in `constants.py`) — confirmed live on the running snapserver (stream `Music Assistant - ma74563c4f1317`, URI contains `idle_threshold=60000`).
- HA's MA entity state = `player.playback_state` directly. So for up to **60 s** after pause, the MA entity reports stale `playing`; state-gated commands (resume etc.) misbehave, and the Navidrome entity's state listener (`_handle_target_state_change`) overwrites its optimistic `paused` back to `playing` → UI looks like the command "didn't work" for ~1 min.
- Aggravator (scales with playlist size): the integration enqueues every remaining track **one-by-one with sequential `blocking=True` service calls** in the foreground (`media_player.py:372-386`, `:553-565`; `__init__.py:239-261`). A jump/reorder also stops + clears + re-enqueues everything — drag-reorder even **restarts the currently playing track**.

### Fix part 0 — no-code test (do first)
In MA UI → Settings → Player providers → Snapcast → *Show advanced settings* → set **stream idle threshold 60000 → 10000** (it's `CONF_STREAM_IDLE_THRESHOLD`), save, then test pause/resume/next. Expect stale-state window to drop 60 s → 10 s. Don't go too low: between-track ffmpeg restarts + remote Navidrome fetches create real silence gaps; <5000 risks MA mistaking a track transition for "stopped".

## Code issues found (review report)

### ha-music-assistant
| # | Issue | Where | Action |
|---|-------|-------|--------|
| 1 | Foreground blocking enqueue storms; controls queue behind them | `media_player.py:372-386,553-565`, `__init__.py:239-261` | **Fix (this plan)** |
| 2 | Drag-reorder stops + restarts current track | `__init__.py:220-261` | **Fix (this plan)** |
| 3 | Target stale-state flapping overwrites optimistic state | `media_player.py:107-142` | **Fix (this plan)** |
| 4 | XSS / broken rendering: titles, artists, error messages interpolated into `innerHTML` unescaped | both cards | **Fix (this plan)** |
| 5 | Changing target player in options never rebinds the state listener (needs reload) | `media_player.py:93-105` | Optional small fix |
| 6 | `buffering` target state maps to IDLE | `media_player.py:116-121` | Fix in passing |
| 7 | Search card "add to playlist" only offers New Playlist (TODO at `navidrome-search-card.js:410`); saves whole queue, not the song | search card | Report only (separate feature) |
| 8 | Cover-art proxy `requires_auth=False` (needed for `<img>`); silent failure paths; service handlers bound to first config entry | `__init__.py` | Report only |
| 9 | README documents `max_height` for queue card; card uses `max_visible` | README:116 | Fix in passing |

### ha-addon-snapserver
| # | Issue | Where | Action |
|---|-------|-------|--------|
| 1 | `[tcp-control]` / `[tcp-streaming]` are **not valid snapserver sections** (valid: `[tcp]`, `[stream]`); works today only because defaults happen to be enabled | `snapserver/run.sh:47-55` | **Fix (this plan)** |
| 2 | `buffer_ms: int` unbounded in schema (HA number entity caps 500–5000, addon page allows anything) | `snapserver/config.yaml:35` | **Fix: `int(500,10000)`** |
| 3 | control.py: MA unix socket has no timeout; malformed JSON-RPC (`request["id"]`, `method.rsplit`) can crash the plugin; failed sends silently dropped; fixed 2 s reconnect | `snapserver/plug-ins/control.py:92-110,205,334-339` | Optional hardening |
| 4 | Snapweb on by default, all services bind 0.0.0.0 (host_network) | `config.yaml` | Report only (documented) |

## Implementation

### Phase 1 — Integration backend (`custom_components/navidrome/`)

**`__init__.py` — NavidromeData infra**
- New fields: `repeat_mode: str = "off"`, `queue_dirty: bool = False`, `enqueue_task: asyncio.Task | None`, `target_lock: asyncio.Lock`.
- New methods: `async_start_enqueue(target, start_index)` / `async_cancel_enqueue()` / `_enqueue_worker` — worker iterates the **live** queue list from `start_index`, each per-track `play_media {enqueue: add}` call wrapped in `async with target_lock` + per-track `except Exception` (never swallow `CancelledError`). Persist `repeat_mode`/`queue_dirty` in `save_queue`/`load_queue` (additive keys, `.get` defaults). Cancel worker in `async_unload_entry`.
- Cancel the worker **only** on tail-invalidating actions (new play, jump, reorder, clear, unload) — *not* on pause/next/prev; those just take the lock (wait ≤1 in-flight call).
- `handle_reorder_queue`: cancel worker → pure helper `apply_reorder(queue, current_index, from, to) -> (new_index, tail_changed)` → **delete the stop/clear/replay block**; set `queue_dirty` when the tail changed. Current track never restarts; stale target tail is rebuilt at the next track boundary (below).
- `handle_add_to_queue`: if worker active, skip direct enqueue (live iteration picks it up); else direct enqueue under the lock.
- `const.py`: `TARGET_STATE_GRACE_SECONDS = 10.0`, `PLAYLIST_CACHE_TTL_SECONDS = 30.0`.

**`media_player.py`**
- Refactor the state-listener closure into bound method `_async_target_state_changed` (testability).
- Optimistic grace: `_set_optimistic_state(state)` sets `_attr_state` + `monotonic` deadline (+10 s) and writes state **before** the proxy call in `async_media_play/pause/stop`. In the state listener, ignore a contradicting target state inside the window (metadata + queue-index sync still run); a confirming state clears the window. Map `buffering`→PLAYING.
- `_proxy_command`: wrap service call in `async with self.data.target_lock`.
- `async_play_media` / `_play_from_queue_index`: cancel worker first; keep stop→clear→play-first (foreground); then `async_start_enqueue(target, index+1)` instead of the foreground loop; clear `queue_dirty`; re-assert repeat (below). Cancel worker in `async_will_remove_from_hass`.
- Dirty-advance hook in the state listener: if `queue_dirty` and target advanced to a new title → clear flag, schedule `_play_from_queue_index(current_index + 1)` (rebuild at a track boundary, not mid-song).

**Repeat feature (`media_player.py`)**
- `supported_features` becomes a property: base flags + `MediaPlayerEntityFeature.REPEAT_SET` only when the target entity advertises REPEAT_SET (MA does). Note: correct HA names are `REPEAT_SET` / `async_set_repeat(repeat: RepeatMode)` / service `media_player.repeat_set`.
- `async_set_repeat`: optimistic `_attr_repeat` (+ its own 10 s grace), persist to `data.repeat_mode`, proxy `repeat_set` to target.
- Sync `_attr_repeat` from target's `repeat` attribute in the state listener (outside grace window). Restore persisted mode on add-to-hass. `_async_apply_repeat_to_target()` re-asserts a non-off mode after every queue rebuild (don't rely on MA keeping it across `clear_playlist`).

**Playlist search (`media_player.py` `async_search_media`)**
- Fetch `get_playlists()` with a 30 s entity-level cache (try/except so failure never breaks other results); filter case-insensitive substring on name; append `BrowseMedia(media_class=PLAYLIST, media_content_id="media-source://navidrome/playlist/{id}", can_play=True, can_expand=True, thumbnail=coverArt…)`. Playback path already works (`_resolve_to_tracks` playlist branch). Honor `query.media_filter_classes` if set.

### Phase 2 — Cards (`custom_components/navidrome/www/`)

- Both cards: add `esc()` HTML-escape helper; apply to all interpolated strings/attributes (titles, artists, config strings, error messages, `data-content-id`, `src`).
- **Queue card**: repeat cycle button in the header (between count and 🗑), shown only when the player entity exposes `repeat`: cycles off→all→one via `media_player.repeat_set` on the navidrome entity. Indicator = icon + dimming: `mdi:repeat-off` (dim) / `mdi:repeat` (highlighted = whole-playlist loop) / `mdi:repeat-once` (highlighted = single-song loop). Factor out `_playerEntityId()`; include `repeat` in the re-render change check.
- **Search card**: `max_playlists` option (default 5); "Playlists" section rendered from `media_class === "playlist"` with ▶ play (existing generic handler works); placeholder → "Search songs, artists, albums, playlists...".
- Bump card resource versions (registered with `cache_headers=True` in `__init__.py` → append `?v=` query in `add_extra_js_url`) so browsers pick up changes.
- README: fix `max_height`→`max_visible` doc drift; document new options.

### Phase 3 — Snapserver addon repo (small, separate commit(s))

- `run.sh`: replace `[tcp-control]`→`[tcp]`; remove `[tcp-streaming]`, move streaming bind/port (1704) under `[stream]`.
- `config.yaml`: `buffer_ms: int(500,10000)`.
- Optional hardening in `control.py`: socket timeout (5 s), try/except around JSON-RPC request parsing with proper error response.

## Verification

1. `pytest tests/components/navidrome/ -v` — update existing tests (enqueue now via worker → await `data.enqueue_task`; foreground call order stop/clear/play; optimistic state asserted before proxy returns; queue persistence payload gains `repeat_mode`/`queue_dirty`). New tests: enqueue worker (sequential, cancellation, per-track failure tolerance), optimistic grace (stale `playing` event ignored within window, adopted after), repeat (proxy + persist + re-assert after rebuild), `apply_reorder` matrix + dirty-advance, playlist search merge/filtering. Test harness: `_make_player` must set `data.hass` and shim `async_create_background_task` onto the real loop.
2. Deploy to HA (copy `custom_components/navidrome/`, restart) — live checks:
   - Set MA snapcast `stream idle threshold` → 10000; pause/resume/next respond in ≤ a couple of seconds (audio) and UI no longer flips back to "playing".
   - Start a large playlist → pause immediately → reacts fast (lock, no storm); drag-reorder mid-song → current track does **not** restart.
   - Repeat button cycles + indicator matches MA queue repeat (check MA UI); repeat-one loops current song; repeat-all wraps queue to track 1.
   - Search a playlist name → Playlists section appears → ▶ plays full playlist and fills queue card.
3. Addon: rebuild, check snapserver log shows config parsed cleanly; snapclient reconnects; `Server.GetStatus` via port 1705 still lists streams.

## Notes
- Accepted trade-off: after a reorder, the target's queue tail is stale until the next track boundary (HA media_player API can't edit individual queue items without killing current playback).
- Phase ordering: Phase 0 (MA setting) needs no code. Phases 1–3 are independent enough to land as separate commits; tests land with each phase.
