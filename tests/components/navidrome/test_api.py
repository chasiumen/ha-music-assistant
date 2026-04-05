"""Tests for the Navidrome API client."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.navidrome.api import (
    AuthenticationFailed,
    CannotConnect,
    NavidromeApiError,
    NavidromeClient,
)


@pytest.fixture
def mock_session() -> MagicMock:
    """Create a mock aiohttp session."""
    return MagicMock(spec=aiohttp.ClientSession)


@pytest.fixture
def client(mock_session: MagicMock) -> NavidromeClient:
    """Create a NavidromeClient with mock session."""
    return NavidromeClient(
        mock_session, "http://navidrome.local:4533", "testuser", "testpass"
    )


def _mock_response(data: dict, status: int = 200) -> AsyncMock:
    """Create a mock aiohttp response."""
    response = AsyncMock()
    response.status = status
    response.raise_for_status = MagicMock()
    response.json = AsyncMock(return_value=data)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    return response


class TestNavidromeClient:
    """Test the NavidromeClient."""

    def test_auth_params(self, client: NavidromeClient) -> None:
        """Test that auth params are generated correctly."""
        params = client._auth_params()
        assert params["u"] == "testuser"
        assert params["v"] == "1.16.1"
        assert params["c"] == "HomeAssistant"
        assert params["f"] == "json"
        assert "t" in params
        assert "s" in params

        # Verify token is MD5(password + salt)
        expected_token = hashlib.md5(
            ("testpass" + params["s"]).encode(), usedforsecurity=False
        ).hexdigest()
        assert params["t"] == expected_token

    async def test_ping_success(
        self, client: NavidromeClient, mock_session: MagicMock
    ) -> None:
        """Test successful ping."""
        mock_session.get.return_value = _mock_response(
            {"subsonic-response": {"status": "ok", "version": "1.16.1"}}
        )
        result = await client.ping()
        assert result is True

    async def test_ping_cannot_connect(
        self, client: NavidromeClient, mock_session: MagicMock
    ) -> None:
        """Test ping with connection error."""
        mock_session.get.side_effect = aiohttp.ClientError("Connection refused")
        with pytest.raises(CannotConnect):
            await client.ping()

    async def test_ping_auth_failed(
        self, client: NavidromeClient, mock_session: MagicMock
    ) -> None:
        """Test ping with authentication error."""
        mock_session.get.return_value = _mock_response(
            {
                "subsonic-response": {
                    "status": "failed",
                    "error": {"code": 40, "message": "Wrong username or password"},
                }
            }
        )
        with pytest.raises(AuthenticationFailed):
            await client.ping()

    async def test_api_error(
        self, client: NavidromeClient, mock_session: MagicMock
    ) -> None:
        """Test generic API error."""
        mock_session.get.return_value = _mock_response(
            {
                "subsonic-response": {
                    "status": "failed",
                    "error": {"code": 70, "message": "Not found"},
                }
            }
        )
        with pytest.raises(NavidromeApiError):
            await client.ping()

    async def test_search3(
        self, client: NavidromeClient, mock_session: MagicMock
    ) -> None:
        """Test search3 endpoint."""
        mock_session.get.return_value = _mock_response(
            {
                "subsonic-response": {
                    "status": "ok",
                    "searchResult3": {
                        "song": [{"id": "tr-1", "title": "Come Together"}],
                        "album": [],
                        "artist": [],
                    },
                }
            }
        )
        result = await client.search3("Come Together")
        assert len(result["song"]) == 1
        assert result["song"][0]["title"] == "Come Together"

    async def test_get_artists(
        self, client: NavidromeClient, mock_session: MagicMock
    ) -> None:
        """Test getArtists endpoint."""
        mock_session.get.return_value = _mock_response(
            {
                "subsonic-response": {
                    "status": "ok",
                    "artists": {
                        "index": [
                            {
                                "name": "B",
                                "artist": [
                                    {"id": "ar-1", "name": "The Beatles"}
                                ],
                            },
                            {
                                "name": "P",
                                "artist": [
                                    {"id": "ar-2", "name": "Pink Floyd"}
                                ],
                            },
                        ]
                    },
                }
            }
        )
        result = await client.get_artists()
        assert len(result) == 2
        assert result[0]["name"] == "The Beatles"
        assert result[1]["name"] == "Pink Floyd"

    def test_stream_url(self, client: NavidromeClient) -> None:
        """Test stream URL building."""
        url = client.stream_url("tr-123")
        assert "http://navidrome.local:4533/rest/stream" in url
        assert "id=tr-123" in url
        assert "u=testuser" in url

    def test_cover_art_url(self, client: NavidromeClient) -> None:
        """Test cover art URL building."""
        url = client.cover_art_url("al-456", size=200)
        assert "http://navidrome.local:4533/rest/getCoverArt" in url
        assert "id=al-456" in url
        assert "size=200" in url
