class NavidromeSearchCard extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    // Don't re-render on every hass update — only on first load
    if (!this._rendered) {
      this._render();
    }
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error("Please define a media_player entity");
    }
    this._config = {
      entity: config.entity,
      max_height: config.max_height || 500,
      title: config.title || "Search",
      debounce_ms: config.debounce_ms || 400,
      ...config,
    };
    this._searchResults = null;
    this._searchTimeout = null;
    this._playlistCache = null;
  }

  getCardSize() {
    return 4;
  }

  static getStubConfig() {
    return {
      entity: "media_player.navidrome_ryosukemorino_com",
    };
  }

  _render() {
    if (!this._hass || !this._config) return;
    this._rendered = true;

    this.innerHTML = `
      <ha-card>
        <div class="ns-header">
          <span class="ns-title">${this._config.title}</span>
        </div>
        <div class="ns-search-box">
          <input type="text" class="ns-input" placeholder="Search songs, artists, albums..." />
        </div>
        <div class="ns-results" style="max-height: ${this._config.max_height}px; overflow-y: auto;">
          <div class="ns-empty">Type to search your Navidrome library</div>
        </div>
      </ha-card>
      <style>
        .ns-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 12px 16px 4px;
        }
        .ns-title {
          font-size: 1.1em;
          font-weight: 500;
        }
        .ns-search-box {
          padding: 4px 16px 8px;
        }
        .ns-input {
          width: 100%;
          padding: 8px 12px;
          border: 1px solid var(--divider-color, #ccc);
          border-radius: 8px;
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #333);
          font-size: 0.95em;
          outline: none;
          box-sizing: border-box;
        }
        .ns-input:focus {
          border-color: var(--primary-color);
        }
        .ns-results {
          padding: 0 0 8px;
          scroll-behavior: smooth;
        }
        .ns-section-title {
          font-size: 0.8em;
          font-weight: 600;
          text-transform: uppercase;
          opacity: 0.6;
          padding: 8px 16px 4px;
          letter-spacing: 0.5px;
        }
        .ns-item {
          display: flex;
          align-items: center;
          padding: 6px 16px;
          gap: 10px;
          cursor: pointer;
          transition: background 0.2s;
          position: relative;
        }
        .ns-item:hover {
          background: var(--secondary-background-color);
        }
        .ns-item-thumb {
          width: 40px;
          height: 40px;
          border-radius: 4px;
          object-fit: cover;
          background: var(--divider-color, #eee);
        }
        .ns-item-info {
          flex: 1;
          min-width: 0;
          overflow: hidden;
        }
        .ns-item-title {
          font-size: 0.95em;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .ns-item-subtitle {
          font-size: 0.8em;
          opacity: 0.6;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .ns-item-duration {
          font-size: 0.8em;
          opacity: 0.5;
          min-width: 35px;
          text-align: right;
        }
        .ns-actions {
          display: flex;
          gap: 4px;
          opacity: 0;
          transition: opacity 0.2s;
        }
        .ns-item:hover .ns-actions {
          opacity: 1;
        }
        .ns-action-btn {
          padding: 4px 6px;
          border-radius: 4px;
          cursor: pointer;
          font-size: 0.75em;
          background: var(--primary-color);
          color: var(--text-primary-color);
          border: none;
          transition: opacity 0.2s;
        }
        .ns-action-btn:hover {
          opacity: 0.85;
        }
        .ns-action-btn.ns-secondary {
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
        }
        .ns-empty {
          text-align: center;
          padding: 24px 16px;
          opacity: 0.5;
          font-size: 0.9em;
        }
        .ns-loading {
          text-align: center;
          padding: 16px;
          opacity: 0.5;
        }
        .ns-playlist-dropdown {
          position: absolute;
          right: 16px;
          top: 100%;
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #ccc);
          border-radius: 8px;
          box-shadow: 0 4px 12px rgba(0,0,0,0.15);
          z-index: 10;
          min-width: 200px;
          max-height: 200px;
          overflow-y: auto;
        }
        .ns-playlist-option {
          padding: 8px 12px;
          cursor: pointer;
          font-size: 0.85em;
          transition: background 0.2s;
        }
        .ns-playlist-option:hover {
          background: var(--secondary-background-color);
        }
        .ns-playlist-option.ns-new-playlist {
          font-weight: 600;
          border-top: 1px solid var(--divider-color, #ccc);
        }
        .ns-results::-webkit-scrollbar {
          width: 6px;
        }
        .ns-results::-webkit-scrollbar-track {
          background: transparent;
        }
        .ns-results::-webkit-scrollbar-thumb {
          background: var(--divider-color, #ccc);
          border-radius: 3px;
        }
      </style>
    `;

    // Search input handler with debounce
    const input = this.querySelector(".ns-input");
    input.addEventListener("input", () => {
      clearTimeout(this._searchTimeout);
      const query = input.value.trim();
      if (query.length < 2) {
        this._showEmpty("Type to search your Navidrome library");
        return;
      }
      this._showLoading();
      this._searchTimeout = setTimeout(() => this._doSearch(query), this._config.debounce_ms);
    });

    // Close any open dropdowns on click outside
    document.addEventListener("click", () => {
      const dd = this.querySelector(".ns-playlist-dropdown");
      if (dd) dd.remove();
    });
  }

  async _doSearch(query) {
    if (!this._hass) return;

    try {
      const result = await this._hass.callWS({
        type: "media_player/search_media",
        entity_id: this._config.entity,
        search_query: query,
      });

      this._searchResults = result?.result || [];
      this._renderResults();
    } catch (err) {
      this._showEmpty(`Search failed: ${err.message || "unknown error"}`);
    }
  }

  _renderResults() {
    const container = this.querySelector(".ns-results");
    if (!container) return;

    const results = this._searchResults || [];
    if (results.length === 0) {
      container.innerHTML = '<div class="ns-empty">No results found</div>';
      return;
    }

    // Categorize results
    const songs = results.filter((r) => r.media_class === "track");
    const albums = results.filter((r) => r.media_class === "album");
    const artists = results.filter((r) => r.media_class === "artist");

    let html = "";

    if (songs.length > 0) {
      html += `<div class="ns-section-title">Songs (${songs.length})</div>`;
      html += songs.map((s, i) => this._renderSongItem(s, i)).join("");
    }

    if (albums.length > 0) {
      html += `<div class="ns-section-title">Albums (${albums.length})</div>`;
      html += albums.map((a) => this._renderAlbumItem(a)).join("");
    }

    if (artists.length > 0) {
      html += `<div class="ns-section-title">Artists (${artists.length})</div>`;
      html += artists.map((a) => this._renderArtistItem(a)).join("");
    }

    container.innerHTML = html;
    this._attachResultHandlers();
  }

  _renderSongItem(song, index) {
    const thumb = song.thumbnail
      ? `<img class="ns-item-thumb" src="${song.thumbnail}" loading="lazy" />`
      : '<div class="ns-item-thumb"></div>';

    return `
      <div class="ns-item" data-content-id="${song.media_content_id}" data-type="song">
        ${thumb}
        <div class="ns-item-info">
          <div class="ns-item-title">${song.title || "Unknown"}</div>
        </div>
        <div class="ns-actions">
          <button class="ns-action-btn ns-play" title="Play now">▶</button>
          <button class="ns-action-btn ns-secondary ns-add-queue" title="Add to queue">➕</button>
          <button class="ns-action-btn ns-secondary ns-add-playlist" title="Add to playlist">💾</button>
        </div>
      </div>`;
  }

  _renderAlbumItem(album) {
    const thumb = album.thumbnail
      ? `<img class="ns-item-thumb" src="${album.thumbnail}" loading="lazy" />`
      : '<div class="ns-item-thumb"></div>';

    return `
      <div class="ns-item" data-content-id="${album.media_content_id}" data-type="album">
        ${thumb}
        <div class="ns-item-info">
          <div class="ns-item-title">${album.title || "Unknown"}</div>
          <div class="ns-item-subtitle">Album</div>
        </div>
        <div class="ns-actions">
          <button class="ns-action-btn ns-play" title="Play album">▶</button>
          <button class="ns-action-btn ns-secondary ns-add-queue" title="Add to queue">➕</button>
        </div>
      </div>`;
  }

  _renderArtistItem(artist) {
    const thumb = artist.thumbnail
      ? `<img class="ns-item-thumb" src="${artist.thumbnail}" loading="lazy" />`
      : '<div class="ns-item-thumb"></div>';

    return `
      <div class="ns-item" data-content-id="${artist.media_content_id}" data-type="artist">
        ${thumb}
        <div class="ns-item-info">
          <div class="ns-item-title">${artist.title || "Unknown"}</div>
          <div class="ns-item-subtitle">Artist</div>
        </div>
      </div>`;
  }

  _attachResultHandlers() {
    // Play buttons
    this.querySelectorAll(".ns-play").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const item = btn.closest(".ns-item");
        const contentId = item.dataset.contentId;
        this._hass.callService("media_player", "play_media", {
          entity_id: this._config.entity,
          media_content_id: contentId,
          media_content_type: "music",
        });
      });
    });

    // Add to queue buttons
    this.querySelectorAll(".ns-add-queue").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const item = btn.closest(".ns-item");
        const contentId = item.dataset.contentId;
        // Extract song ID from stream URL or media-source URI
        const songId = this._extractSongId(contentId);
        if (songId) {
          this._hass.callService("navidrome", "add_to_queue", { song_id: songId });
          btn.textContent = "✓";
          setTimeout(() => { btn.textContent = "➕"; }, 1500);
        }
      });
    });

    // Add to playlist buttons
    this.querySelectorAll(".ns-add-playlist").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const item = btn.closest(".ns-item");
        const contentId = item.dataset.contentId;
        const songId = this._extractSongId(contentId);
        if (songId) {
          this._showPlaylistDropdown(btn, songId);
        }
      });
    });
  }

  _extractSongId(contentId) {
    // From media-source URI: media-source://navidrome/song/{id}
    if (contentId.includes("media-source://navidrome/song/")) {
      return contentId.replace("media-source://navidrome/song/", "");
    }
    // From stream URL: ...?id={id}&...
    try {
      const url = new URL(contentId);
      return url.searchParams.get("id");
    } catch {
      return null;
    }
  }

  async _showPlaylistDropdown(btn, songId) {
    // Remove any existing dropdown
    const existing = this.querySelector(".ns-playlist-dropdown");
    if (existing) existing.remove();

    // Fetch playlists if not cached
    if (!this._playlistCache) {
      try {
        const state = this._hass.states[this._config.entity];
        // We'll fetch playlists by browsing the media source
        // For now, use a simple dropdown with "New Playlist" option
        this._playlistCache = []; // TODO: fetch from browse
      } catch {
        this._playlistCache = [];
      }
    }

    const dropdown = document.createElement("div");
    dropdown.className = "ns-playlist-dropdown";

    // New playlist option
    dropdown.innerHTML = `
      <div class="ns-playlist-option ns-new-playlist" data-action="new">
        + New Playlist...
      </div>
    `;

    btn.closest(".ns-item").appendChild(dropdown);

    // Handle new playlist click
    dropdown.querySelector('[data-action="new"]').addEventListener("click", (e) => {
      e.stopPropagation();
      const name = prompt("Enter playlist name:");
      if (name) {
        this._hass.callService("navidrome", "save_queue_as_playlist", { name });
        // TODO: create playlist with just this song instead of queue
      }
      dropdown.remove();
    });

    // Close on next click
    setTimeout(() => {
      const handler = () => {
        dropdown.remove();
        document.removeEventListener("click", handler);
      };
      document.addEventListener("click", handler);
    }, 10);
  }

  _showEmpty(message) {
    const container = this.querySelector(".ns-results");
    if (container) {
      container.innerHTML = `<div class="ns-empty">${message}</div>`;
    }
  }

  _showLoading() {
    const container = this.querySelector(".ns-results");
    if (container) {
      container.innerHTML = '<div class="ns-loading">Searching...</div>';
    }
  }
}

customElements.define("navidrome-search-card", NavidromeSearchCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "navidrome-search-card",
  name: "Navidrome Search",
  description: "Search your Navidrome library and play, queue, or save to playlists",
});
