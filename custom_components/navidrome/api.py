"""Async Subsonic API client for Navidrome."""

from __future__ import annotations

import hashlib
import secrets
from typing import Any
from urllib.parse import urljoin, urlencode

import aiohttp

from .const import LOGGER, SUBSONIC_API_VERSION, SUBSONIC_CLIENT_NAME


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class AuthenticationFailed(Exception):
    """Error to indicate authentication failed."""


class NavidromeApiError(Exception):
    """Error to indicate a generic API error."""


class NavidromeClient:
    """Async client for the Navidrome Subsonic API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        username: str,
        password: str,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password

    def _auth_params(self) -> dict[str, str]:
        """Generate authentication parameters with token+salt."""
        salt = secrets.token_hex(16)
        token = hashlib.md5(
            (self._password + salt).encode(), usedforsecurity=False
        ).hexdigest()
        return {
            "u": self._username,
            "t": token,
            "s": salt,
            "v": SUBSONIC_API_VERSION,
            "c": SUBSONIC_CLIENT_NAME,
            "f": "json",
        }

    async def _request(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make an authenticated request to the Subsonic API."""
        request_params = self._auth_params()
        if params:
            request_params.update(params)

        url = f"{self._base_url}/rest/{endpoint}"

        try:
            async with self._session.get(
                url, params=request_params, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
        except aiohttp.ClientResponseError as err:
            LOGGER.error("HTTP error from %s: %s %s", url, err.status, err.message)
            raise CannotConnect(
                f"HTTP {err.status} from {self._base_url}: {err.message}"
            ) from err
        except (aiohttp.ClientError, TimeoutError) as err:
            LOGGER.error("Connection error to %s: %s", url, err)
            raise CannotConnect(f"Cannot connect to {self._base_url}: {err}") from err

        subsonic_response = data.get("subsonic-response", {})
        status = subsonic_response.get("status")

        if status != "ok":
            error = subsonic_response.get("error", {})
            code = error.get("code", 0)
            message = error.get("message", "Unknown error")
            # Code 40 = wrong username or password
            if code == 40:
                raise AuthenticationFailed(message)
            raise NavidromeApiError(f"API error {code}: {message}")

        return subsonic_response

    # -- System --

    async def ping(self) -> bool:
        """Check connectivity and authentication."""
        await self._request("ping")
        return True

    # -- Scrobble --

    async def scrobble(self, song_id: str, submission: bool = False) -> None:
        """Send a scrobble event for a song.

        submission=False: "now playing" notification
        submission=True: "listened to" (after song ends)
        """
        await self._request(
            "scrobble",
            {"id": song_id, "submission": str(submission).lower()},
        )

    # -- Search --

    async def search3(
        self,
        query: str,
        song_count: int = 20,
        album_count: int = 20,
        artist_count: int = 20,
    ) -> dict[str, Any]:
        """Search for songs, albums, and artists."""
        result = await self._request(
            "search3",
            {
                "query": query,
                "songCount": song_count,
                "albumCount": album_count,
                "artistCount": artist_count,
            },
        )
        return result.get("searchResult3", {})

    # -- Browsing --

    async def get_artists(self) -> list[dict[str, Any]]:
        """Get all artists (ID3 format)."""
        result = await self._request("getArtists")
        artists_data = result.get("artists", {})
        artists: list[dict[str, Any]] = []
        for index in artists_data.get("index", []):
            artists.extend(index.get("artist", []))
        return artists

    async def get_artist(self, artist_id: str) -> dict[str, Any]:
        """Get an artist with their albums."""
        result = await self._request("getArtist", {"id": artist_id})
        return result.get("artist", {})

    async def get_song(self, song_id: str) -> dict[str, Any]:
        """Get a single song's metadata."""
        result = await self._request("getSong", {"id": song_id})
        return result.get("song", {})

    async def get_album(self, album_id: str) -> dict[str, Any]:
        """Get an album with its songs."""
        result = await self._request("getAlbum", {"id": album_id})
        return result.get("album", {})

    async def get_playlists(self) -> list[dict[str, Any]]:
        """Get all playlists."""
        result = await self._request("getPlaylists")
        return result.get("playlists", {}).get("playlist", [])

    async def get_playlist(self, playlist_id: str) -> dict[str, Any]:
        """Get a playlist with its songs."""
        result = await self._request("getPlaylist", {"id": playlist_id})
        return result.get("playlist", {})

    async def get_genres(self) -> list[dict[str, Any]]:
        """Get all genres."""
        result = await self._request("getGenres")
        return result.get("genres", {}).get("genre", [])

    async def get_album_list2(
        self,
        list_type: str,
        size: int = 20,
        offset: int = 0,
        genre: str | None = None,
        from_year: int | None = None,
        to_year: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get a curated list of albums.

        list_type: newest, random, frequent, starred, alphabeticalByName,
                   alphabeticalByArtist, byGenre, byYear, recent, highest
        """
        params: dict[str, Any] = {
            "type": list_type,
            "size": size,
            "offset": offset,
        }
        if genre is not None:
            params["genre"] = genre
        if from_year is not None:
            params["fromYear"] = from_year
        if to_year is not None:
            params["toYear"] = to_year

        result = await self._request("getAlbumList2", params)
        return result.get("albumList2", {}).get("album", [])

    # -- URL builders (no HTTP request) --

    def stream_url(self, song_id: str) -> str:
        """Build an authenticated stream URL for a song."""
        params = self._auth_params()
        params["id"] = song_id
        return f"{self._base_url}/rest/stream?{urlencode(params)}"

    def cover_art_url(self, item_id: str, size: int = 300) -> str:
        """Build an authenticated cover art URL."""
        params = self._auth_params()
        params["id"] = item_id
        params["size"] = str(size)
        return f"{self._base_url}/rest/getCoverArt?{urlencode(params)}"
