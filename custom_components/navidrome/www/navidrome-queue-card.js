class NavidromeQueueCard extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error("Please define a queue sensor entity");
    }
    this._config = {
      entity: config.entity,
      player_entity: config.player_entity || null,
      max_height: config.max_height || 400,
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
      max_height: 400,
    };
  }

  _render() {
    if (!this._hass || !this._config) return;

    const state = this._hass.states[this._config.entity];
    if (!state) {
      this.innerHTML = `<ha-card><div class="nq-empty">Entity not found: ${this._config.entity}</div></ha-card>`;
      return;
    }

    const tracks = state.attributes.tracks || [];
    const total = state.attributes.total_tracks || 0;
    const currentIndex = state.attributes.current_index || 0;

    const trackRows = tracks
      .map((track) => {
        const isCurrent = track.is_current;
        const mins = Math.floor((track.duration || 0) / 60);
        const secs = String((track.duration || 0) % 60).padStart(2, "0");
        const duration = track.duration ? `${mins}:${secs}` : "";

        return `
        <div class="nq-track ${isCurrent ? "nq-current" : ""}" data-index="${track.index}">
          <div class="nq-index">${isCurrent ? "▶" : track.index}</div>
          <div class="nq-info">
            <div class="nq-title">${track.title || "Unknown"}</div>
            <div class="nq-artist">${track.artist || "Unknown"}</div>
          </div>
          <div class="nq-duration">${duration}</div>
          <div class="nq-play-btn" data-track-index="${track.index}" title="Play this track">▶</div>
        </div>`;
      })
      .join("");

    this.innerHTML = `
      <ha-card>
        <div class="nq-header">
          <span class="nq-title-text">${this._config.title}</span>
          <div class="nq-header-right">
            <span class="nq-count">${currentIndex}/${total}</span>
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
          max-height: ${this._config.max_height}px;
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
        /* Scrollbar styling */
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

    // Scroll current track into view
    requestAnimationFrame(() => {
      const current = this.querySelector(".nq-current");
      if (current) {
        current.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    });

    // Add click handlers for play buttons
    this.querySelectorAll(".nq-play-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const trackIndex = parseInt(btn.dataset.trackIndex) - 1;
        this._playTrack(trackIndex);
      });
    });

    // Add click handler for track rows
    this.querySelectorAll(".nq-track:not(.nq-current)").forEach((row) => {
      row.addEventListener("click", () => {
        const trackIndex = parseInt(row.dataset.index) - 1;
        this._playTrack(trackIndex);
      });
    });

    // Clear queue button
    const clearBtn = this.querySelector(".nq-clear-btn");
    if (clearBtn) {
      clearBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._clearQueue();
      });
    }
  }

  _playTrack(index) {
    if (!this._hass || !this._config) return;

    const state = this._hass.states[this._config.entity];
    if (!state) return;

    const tracks = state.attributes.tracks || [];
    if (index < 0 || index >= tracks.length) return;

    // Find the navidrome media_player entity to send play_media
    // Derive from the sensor entity name
    const sensorId = this._config.entity;
    const playerEntity =
      this._config.player_entity ||
      sensorId.replace("sensor.", "media_player.").replace("_queue", "");

    const track = tracks[index];
    if (!track.song_id) return;

    this._hass.callService("media_player", "play_media", {
      entity_id: playerEntity,
      media_content_id: `media-source://navidrome/song/${track.song_id}`,
      media_content_type: "music",
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
  description: "Shows the current Navidrome playback queue with scrolling and click-to-play",
});
