"""HomeMatic über das CCU-Add-on HM-REST (REST-API + Server-Sent Events)."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import CONF_API_KEY, CONF_SSL, DEFAULT_PORT, DOMAIN, PLATFORMS
from .hub import HmRestApi, HmRestAuthError, HmRestError, HmRestHub
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

type HmRestConfigEntry = ConfigEntry[HmRestHub]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Aktionen (Wochenprogramm) einmalig registrieren."""
    await async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HmRestConfigEntry) -> bool:
    api = HmRestApi(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        entry.data[CONF_API_KEY],
        entry.data.get(CONF_SSL, False),
    )
    hub = HmRestHub(hass, entry, api)
    try:
        await hub.async_load()
    except HmRestAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except HmRestError as err:
        raise ConfigEntryNotReady(f"HM-REST nicht erreichbar: {err}") from err

    if hub.sysvars_enabled:
        await hub.async_poll_sysvars()  # Fehler hier sind nicht fatal (ReGa evtl. noch nicht bereit)

    entry.runtime_data = hub
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_create_background_task(hass, hub.run_events(), "hmrest_events")
    entry.async_create_background_task(hass, hub.run_scanner(), "hmrest_scanner")
    if hub.sysvars_enabled:
        entry.async_create_background_task(hass, hub.run_sysvar_poller(), "hmrest_sysvars")
    entry.async_on_unload(hub.stop)
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def _options_updated(hass: HomeAssistant, entry: HmRestConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HmRestConfigEntry) -> bool:
    entry.runtime_data.stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(hass: HomeAssistant, entry: HmRestConfigEntry, device_entry) -> bool:
    """Gerät manuell entfernen erlauben, wenn es in der CCU nicht mehr existiert."""
    hub = entry.runtime_data
    return not any(
        ident[1] in hub.devices or ident[1] == f"{entry.entry_id}_sysvars" for ident in device_entry.identifiers
    )
