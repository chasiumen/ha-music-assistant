"""Config flow for the Navidrome integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any
from urllib.parse import urlparse

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import AuthenticationFailed, CannotConnect, NavidromeClient
from .const import (
    CONF_CONTROL_GRACE_SECONDS,
    CONF_PLAYLIST_CACHE_TTL,
    CONF_SCROBBLE_ENABLED,
    CONF_SEARCH_RESULT_LIMIT,
    CONF_TARGET_PLAYER,
    CONTROL_GRACE_SECONDS_RANGE,
    DEFAULT_CONTROL_GRACE_SECONDS,
    DEFAULT_PLAYLIST_CACHE_TTL,
    DEFAULT_PORT,
    DEFAULT_SCROBBLE_ENABLED,
    DEFAULT_SEARCH_RESULT_LIMIT,
    DOMAIN,
    PLAYLIST_CACHE_TTL_RANGE,
    SEARCH_RESULT_LIMIT_RANGE,
)

_HTTPS_PORT = 443

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_VERIFY_SSL, default=True): bool,
    }
)

REAUTH_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): str,
    }
)


def _int_selector(bounds: tuple[int, int], unit: str | None = None) -> NumberSelector:
    """Return a whole-number input box limited to (min, max)."""
    config = NumberSelectorConfig(
        min=bounds[0], max=bounds[1], step=1, mode=NumberSelectorMode.BOX
    )
    if unit:
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


def _get_session(hass, verify_ssl: bool) -> aiohttp.ClientSession:
    """Get an aiohttp session with the correct SSL setting."""
    return async_get_clientsession(hass, verify_ssl=verify_ssl)


class NavidromeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Navidrome."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            user_input[CONF_URL] = url
            verify_ssl = user_input.get(CONF_VERIFY_SSL, True)

            # Set unique ID based on host:port
            parsed = urlparse(url)
            host = parsed.hostname or "unknown"
            port = parsed.port or (
                _HTTPS_PORT if parsed.scheme == "https" else DEFAULT_PORT
            )
            unique_id = f"{host}:{port}"

            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            session = _get_session(self.hass, verify_ssl)
            client = NavidromeClient(
                session,
                url,
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )

            try:
                await client.ping()
            except CannotConnect as err:
                _LOGGER.error("Cannot connect to Navidrome: %s", err)
                errors["base"] = "cannot_connect"
            except AuthenticationFailed:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"Navidrome ({host})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Perform reauth upon an API authentication error."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Dialog that informs the user that reauth is required."""
        errors: dict[str, str] = {}

        if user_input is not None:
            reauth_entry = self._get_reauth_entry()
            new_data = {**reauth_entry.data, **user_input}
            verify_ssl = new_data.get(CONF_VERIFY_SSL, True)

            session = _get_session(self.hass, verify_ssl)
            client = NavidromeClient(
                session,
                new_data[CONF_URL],
                new_data[CONF_USERNAME],
                new_data[CONF_PASSWORD],
            )

            try:
                await client.ping()
            except CannotConnect as err:
                _LOGGER.error("Cannot connect to Navidrome: %s", err)
                errors["base"] = "cannot_connect"
            except AuthenticationFailed:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry, data=new_data
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry,
    ) -> NavidromeOptionsFlow:
        """Create the options flow."""
        return NavidromeOptionsFlow()


class NavidromeOptionsFlow(OptionsFlow):
    """Handle options for the Navidrome integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        options_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TARGET_PLAYER,
                    default=options.get(CONF_TARGET_PLAYER, ""),
                ): EntitySelector(
                    EntitySelectorConfig(
                        domain="media_player",
                    )
                ),
                vol.Optional(
                    CONF_SCROBBLE_ENABLED,
                    default=options.get(CONF_SCROBBLE_ENABLED, DEFAULT_SCROBBLE_ENABLED),
                ): bool,
                vol.Optional(
                    CONF_SEARCH_RESULT_LIMIT,
                    default=options.get(CONF_SEARCH_RESULT_LIMIT, DEFAULT_SEARCH_RESULT_LIMIT),
                ): _int_selector(SEARCH_RESULT_LIMIT_RANGE),
                vol.Optional(
                    CONF_PLAYLIST_CACHE_TTL,
                    default=options.get(CONF_PLAYLIST_CACHE_TTL, DEFAULT_PLAYLIST_CACHE_TTL),
                ): _int_selector(PLAYLIST_CACHE_TTL_RANGE, unit="s"),
                vol.Optional(
                    CONF_CONTROL_GRACE_SECONDS,
                    default=options.get(
                        CONF_CONTROL_GRACE_SECONDS, DEFAULT_CONTROL_GRACE_SECONDS
                    ),
                ): _int_selector(CONTROL_GRACE_SECONDS_RANGE, unit="s"),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
        )
