# Bug: Queue card does not update when playing a song from search

## Root cause

`NavidromeQueueSensor` has no subscription or polling mechanism. When `async_play_media` in `media_player.py` updates `data.queue` and calls `self.async_write_ha_state()`, that only refreshes the media player entity — the sensor is never told to re-evaluate, so the queue card stays stale until HA restarts.

## Affected files

- `custom_components/navidrome/const.py`
- `custom_components/navidrome/__init__.py`
- `custom_components/navidrome/sensor.py`

## Fix: HA dispatcher signaling

Every queue mutation already calls `save_queue()`. Fire a dispatcher signal there so the sensor can subscribe and refresh itself.

Mutation sites covered automatically:
- `async_play_media` → `data.save_queue()`
- `_play_from_queue_index` → `data.save_queue()`
- `_sync_queue_index` → `data.save_queue()`
- `handle_add_to_queue` → `data.save_queue()`
- `handle_reorder_queue` → `data.save_queue()`
- `data.clear_queue()` → `save_queue()`

---

## Changes

### 1. `const.py` — append one line at the bottom

```python
SIGNAL_QUEUE_UPDATED = f"{DOMAIN}_queue_updated"
```

---

### 2. `__init__.py` — three changes

**a) Add fields to `NavidromeData` dataclass** after `current_index: int = 0`:

```python
hass: Any | None = None
entry_id: str | None = None
```

(`Any` is already imported from `typing`.)

**b) After `data = NavidromeData(client=client, store=store)` in `async_setup_entry`, add:**

```python
data.hass = hass
data.entry_id = entry.entry_id
```

**c) In `save_queue()`, after `await self.store.async_save(...)`, add:**

```python
if self.hass and self.entry_id:
    from homeassistant.helpers.dispatcher import async_dispatcher_send
    from .const import SIGNAL_QUEUE_UPDATED
    async_dispatcher_send(self.hass, f"{SIGNAL_QUEUE_UPDATED}_{self.entry_id}")
```

---

### 3. `sensor.py` — add `async_added_to_hass` to `NavidromeQueueSensor`

Add this method after `__init__`:

```python
async def async_added_to_hass(self) -> None:
    """Subscribe to queue update signals."""
    from homeassistant.helpers.dispatcher import async_dispatcher_connect
    from .const import SIGNAL_QUEUE_UPDATED
    self.async_on_remove(
        async_dispatcher_connect(
            self.hass,
            f"{SIGNAL_QUEUE_UPDATED}_{self._entry.entry_id}",
            self.async_write_ha_state,
        )
    )
```

---

## Verification

After implementing, restart HA and confirm the queue card updates immediately when playing a song from the search card.
