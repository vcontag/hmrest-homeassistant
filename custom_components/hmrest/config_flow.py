"""Einrichtung über die Oberfläche."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_API_KEY,
    CONF_SCAN_MINUTES,
    CONF_SSL,
    CONF_SYSVAR_SECONDS,
    CONF_SYSVARS,
    CONF_VIRTUAL_REMOTES,
    DEFAULT_PORT,
    DEFAULT_SCAN_MINUTES,
    DEFAULT_SYSVAR_SECONDS,
    DOMAIN,
)
from .hub import HmRestApi, HmRestAuthError, HmRestError


async def _validate(hass, data: Mapping[str, Any]) -> dict:
    api = HmRestApi(
        async_get_clientsession(hass),
        data[CONF_HOST],
        data.get(CONF_PORT, DEFAULT_PORT),
        data[CONF_API_KEY],
        data.get(CONF_SSL, False),
    )
    return await api.info()


class HmRestConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].strip().removeprefix("http://").removeprefix("https://").rstrip("/")
            await self.async_set_unique_id(f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}")
            self._abort_if_unique_id_configured()
            try:
                info = await _validate(self.hass, user_input)
            except HmRestAuthError:
                errors["base"] = "invalid_auth"
            except HmRestError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"HomeMatic CCU ({user_input[CONF_HOST]})",
                    data=user_input,
                    description_placeholders={"version": str(info.get("version", ""))},
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=(user_input or {}).get(CONF_HOST, "")): str,
                vol.Required(CONF_PORT, default=(user_input or {}).get(CONF_PORT, DEFAULT_PORT)): int,
                vol.Required(CONF_API_KEY, default=(user_input or {}).get(CONF_API_KEY, "")): str,
                vol.Optional(CONF_SSL, default=(user_input or {}).get(CONF_SSL, False)): bool,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**entry.data, CONF_API_KEY: user_input[CONF_API_KEY]}
            try:
                await _validate(self.hass, data)
            except HmRestAuthError:
                errors["base"] = "invalid_auth"
            except HmRestError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HmRestOptionsFlow()


class HmRestOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_VIRTUAL_REMOTES, default=o.get(CONF_VIRTUAL_REMOTES, False)): bool,
                    vol.Optional(CONF_SYSVARS, default=o.get(CONF_SYSVARS, True)): bool,
                    vol.Optional(
                        CONF_SYSVAR_SECONDS, default=o.get(CONF_SYSVAR_SECONDS, DEFAULT_SYSVAR_SECONDS)
                    ): vol.All(int, vol.Range(min=5, max=3600)),
                    vol.Optional(CONF_SCAN_MINUTES, default=o.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)): vol.All(
                        int, vol.Range(min=1, max=1440)
                    ),
                }
            ),
        )
