"""Aktionen der HM-REST-Integration: Wochenprogramme von Heizungsthermostaten."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr, entity_registry as er

from .const import DOMAIN
from .hub import HmRestError, HmRestHub

SERVICE_SET_WEEK_PROGRAM = "set_week_program"
SERVICE_GET_WEEK_PROGRAM = "get_week_program"

ATTR_DAYS = "days"
ATTR_SCHEDULE = "schedule"
ATTR_PROFILE = "profile"
ATTR_ACTIVATE = "activate"

DAY_CHOICES = [
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "workdays", "weekend", "all",
]

# "06:00 17; 22:00 21; 24:00 17"  oder  "06:00=17, 22:00=21,5, 24:00=17"
_SLOT_RE = re.compile(r"(\d{1,2}:\d{2})\s*(?:=|\s|->|bis)?\s*(\d+(?:[.,]\d+)?)")


def _parse_schedule(value: Any) -> list[dict[str, Any]]:
    """Plan als Liste [{end, temp}] oder als Text annehmen."""
    if isinstance(value, str):
        slots = [{"end": m.group(1), "temp": float(m.group(2).replace(",", "."))} for m in _SLOT_RE.finditer(value)]
        if not slots:
            raise vol.Invalid('Plan nicht lesbar – Beispiel: "06:00 17; 22:00 21; 24:00 17"')
        return slots
    if isinstance(value, list):
        out = []
        for i, s in enumerate(value, 1):
            if not isinstance(s, dict):
                raise vol.Invalid(f"Abschnitt {i}: erwartet {{end: '06:00', temp: 21}}")
            end = s.get("end", s.get("bis", s.get("until")))
            temp = s.get("temp", s.get("temperature"))
            if end is None or temp is None:
                raise vol.Invalid(f"Abschnitt {i}: 'end' und 'temp' werden benötigt")
            if isinstance(temp, str):
                temp = temp.replace(",", ".")
            try:
                temp = float(temp)
            except (TypeError, ValueError) as err:
                raise vol.Invalid(f"Abschnitt {i}: Temperatur ungültig") from err
            out.append({"end": str(end) if not isinstance(end, (int, float)) else int(end), "temp": temp})
        if not out:
            raise vol.Invalid("Plan ist leer")
        return out
    raise vol.Invalid("Plan als Liste oder Text angeben")


_TARGET = {
    vol.Optional(ATTR_DEVICE_ID): vol.Any(cv.string, [cv.string]),
    vol.Optional(ATTR_ENTITY_ID): vol.Any(cv.entity_id, cv.entity_ids),
}

SET_SCHEMA = vol.All(
    vol.Schema(
        {
            **_TARGET,
            vol.Optional(ATTR_DAYS): vol.All(cv.ensure_list, [vol.All(cv.string, vol.Lower, vol.In(DAY_CHOICES))]),
            vol.Optional(ATTR_SCHEDULE): _parse_schedule,
            vol.Optional(ATTR_PROFILE): vol.All(vol.Coerce(int), vol.Range(min=1, max=6)),
            vol.Optional(ATTR_ACTIVATE, default=False): cv.boolean,
        }
    ),
    cv.has_at_least_one_key(ATTR_DEVICE_ID, ATTR_ENTITY_ID),
)

GET_SCHEMA = vol.All(vol.Schema(_TARGET), cv.has_at_least_one_key(ATTR_DEVICE_ID, ATTR_ENTITY_ID))


def _targets(hass: HomeAssistant, call: ServiceCall) -> list[tuple[HmRestHub, str, str]]:
    """Gerät(e) aus device_id/entity_id ermitteln -> (Hub, CCU-Adresse, Anzeigename)."""
    dev_reg, ent_reg = dr.async_get(hass), er.async_get(hass)
    device_ids: list[str] = []
    for d in cv.ensure_list(call.data.get(ATTR_DEVICE_ID)):
        device_ids.append(d)
    for eid in cv.ensure_list(call.data.get(ATTR_ENTITY_ID)):
        ent = ent_reg.async_get(eid)
        if ent is None or ent.device_id is None:
            raise ServiceValidationError(f"{eid} gehört zu keinem HomeMatic-Gerät")
        device_ids.append(ent.device_id)

    hubs: list[HmRestHub] = [
        e.runtime_data for e in hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED and getattr(e, "runtime_data", None) is not None
    ]
    result: list[tuple[HmRestHub, str, str]] = []
    for did in dict.fromkeys(device_ids):  # Duplikate entfernen, Reihenfolge behalten
        device = dev_reg.async_get(did)
        if device is None:
            raise ServiceValidationError(f"Gerät {did} nicht gefunden")
        addr = next((ident[1] for ident in device.identifiers if ident[0] == DOMAIN), None)
        if not addr:
            raise ServiceValidationError(f"{device.name_by_user or device.name} ist kein HM-REST-Gerät")
        hub = next((h for h in hubs if addr in h.devices), None)
        if hub is None:
            raise ServiceValidationError(f"{device.name_by_user or device.name}: zugehörige CCU ist nicht verbunden")
        result.append((hub, addr, device.name_by_user or device.name or addr))
    return result


def _raise(err: HmRestError, name: str) -> None:
    msg = str(err)
    if "HTTP 400" in msg or "HTTP 404" in msg:
        raise ServiceValidationError(f"{name}: {msg.split(': ', 2)[-1]}") from err
    raise HomeAssistantError(f"{name}: {msg}") from err


async def async_setup_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SET_WEEK_PROGRAM):
        return

    async def set_week_program(call: ServiceCall) -> None:
        days = call.data.get(ATTR_DAYS)
        schedule = call.data.get(ATTR_SCHEDULE)
        profile = call.data.get(ATTR_PROFILE)
        activate = call.data[ATTR_ACTIVATE]
        if bool(days) != bool(schedule):
            raise ServiceValidationError("'days' und 'schedule' gehören zusammen")
        if not days and not activate:
            raise ServiceValidationError("Nichts zu tun: 'days' + 'schedule' und/oder 'activate' angeben")
        for hub, addr, name in _targets(hass, call):
            body: dict[str, Any] = {}
            if profile:
                body["profile"] = profile
            if days:
                body["days"] = {",".join(days): schedule}
            if activate:
                if not profile:
                    raise ServiceValidationError("Für 'activate' bitte 'profile' angeben")
                body["activeProfile"] = profile
            try:
                await hub.api.set_week_program(addr, body)
            except HmRestError as err:
                _raise(err, name)

    async def get_week_program(call: ServiceCall) -> ServiceResponse:
        out: dict[str, Any] = {}
        for hub, addr, name in _targets(hass, call):
            try:
                info = await hub.api.week_program(addr)
            except HmRestError as err:
                _raise(err, name)
            out[name] = {
                "address": info.get("address"),
                "active_profile": info.get("activeProfile"),
                "profiles": info.get("profiles"),
                "program": {
                    p: {d.lower(): slots for d, slots in days.items()}
                    for p, days in (info.get("program") or {}).items()
                },
            }
        return out

    hass.services.async_register(DOMAIN, SERVICE_SET_WEEK_PROGRAM, set_week_program, schema=SET_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_GET_WEEK_PROGRAM, get_week_program, schema=GET_SCHEMA, supports_response=SupportsResponse.ONLY
    )
