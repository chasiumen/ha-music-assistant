"""Tests for setup helpers in the Navidrome integration's __init__."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.navidrome import (
    NavidromeData,
    _async_register_frontend,
    async_refresh_server_info,
)
from custom_components.navidrome.api import CannotConnect, ServerInfo
from custom_components.navidrome.const import (
    DOMAIN,
    FRONTEND_CARDS,
    FRONTEND_URL_BASE,
    SIGNAL_SERVER_INFO_UPDATED,
)

from .conftest import MOCK_SERVER_INFO


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


def _entry_with_server_info(server_info: ServerInfo | None) -> MagicMock:
    data = NavidromeData(client=MagicMock(), server_info=server_info)
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    entry.runtime_data = data
    return entry


class TestRefreshServerInfo:
    """Test the periodic server version refresh."""

    async def test_version_change_updates_data_device_and_sensor(self) -> None:
        """A new version is stored, written to the device and signalled."""
        entry = _entry_with_server_info(ServerInfo(server_version="0.53.3 (old)"))
        new_info = ServerInfo(server_version="0.54.0 (new)")
        entry.runtime_data.client.ping = AsyncMock(return_value=new_info)
        dev_reg = MagicMock()
        dev_reg.async_get_device.return_value = MagicMock(
            id="dev-1", sw_version="0.53.3 (old)"
        )
        hass = MagicMock()

        with (
            patch("custom_components.navidrome.dr.async_get", return_value=dev_reg),
            patch("custom_components.navidrome.async_dispatcher_send") as send,
        ):
            await async_refresh_server_info(hass, entry)

        assert entry.runtime_data.server_info == new_info
        dev_reg.async_get_device.assert_called_once_with(
            identifiers={(DOMAIN, "test_entry_123")}
        )
        dev_reg.async_update_device.assert_called_once_with(
            "dev-1", sw_version="0.54.0 (new)"
        )
        send.assert_called_once_with(
            hass, f"{SIGNAL_SERVER_INFO_UPDATED}_test_entry_123"
        )

    async def test_unchanged_version_is_a_noop(self) -> None:
        """Same info → no registry write, no signal."""
        entry = _entry_with_server_info(MOCK_SERVER_INFO)
        entry.runtime_data.client.ping = AsyncMock(return_value=MOCK_SERVER_INFO)

        with (
            patch("custom_components.navidrome.dr.async_get") as get_reg,
            patch("custom_components.navidrome.async_dispatcher_send") as send,
        ):
            await async_refresh_server_info(MagicMock(), entry)

        get_reg.assert_not_called()
        send.assert_not_called()

    async def test_failed_ping_keeps_last_known(self) -> None:
        """An unreachable server leaves the stored version untouched."""
        entry = _entry_with_server_info(MOCK_SERVER_INFO)
        entry.runtime_data.client.ping = AsyncMock(side_effect=CannotConnect("down"))

        with patch("custom_components.navidrome.async_dispatcher_send") as send:
            await async_refresh_server_info(MagicMock(), entry)

        assert entry.runtime_data.server_info == MOCK_SERVER_INFO
        send.assert_not_called()
