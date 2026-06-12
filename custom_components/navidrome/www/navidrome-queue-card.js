function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

class NavidromeQueueCard extends HTMLElement {
  set hass(hass) {
    this._hass = hass;

    const state = hass.states[this._config?.entity];
    const newTracks = state?.attributes?.tracks;
    const newIndex = state?.attributes?.current_index;

    // Also check repeat on the player entity
    const playerEntityId = this._playerEntityId();
    const playerState = playerEntityId ? hass.states[playerEntityId] : null;
    const newRepeat = playerState?.attributes?.repeat ?? null;

    const stateChanged =
      JSON.stringify(newTracks) !== this._lastTracksJson ||
      newIndex !== this._lastIndex ||
      newRepeat !== this._lastRepeat;

    if (stateChanged || !this._rendered) {
      this._lastTracksJson = JSON.stringify(newTracks);
      const trackChanged = this._lastIndex !== newIndex;
      this._lastIndex = newIndex;
      this._lastRepeat = newRepeat;
      this._render(trackChanged);
    }
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error("Please define a queue sensor entity");
    }
    this._config = {
      entity: config.entity,
      player_entity: config.player_entity || null,
      max_visible: config.max_visible || 10,
      title: config.title || "Queue",
      ...config,
    };
  }

  getCardSize() {
    return 4;
  }

  static getStubConfig() {
    return {
      entity: "sensor.navidrome_ryosukemorino_com_queue",
      max_visible: 10,
    };
  }

  _playerEntityId() {
    if (this._config?.player_entity) return this._config.player_entity;
    const sensorId = this._config?.entity;
    if (!sensorId) return null;
    return sensorId.replace("sensor.", "media_player.").replace("_queue", "");
  }

  _render(scrollToCurrent = false) {
    this._rendered = true;
    if (!this._hass || !this._config) return;

    const state = this._hass.states[this._config.entity];
    if (!state) {
      this.innerHTML = `<ha-card><div class="nq-empty">Entity not found: ${esc(this._config.entity)}</div></ha-card>`;
      return;
    }

    const tracks = state.attributes.tracks || [];
    const total = state.attributes.total_tracks || 0;
    const currentIndex = state.attributes.current_index || 0;

    const playerEntityId = this._playerEntityId();
    const playerState = playerEntityId ? this._hass.states[playerEntityId] : null;
    const repeat = playerState?.attributes?.repeat ?? null;

    // Repeat button: only show when the player exposes a repeat attribute
    let repeatBtnHtml = "";
    if (repeat !== null) {
      const repeatIcons = {
        off: "mdi:repeat-off",
        all: "mdi:repeat",
        one: "mdi:repeat-once",
      };
      const icon = repeatIcons[repeat] || "mdi:repeat-off";
      const active = repeat !== "off";
      repeatBtnHtml = `<ha-icon
          class="nq-repeat-btn ${active ? "nq-repeat-active" : ""}"
          icon="${esc(icon)}"
          title="Repeat: ${esc(repeat)}"
        ></ha-icon>`;
    }

    const trackRows = tracks
      .map((track) => {
        const isCurrent = track.is_current;
        const mins = Math.floor((track.duration || 0) / 60);
        const secs = String((track.duration || 0) % 60).padStart(2, "0");
        const duration = track.duration ? `${mins}:${secs}` : "";

        return `
        <div class="nq-track ${isCurrent ? "nq-current" : ""}" data-index="${track.index}" draggable="true">
          <div class="nq-drag-handle" title="Drag to reorder">⠿</div>
          <div class="nq-index">${isCurrent ? "▶" : track.index}</div>
          <div class="nq-info">
            <div class="nq-title">${esc(track.title) || "Unknown"}</div>
            <div class="nq-artist">${esc(track.artist) || "Unknown"}</div>
          </div>
          <div class="nq-duration">${esc(duration)}</div>
          <div class="nq-play-btn" data-track-index="${track.index}" title="Play this track">▶</div>
        </div>`;
      })
      .join("");

    this.innerHTML = `
      <ha-card>
        <div class="nq-header">
          <span class="nq-title-text">${esc(this._config.title)}</span>
          <div class="nq-header-right">
            <span class="nq-count">${esc(currentIndex)}/${esc(total)}</span>
            ${repeatBtnHtml}
            <span class="nq-clear-btn" title="Clear queue">🗑</span>
          </div>
        </div>
        <div class="nq-list">
          ${trackRows || '<div class="nq-empty">No tracks in queue</div>'}
        </div>
      </ha-card>
      <style>
        .nq-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 12px 16px 4px;
        }
        .nq-title-text {
          font-size: 1.1em;
          font-weight: 500;
        }
        .nq-header-right {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .nq-count {
          font-size: 0.85em;
          opacity: 0.7;
        }
        .nq-repeat-btn {
          cursor: pointer;
          opacity: 0.3;
          transition: opacity 0.2s;
          --mdc-icon-size: 20px;
        }
        .nq-repeat-btn:hover {
          opacity: 0.7;
        }
        .nq-repeat-btn.nq-repeat-active {
          opacity: 1;
          color: var(--primary-color);
        }
        .nq-clear-btn {
          cursor: pointer;
          font-size: 0.9em;
          opacity: 0.5;
          transition: opacity 0.2s;
          padding: 2px 4px;
        }
        .nq-clear-btn:hover {
          opacity: 1;
        }
        .nq-list {
          padding: 4px 0 8px;
          max-height: ${this._config.max_visible * 44}px;
          overflow-y: auto;
          scroll-behavior: smooth;
        }
        .nq-track {
          display: flex;
          align-items: center;
          padding: 6px 16px;
          gap: 12px;
          cursor: pointer;
          transition: background 0.2s;
        }
        .nq-track:hover {
          background: var(--secondary-background-color);
        }
        .nq-track:hover .nq-play-btn {
          opacity: 1;
        }
        .nq-current {
          background: var(--primary-color);
          color: var(--text-primary-color);
          border-radius: 4px;
          margin: 2px 8px;
        }
        .nq-current:hover {
          background: var(--primary-color);
        }
        .nq-drag-handle {
          cursor: grab;
          opacity: 0.3;
          font-size: 1em;
          min-width: 16px;
          text-align: center;
          user-select: none;
        }
        .nq-drag-handle:hover {
          opacity: 0.7;
        }
        .nq-track.nq-dragging {
          opacity: 0.4;
          background: var(--secondary-background-color);
        }
        .nq-track.nq-drag-over {
          border-top: 2px solid var(--primary-color);
        }
        .nq-index {
          min-width: 28px;
          text-align: center;
          font-size: 0.85em;
          opacity: 0.7;
        }
        .nq-current .nq-index {
          opacity: 1;
          font-size: 1em;
        }
        .nq-info {
          flex: 1;
          min-width: 0;
          overflow: hidden;
        }
        .nq-title {
          font-size: 0.95em;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .nq-current .nq-title {
          font-weight: 600;
        }
        .nq-artist {
          font-size: 0.8em;
          opacity: 0.7;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .nq-current .nq-artist {
          opacity: 0.9;
        }
        .nq-duration {
          font-size: 0.8em;
          opacity: 0.6;
          min-width: 40px;
          text-align: right;
        }
        .nq-current .nq-duration {
          opacity: 0.9;
        }
        .nq-play-btn {
          opacity: 0;
          font-size: 0.75em;
          padding: 4px 8px;
          border-radius: 50%;
          background: var(--primary-color);
          color: var(--text-primary-color);
          cursor: pointer;
          transition: opacity 0.2s;
          min-width: 24px;
          text-align: center;
        }
        .nq-current .nq-play-btn {
          display: none;
        }
        .nq-empty {
          text-align: center;
          padding: 16px;
          opacity: 0.5;
        }
        .nq-list::-webkit-scrollbar {
          width: 6px;
        }
        .nq-list::-webkit-scrollbar-track {
          background: transparent;
        }
        .nq-list::-webkit-scrollbar-thumb {
          background: var(--divider-color, #ccc);
          border-radius: 3px;
        }
        .nq-list::-webkit-scrollbar-thumb:hover {
          background: var(--secondary-text-color, #999);
        }
      </style>
    `;

    if (scrollToCurrent) {
      requestAnimationFrame(() => {
        const current = this.querySelector(".nq-current");
        if (current) {
          current.scrollIntoView({ block: "center", behavior: "smooth" });
        }
      });
    }

    this.querySelectorAll(".nq-play-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const trackIndex = parseInt(btn.dataset.trackIndex) - 1;
        this._playTrack(trackIndex);
      });
    });

    this.querySelectorAll(".nq-track:not(.nq-current)").forEach((row) => {
      row.addEventListener("click", () => {
        const trackIndex = parseInt(row.dataset.index) - 1;
        this._playTrack(trackIndex);
      });
    });

    const clearBtn = this.querySelector(".nq-clear-btn");
    if (clearBtn) {
      clearBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._clearQueue();
      });
    }

    const repeatBtn = this.querySelector(".nq-repeat-btn");
    if (repeatBtn) {
      repeatBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._cycleRepeat();
      });
    }

    let dragFromIndex = null;
    this.querySelectorAll(".nq-track[draggable]").forEach((row) => {
      row.addEventListener("dragstart", (e) => {
        dragFromIndex = parseInt(row.dataset.index) - 1;
        row.classList.add("nq-dragging");
        e.dataTransfer.effectAllowed = "move";
      });

      row.addEventListener("dragend", () => {
        row.classList.remove("nq-dragging");
        this.querySelectorAll(".nq-drag-over").forEach((el) =>
          el.classList.remove("nq-drag-over")
        );
      });

      row.addEventListener("dragover", (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        this.querySelectorAll(".nq-drag-over").forEach((el) =>
          el.classList.remove("nq-drag-over")
        );
        row.classList.add("nq-drag-over");
      });

      row.addEventListener("dragleave", () => {
        row.classList.remove("nq-drag-over");
      });

      row.addEventListener("drop", (e) => {
        e.preventDefault();
        row.classList.remove("nq-drag-over");
        const dragToIndex = parseInt(row.dataset.index) - 1;
        if (dragFromIndex !== null && dragFromIndex !== dragToIndex) {
          this._reorderTrack(dragFromIndex, dragToIndex);
        }
        dragFromIndex = null;
      });
    });
  }

  _playTrack(index) {
    if (!this._hass || !this._config) return;

    const state = this._hass.states[this._config.entity];
    if (!state) return;

    const tracks = state.attributes.tracks || [];
    if (index < 0 || index >= tracks.length) return;

    const track = tracks[index];
    if (!track.song_id) return;

    this._hass.callService("media_player", "play_media", {
      entity_id: this._playerEntityId(),
      media_content_id: `media-source://navidrome/song/${track.song_id}`,
      media_content_type: "music",
    });
  }

  _cycleRepeat() {
    if (!this._hass) return;
    const cycle = { off: "all", all: "one", one: "off" };
    const current = this._lastRepeat || "off";
    const next = cycle[current] || "off";
    this._hass.callService("media_player", "repeat_set", {
      entity_id: this._playerEntityId(),
      repeat: next,
    });
  }

  _reorderTrack(fromIndex, toIndex) {
    if (!this._hass) return;
    this._hass.callService("navidrome", "reorder_queue", {
      from_index: fromIndex,
      to_index: toIndex,
    });
  }

  _clearQueue() {
    if (!this._hass) return;
    this._hass.callService("navidrome", "clear_queue", {});
  }
}

customElements.define("navidrome-queue-card", NavidromeQueueCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "navidrome-queue-card",
  name: "Navidrome Queue",
  description: "Shows the current Navidrome playback queue with scrolling, click-to-play, and repeat controls",
});
