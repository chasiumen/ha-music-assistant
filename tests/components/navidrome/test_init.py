"""Tests for setup helpers in the Navidrome integration's __init__."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.navidrome import _async_register_frontend
from custom_components.navidrome.const import FRONTEND_CARDS, FRONTEND_URL_BASE


def _mock_hass() -> MagicMock:
    hass = MagicMock()
    hass.data = {}
    hass.http.async_register_static_paths = AsyncMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    return hass


class TestRegisterFrontend:
    """Test serving and loading the bundled Lovelace cards."""

    async def test_registers_each_card_with_content_hash(self) -> None:
        """Every card is served and loaded with an 8-hex-char content hash."""
        hass = _mock_hass()

        with patch("homeassistant.components.frontend.add_extra_js_url") as add_js:
            await _async_register_frontend(hass)

        (paths,), _ = hass.http.async_register_static_paths.call_args
        assert [p.url_path for p in paths] == [
            f"{FRONTEND_URL_BASE}/{name}" for name in FRONTEND_CARDS
        ]
        urls = [call.args[1] for call in add_js.call_args_list]
        assert len(urls) == len(FRONTEND_CARDS)
        for name, url in zip(FRONTEND_CARDS, urls):
            assert re.fullmatch(rf"{FRONTEND_URL_BASE}/{name}\?v=[0-9a-f]{{8}}", url)

    async def test_registers_only_once(self) -> None:
        """A second setup (e.g. entry reload) doesn't register cards again."""
        hass = _mock_hass()

        with patch("homeassistant.components.frontend.add_extra_js_url") as add_js:
            await _async_register_frontend(hass)
            await _async_register_frontend(hass)

        assert hass.http.async_register_static_paths.call_count == 1
        assert add_js.call_count == len(FRONTEND_CARDS)
