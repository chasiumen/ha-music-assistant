"""Tests for the Navidrome config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.navidrome.api import AuthenticationFailed, CannotConnect
from custom_components.navidrome.const import DOMAIN

from .conftest import MOCK_CONFIG


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """Test successful user config flow."""
    with patch(
        "custom_components.navidrome.config_flow.NavidromeClient"
    ) as mock_client_cls:
        mock_client_cls.return_value.ping = AsyncMock(return_value=True)

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], MOCK_CONFIG
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "Navidrome (navidrome.local)"
        assert result["data"] == MOCK_CONFIG


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    """Test config flow with connection error."""
    with patch(
        "custom_components.navidrome.config_flow.NavidromeClient"
    ) as mock_client_cls:
        mock_client_cls.return_value.ping = AsyncMock(
            side_effect=CannotConnect("Connection refused")
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], MOCK_CONFIG
        )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_invalid_auth(hass: HomeAssistant) -> None:
    """Test config flow with invalid credentials."""
    with patch(
        "custom_components.navidrome.config_flow.NavidromeClient"
    ) as mock_client_cls:
        mock_client_cls.return_value.ping = AsyncMock(
            side_effect=AuthenticationFailed("Wrong password")
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], MOCK_CONFIG
        )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_unknown_error(hass: HomeAssistant) -> None:
    """Test config flow with unexpected error."""
    with patch(
        "custom_components.navidrome.config_flow.NavidromeClient"
    ) as mock_client_cls:
        mock_client_cls.return_value.ping = AsyncMock(
            side_effect=RuntimeError("Unexpected")
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], MOCK_CONFIG
        )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "unknown"}
