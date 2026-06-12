function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

class NavidromeSearchCard extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
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
      max_songs: config.max_songs || 20,
      max_albums: config.max_albums || 10,
      max_artists: config.max_artists || 5,
      max_playlists: config.max_playlists || 5,
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
          <span class="ns-title">${esc(this._config.title)}</span>
        </div>
        <div class="ns-search-box">
          <input type="text" class="ns-input" placeholder="Search songs, artists, albums, playlists..." />
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
      this._showEmpty(`Search failed: ${esc(err.message || "unknown error")}`);
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

    const songs = results.filter((r) => r.media_class === "track").slice(0, this._config.max_songs);
    const albums = results.filter((r) => r.media_class === "album").slice(0, this._config.max_albums);
    const artists = results.filter((r) => r.media_class === "artist").slice(0, this._config.max_artists);
    const playlists = results.filter((r) => r.media_class === "playlist").slice(0, this._config.max_playlists);

    let html = "";

    if (songs.length > 0) {
      html += `<div class="ns-section-title">Songs (${songs.length})</div>`;
      html += songs.map((s) => this._renderSongItem(s)).join("");
    }

    if (albums.length > 0) {
      html += `<div class="ns-section-title">Albums (${albums.length})</div>`;
      html += albums.map((a) => this._renderAlbumItem(a)).join("");
    }

    if (artists.length > 0) {
      html += `<div class="ns-section-title">Artists (${artists.length})</div>`;
      html += artists.map((a) => this._renderArtistItem(a)).join("");
    }

    if (playlists.length > 0) {
      html += `<div class="ns-section-title">Playlists (${playlists.length})</div>`;
      html += playlists.map((p) => this._renderPlaylistItem(p)).join("");
    }

    container.innerHTML = html;
    this._attachResultHandlers();
  }

  _renderSongItem(song) {
    const thumb = song.thumbnail
      ? `<img class="ns-item-thumb" src="${esc(song.thumbnail)}" loading="lazy" />`
      : '<div class="ns-item-thumb"></div>';

    return `
      <div class="ns-item" data-content-id="${esc(song.media_content_id)}" data-type="song">
        ${thumb}
        <div class="ns-item-info">
          <div class="ns-item-title">${esc(song.title) || "Unknown"}</div>
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
      ? `<img class="ns-item-thumb" src="${esc(album.thumbnail)}" loading="lazy" />`
      : '<div class="ns-item-thumb"></div>';

    return `
      <div class="ns-item" data-content-id="${esc(album.media_content_id)}" data-type="album">
        ${thumb}
        <div class="ns-item-info">
          <div class="ns-item-title">${esc(album.title) || "Unknown"}</div>
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
      ? `<img class="ns-item-thumb" src="${esc(artist.thumbnail)}" loading="lazy" />`
      : '<div class="ns-item-thumb"></div>';

    return `
      <div class="ns-item" data-content-id="${esc(artist.media_content_id)}" data-type="artist">
        ${thumb}
        <div class="ns-item-info">
          <div class="ns-item-title">${esc(artist.title) || "Unknown"}</div>
          <div class="ns-item-subtitle">Artist</div>
        </div>
      </div>`;
  }

  _renderPlaylistItem(playlist) {
    const thumb = playlist.thumbnail
      ? `<img class="ns-item-thumb" src="${esc(playlist.thumbnail)}" loading="lazy" />`
      : '<div class="ns-item-thumb"></div>';

    return `
      <div class="ns-item" data-content-id="${esc(playlist.media_content_id)}" data-type="playlist">
        ${thumb}
        <div class="ns-item-info">
          <div class="ns-item-title">${esc(playlist.title) || "Unknown"}</div>
          <div class="ns-item-subtitle">Playlist</div>
        </div>
        <div class="ns-actions">
          <button class="ns-action-btn ns-play" title="Play playlist">▶</button>
        </div>
      </div>`;
  }

  _attachResultHandlers() {
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

    this.querySelectorAll(".ns-add-queue").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const item = btn.closest(".ns-item");
        const contentId = item.dataset.contentId;
        const songId = this._extractSongId(contentId);
        if (songId) {
          this._hass.callService("navidrome", "add_to_queue", { song_id: songId });
          btn.textContent = "✓";
          setTimeout(() => { btn.textContent = "➕"; }, 1500);
        }
      });
    });

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
    if (contentId.includes("media-source://navidrome/song/")) {
      return contentId.replace("media-source://navidrome/song/", "");
    }
    try {
      const url = new URL(contentId);
      return url.searchParams.get("id");
    } catch {
      return null;
    }
  }

  async _showPlaylistDropdown(btn, songId) {
    const existing = this.querySelector(".ns-playlist-dropdown");
    if (existing) existing.remove();

    if (!this._playlistCache) {
      try {
        const result = await this._hass.callWS({
          type: "media_player/search_media",
          entity_id: this._config.entity,
          search_query: " ",
        });
        // Extract playlists from search results (empty query returns cached list)
        this._playlistCache = (result?.result || [])
          .filter((r) => r.media_class === "playlist");
      } catch {
        this._playlistCache = [];
      }
    }

    const dropdown = document.createElement("div");
    dropdown.className = "ns-playlist-dropdown";

    let optionsHtml = this._playlistCache.map((p) =>
      `<div class="ns-playlist-option" data-playlist-id="${esc(p.media_content_id)}">${esc(p.title)}</div>`
    ).join("");

    optionsHtml += `<div class="ns-playlist-option ns-new-playlist" data-action="new">+ New Playlist...</div>`;
    dropdown.innerHTML = optionsHtml;

    btn.closest(".ns-item").appendChild(dropdown);

    dropdown.querySelectorAll("[data-playlist-id]").forEach((opt) => {
      opt.addEventListener("click", (e) => {
        e.stopPropagation();
        const playlistId = opt.dataset.playlistId.replace("media-source://navidrome/playlist/", "");
        this._hass.callService("navidrome", "add_to_playlist", {
          playlist_id: playlistId,
          song_id: songId,
        });
        dropdown.remove();
      });
    });

    dropdown.querySelector('[data-action="new"]').addEventListener("click", (e) => {
      e.stopPropagation();
      const name = prompt("Enter playlist name:");
      if (name) {
        this._hass.callService("navidrome", "add_to_playlist", {
          playlist_id: "__new__:" + name,
          song_id: songId,
        });
      }
      dropdown.remove();
    });

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
      // message comes from our own code or an escaped error string, safe to set as text
      const div = document.createElement("div");
      div.className = "ns-empty";
      div.textContent = message;
      container.innerHTML = "";
      container.appendChild(div);
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
