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
      max_visible: config.max_visible || 10,
      title: config.title || "Queue",
      ...config,
    };
  }

  getCardSize() {
    return 3;
  }

  static getConfigElement() {
    return document.createElement("navidrome-queue-card-editor");
  }

  static getStubConfig() {
    return {
      entity: "sensor.navidrome_ryosukemorino_com_queue",
      max_visible: 10,
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
    const maxVisible = this._config.max_visible;

    // Calculate window around current track
    let startIdx = Math.max(0, currentIndex - 3);
    let endIdx = Math.min(tracks.length, startIdx + maxVisible);
    if (endIdx - startIdx < maxVisible) {
      startIdx = Math.max(0, endIdx - maxVisible);
    }
    const visibleTracks = tracks.slice(startIdx, endIdx);

    const trackRows = visibleTracks
      .map((track) => {
        const isCurrent = track.is_current;
        const mins = Math.floor((track.duration || 0) / 60);
        const secs = String((track.duration || 0) % 60).padStart(2, "0");
        const duration = track.duration ? `${mins}:${secs}` : "";

        return `
        <div class="nq-track ${isCurrent ? "nq-current" : ""}">
          <div class="nq-index">${isCurrent ? "▶" : track.index}</div>
          <div class="nq-info">
            <div class="nq-title">${track.title || "Unknown"}</div>
            <div class="nq-artist">${track.artist || "Unknown"}</div>
          </div>
          <div class="nq-duration">${duration}</div>
        </div>`;
      })
      .join("");

    const showBefore = startIdx > 0 ? `<div class="nq-more">↑ ${startIdx} more</div>` : "";
    const remaining = tracks.length - endIdx;
    const showAfter = remaining > 0 ? `<div class="nq-more">↓ ${remaining} more</div>` : "";

    this.innerHTML = `
      <ha-card>
        <div class="nq-header">
          <span class="nq-title-text">${this._config.title}</span>
          <span class="nq-count">${currentIndex}/${total}</span>
        </div>
        <div class="nq-list">
          ${showBefore}
          ${trackRows || '<div class="nq-empty">No tracks in queue</div>'}
          ${showAfter}
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
        .nq-count {
          font-size: 0.85em;
          opacity: 0.7;
        }
        .nq-list {
          padding: 4px 0 8px;
        }
        .nq-track {
          display: flex;
          align-items: center;
          padding: 6px 16px;
          gap: 12px;
          transition: background 0.2s;
        }
        .nq-track:hover {
          background: var(--secondary-background-color);
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
        .nq-more {
          text-align: center;
          font-size: 0.8em;
          opacity: 0.5;
          padding: 4px;
        }
        .nq-empty {
          text-align: center;
          padding: 16px;
          opacity: 0.5;
        }
      </style>
    `;
  }
}

customElements.define("navidrome-queue-card", NavidromeQueueCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "navidrome-queue-card",
  name: "Navidrome Queue",
  description: "Shows the current Navidrome playback queue",
});
