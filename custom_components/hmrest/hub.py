"""Verbindung zum HM-REST-Add-on: Geräteliste per REST, Wertänderungen per SSE."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import json
import logging
from typing import Any
from urllib.parse import quote

import aiohttp

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_SCAN_MINUTES,
    CONF_SYSVAR_SECONDS,
    CONF_SYSVARS,
    CONF_VIRTUAL_REMOTES,
    DEFAULT_SCAN_MINUTES,
    DEFAULT_SYSVAR_SECONDS,
    VIRTUAL_REMOTE_TYPES,
)

_LOGGER = logging.getLogger(__name__)


class HmRestError(Exception):
    """Allgemeiner Fehler beim Zugriff auf HM-REST."""


class HmRestAuthError(HmRestError):
    """API-Key falsch."""


# --------------------------------------------------------------------------
# REST-Client
# --------------------------------------------------------------------------


class HmRestApi:
    """Dünner Client für die HM-REST-API."""

    def __init__(self, session: aiohttp.ClientSession, host: str, port: int, api_key: str, ssl: bool = False) -> None:
        self._session = session
        self.base = f"{'https' if ssl else 'http'}://{host}:{port}"
        self._headers = {"X-API-Key": api_key, "Accept": "application/json"}

    async def _request(self, method: str, path: str, *, json_body: Any = None, timeout: float = 30) -> Any:
        try:
            async with self._session.request(
                method,
                self.base + path,
                headers=self._headers,
                json=json_body,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status in (401, 403):
                    raise HmRestAuthError(f"Zugriff verweigert ({resp.status})")
                text = await resp.text()
                if resp.status >= 400:
                    try:
                        msg = json.loads(text).get("error", text)
                    except (ValueError, AttributeError):
                        msg = text
                    raise HmRestError(f"{method} {path}: HTTP {resp.status}: {msg}")
                return json.loads(text) if text else None
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise HmRestError(f"{method} {path}: {err}") from err

    async def info(self) -> dict:
        return await self._request("GET", "/api/info")

    async def devices(self, values: bool = False) -> list[dict]:
        path = "/api/devices" + ("?values=full" if values else "")
        return await self._request("GET", path, timeout=300 if values else 60)

    async def device(self, address: str) -> dict:
        return await self._request("GET", f"/api/devices/{quote(address)}?values=full", timeout=60)

    async def description(self, address: str) -> dict:
        return await self._request("GET", f"/api/devices/{quote(address)}/paramsets/VALUES/description")

    async def set_value(self, address: str, param: str, value: Any) -> None:
        await self._request("PUT", f"/api/devices/{quote(address)}/values/{quote(param)}", json_body={"value": value})

    async def set_values(self, address: str, values: dict[str, Any]) -> None:
        await self._request("PUT", f"/api/devices/{quote(address)}/values", json_body=values)

    async def sysvars(self) -> list[dict]:
        return await self._request("GET", "/api/sysvars", timeout=60)

    async def set_sysvar(self, ref: str, value: Any) -> dict:
        return await self._request("PUT", f"/api/sysvars/{quote(str(ref), safe='')}", json_body={"value": value})

    async def week_program(self, address: str) -> dict:
        return await self._request("GET", f"/api/devices/{quote(address)}/weekprogram", timeout=60)

    async def set_week_program(self, address: str, body: dict) -> dict:
        return await self._request("PUT", f"/api/devices/{quote(address)}/weekprogram", json_body=body, timeout=60)

    def events_url(self) -> str:
        return self.base + "/api/events"

    @property
    def headers(self) -> dict:
        return {**self._headers, "Accept": "text/event-stream"}


# --------------------------------------------------------------------------
# Datenmodell
# --------------------------------------------------------------------------


@dataclass
class HmParam:
    """Ein Datenpunkt (VALUES-Paramset) eines Kanals."""

    name: str
    type: str
    unit: str | None = None
    min: Any = None
    max: Any = None
    value_list: list[str] | None = None
    special: list | None = None
    readable: bool = True
    writable: bool = False
    event: bool = False
    value: Any = None

    @classmethod
    def from_meta(cls, name: str, m: dict) -> HmParam:
        return cls(
            name=name,
            type=str(m.get("type") or m.get("TYPE") or ""),
            unit=(m.get("unit") if "unit" in m else m.get("UNIT")) or None,
            min=m.get("min", m.get("MIN")),
            max=m.get("max", m.get("MAX")),
            value_list=m.get("valueList", m.get("VALUE_LIST")),
            special=m.get("special", m.get("SPECIAL")),
            readable=bool(m["readable"]) if "readable" in m else bool(int(m.get("OPERATIONS", 1)) & 1),
            writable=bool(m["writable"]) if "writable" in m else bool(int(m.get("OPERATIONS", 0)) & 2),
            event=bool(m["event"]) if "event" in m else bool(int(m.get("OPERATIONS", 0)) & 4),
            value=m.get("value"),
        )

    @property
    def enum_offset(self) -> int:
        try:
            return int(self.min or 0)
        except (TypeError, ValueError):
            return 0

    def enum_label(self, value: Any) -> str | None:
        """ENUM-Index -> Name aus der Werteliste."""
        if value is None or not self.value_list:
            return None if value is None else str(value)
        try:
            idx = int(value) - self.enum_offset
        except (TypeError, ValueError):
            return str(value)
        if 0 <= idx < len(self.value_list):
            return str(self.value_list[idx])
        return str(value)


@dataclass
class HmChannel:
    address: str
    index: int
    type: str
    name: str | None
    rooms: list[str]
    params: dict[str, HmParam] = field(default_factory=dict)
    device: HmDevice | None = field(default=None, repr=False)

    @property
    def has_custom_name(self) -> bool:
        """True, wenn der Kanal in der CCU einen eigenen Namen bekommen hat."""
        if not self.name:
            return False
        if self.address.upper() in self.name.upper():
            return False  # Standardname „HmIP-XYZ 000A…:1"
        return not (self.device and self.name == self.device.name)


@dataclass
class HmDevice:
    address: str
    interface: str
    type: str
    firmware: str | None
    name: str | None
    channels: dict[int, HmChannel] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return self.name or f"{self.type} {self.address}"

    @property
    def area(self) -> str | None:
        for ch in sorted(self.channels.values(), key=lambda c: c.index):
            if ch.rooms:
                return ch.rooms[0]
        return None

    def param(self, index: int, name: str) -> HmParam | None:
        ch = self.channels.get(index)
        return ch.params.get(name) if ch else None

    @property
    def unreach(self) -> bool:
        p = self.param(0, "UNREACH")
        return bool(p and p.value)


@dataclass
class HmSysVar:
    """Systemvariable der CCU (Logikschicht/ReGa)."""

    id: str
    name: str
    type: str  # bool | alarm | float | integer | enum | string
    value: Any = None
    value_list: list[str] | None = None
    unit: str | None = None
    min: Any = None
    max: Any = None
    name0: str | None = None
    name1: str | None = None
    timestamp: str | None = None
    removed: bool = False

    @classmethod
    def from_json(cls, d: dict) -> HmSysVar:
        return cls(
            id=str(d.get("id")),
            name=str(d.get("name") or d.get("id")),
            type=str(d.get("type") or "string"),
            value=d.get("value"),
            value_list=d.get("valueList") or None,
            unit=d.get("unit") or None,
            min=d.get("min"),
            max=d.get("max"),
            name0=d.get("name0") or None,
            name1=d.get("name1") or None,
            timestamp=d.get("timestamp"),
        )

    def update_from(self, other: HmSysVar) -> bool:
        """Werte übernehmen; True wenn sich etwas geändert hat."""
        changed = (
            self.value != other.value
            or self.timestamp != other.timestamp
            or self.name != other.name
            or self.value_list != other.value_list
            or self.removed
        )
        for f in ("name", "value", "value_list", "unit", "min", "max", "name0", "name1", "timestamp"):
            setattr(self, f, getattr(other, f))
        self.removed = False
        return changed


def parse_device(d: dict) -> HmDevice:
    dev = HmDevice(
        address=str(d["address"]).upper(),
        interface=str(d.get("interface", "")),
        type=str(d.get("type", "")),
        firmware=d.get("firmware"),
        name=d.get("name"),
    )
    for c in d.get("channels") or []:
        ch = HmChannel(
            address=str(c["address"]).upper(),
            index=int(c.get("index", 0)),
            type=str(c.get("type", "")),
            name=c.get("name"),
            rooms=list(c.get("rooms") or []),
            device=dev,
        )
        for pname, meta in (c.get("values") or {}).items():
            if isinstance(meta, dict):
                ch.params[pname] = HmParam.from_meta(pname, meta)
        dev.channels[ch.index] = ch
    return dev


# --------------------------------------------------------------------------
# Hub
# --------------------------------------------------------------------------

Listener = Callable[[], None]


class HmRestHub:
    """Hält Geräte, verteilt Events an Entitäten, hält den SSE-Stream offen."""

    def __init__(self, hass: HomeAssistant, entry, api: HmRestApi) -> None:
        self.hass = hass
        self.entry = entry
        self.api = api
        self.devices: dict[str, HmDevice] = {}
        self.connected = False
        self._listeners: dict[tuple[str, str], set[Listener]] = {}
        self._conn_listeners: set[Listener] = set()
        self._device_added: list[Callable[[HmDevice], None]] = []
        self.sysvars: dict[str, HmSysVar] = {}
        self.sysvars_ok = False
        self._sysvar_added: list[Callable[[HmSysVar], None]] = []
        self._stop = asyncio.Event()
        self._needs_resync = False
        self.event_count = 0
        self._bad_values: set[tuple[str, str]] = set()

    @property
    def include_virtual_remotes(self) -> bool:
        return bool(self.entry.options.get(CONF_VIRTUAL_REMOTES, False))

    @property
    def scan_minutes(self) -> int:
        return int(self.entry.options.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES))

    @property
    def sysvars_enabled(self) -> bool:
        return bool(self.entry.options.get(CONF_SYSVARS, True))

    @property
    def sysvar_seconds(self) -> int:
        return int(self.entry.options.get(CONF_SYSVAR_SECONDS, DEFAULT_SYSVAR_SECONDS))

    def _wanted(self, raw: dict) -> bool:
        return self.include_virtual_remotes or str(raw.get("type")) not in VIRTUAL_REMOTE_TYPES

    # ---------- Laden ----------

    async def async_load(self) -> None:
        """Erstes Laden aller Geräte inklusive Werten."""
        raw = await self.api.devices(values=True)
        for d in raw:
            if not self._wanted(d):
                continue
            dev = parse_device(d)
            await self._fill_missing_descriptions(dev, d)
            self.devices[dev.address] = dev
        _LOGGER.info("HM-REST: %d Geräte geladen", len(self.devices))

    async def _fill_missing_descriptions(self, dev: HmDevice, raw: dict) -> None:
        """Kanäle, deren Werte nicht gelesen werden konnten, trotzdem anlegen."""
        for c in raw.get("channels") or []:
            ch = dev.channels.get(int(c.get("index", 0)))
            if ch is None or ch.params or "VALUES" not in (c.get("paramsets") or ["VALUES"]):
                continue
            try:
                desc = await self.api.description(ch.address)
            except HmRestError as err:
                _LOGGER.debug("Beschreibung für %s nicht lesbar: %s", ch.address, err)
                continue
            for pname, meta in (desc or {}).items():
                if isinstance(meta, dict):
                    ch.params[pname] = HmParam.from_meta(pname, meta)

    async def async_resync(self) -> None:
        """Nach einem Verbindungsabbruch alle Werte neu holen."""
        try:
            raw = await self.api.devices(values=True)
        except HmRestError as err:
            _LOGGER.warning("HM-REST: Werte konnten nicht neu geladen werden: %s", err)
            return
        for d in raw:
            if not self._wanted(d):
                continue
            new = parse_device(d)
            cur = self.devices.get(new.address)
            if cur is None:
                await self._fill_missing_descriptions(new, d)
                self._add_device(new)
                continue
            for idx, ch in new.channels.items():
                cch = cur.channels.get(idx)
                if not cch:
                    continue
                for pname, p in ch.params.items():
                    if pname in cch.params and p.value is not None:
                        self._set(cch.address, pname, p.value)

    async def async_scan_new_devices(self) -> None:
        """Neu angelernte Geräte erkennen (ohne alle Werte zu lesen)."""
        try:
            raw = await self.api.devices(values=False)
        except HmRestError as err:
            _LOGGER.debug("Gerätescan fehlgeschlagen: %s", err)
            return
        for d in raw:
            addr = str(d.get("address", "")).upper()
            if addr in self.devices or not self._wanted(d):
                continue
            try:
                full = await self.api.device(addr)
            except HmRestError as err:
                _LOGGER.warning("Neues Gerät %s nicht lesbar: %s", addr, err)
                continue
            dev = parse_device(full)
            await self._fill_missing_descriptions(dev, full)
            _LOGGER.info("HM-REST: neues Gerät %s (%s)", dev.title, dev.type)
            self._add_device(dev)

    @callback
    def _add_device(self, dev: HmDevice) -> None:
        self.devices[dev.address] = dev
        for cb in self._device_added:
            cb(dev)

    @callback
    def register_device_callback(self, cb: Callable[[HmDevice], None]) -> Callable[[], None]:
        self._device_added.append(cb)
        return lambda: self._device_added.remove(cb)

    # ---------- Systemvariablen ----------

    async def async_poll_sysvars(self) -> None:
        """Systemvariablen abrufen, Änderungen melden, neue anlegen."""
        try:
            raw = await self.api.sysvars()
        except HmRestError as err:
            if self.sysvars_ok:
                _LOGGER.warning("HM-REST: Systemvariablen nicht lesbar: %s", err)
            self._set_sysvars_ok(False)
            return
        seen: set[str] = set()
        for d in raw or []:
            if not isinstance(d, dict) or d.get("id") is None:
                continue
            new = HmSysVar.from_json(d)
            seen.add(new.id)
            cur = self.sysvars.get(new.id)
            if cur is None:
                self.sysvars[new.id] = new
                for cb in list(self._sysvar_added):
                    cb(new)
            elif cur.update_from(new):
                self._notify(("SYSVAR", new.id))
        for sid, sv in self.sysvars.items():
            if sid not in seen and not sv.removed:
                sv.removed = True
                self._notify(("SYSVAR", sid))
        self._set_sysvars_ok(True)

    @callback
    def _set_sysvars_ok(self, ok: bool) -> None:
        if self.sysvars_ok != ok:
            self.sysvars_ok = ok
            for cb in list(self._conn_listeners):
                cb()

    async def async_set_sysvar(self, sid: str, value: Any) -> None:
        res = await self.api.set_sysvar(sid, value)
        sv = self.sysvars.get(sid)
        if sv is not None and isinstance(res, dict) and res.get("id") is not None:
            sv.update_from(HmSysVar.from_json(res))
            self._notify(("SYSVAR", sid))

    @callback
    def register_sysvar_callback(self, cb: Callable[[HmSysVar], None]) -> Callable[[], None]:
        self._sysvar_added.append(cb)
        return lambda: self._sysvar_added.remove(cb)

    @callback
    def subscribe_sysvar(self, sid: str, cb: Listener) -> Callable[[], None]:
        key = ("SYSVAR", sid)
        self._listeners.setdefault(key, set()).add(cb)
        return lambda: self._listeners.get(key, set()).discard(cb)

    @callback
    def _notify(self, key: tuple[str, str]) -> None:
        for cb in list(self._listeners.get(key, ())):
            cb()

    async def run_sysvar_poller(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(5, self.sysvar_seconds))
                return
            except asyncio.TimeoutError:
                pass
            await self.async_poll_sysvars()

    # ---------- Listener ----------

    @callback
    def subscribe(self, address: str, param: str, cb: Listener) -> Callable[[], None]:
        key = (address.upper(), param)
        self._listeners.setdefault(key, set()).add(cb)

        def _remove() -> None:
            self._listeners.get(key, set()).discard(cb)

        return _remove

    @callback
    def subscribe_connection(self, cb: Listener) -> Callable[[], None]:
        self._conn_listeners.add(cb)
        return lambda: self._conn_listeners.discard(cb)

    @callback
    def _set_connected(self, state: bool) -> None:
        if self.connected == state:
            return
        self.connected = state
        for cb in list(self._conn_listeners):
            cb()

    @callback
    def _set(self, address: str, param: str, value: Any) -> None:
        address = address.upper()
        dev = self.devices.get(address.split(":")[0])
        if dev is not None:
            try:
                idx = int(address.split(":")[1])
            except (IndexError, ValueError):
                idx = -1
            ch = dev.channels.get(idx)
            if ch is not None and param in ch.params:
                ch.params[param].value = value
        for cb in list(self._listeners.get((address, param), ())):
            try:
                cb()
            except Exception:  # noqa: BLE001 – ein fehlerhafter Wert darf den Event-Stream nicht abbrechen
                key = (address, param)
                if key not in self._bad_values:
                    self._bad_values.add(key)
                    _LOGGER.warning(
                        "HM-REST: Wert %r für %s %s konnte nicht übernommen werden (weitere Meldungen dazu unterdrückt)",
                        value, address, param, exc_info=True,
                    )

    @callback
    def handle_event(self, ev: dict) -> None:
        """Ein Event aus dem SSE-Stream verarbeiten."""
        address = str(ev.get("address", ""))
        param = str(ev.get("param", ""))
        if not address or not param or address.upper().startswith("CENTRAL"):
            return
        self.event_count += 1
        self._set(address, param, ev.get("value"))

    # ---------- Schreiben ----------

    async def async_set_value(self, address: str, param: str, value: Any) -> None:
        await self.api.set_value(address, param, value)

    async def async_set_values(self, address: str, values: dict[str, Any]) -> None:
        await self.api.set_values(address, values)

    # ---------- Hintergrund-Tasks ----------

    async def run_events(self) -> None:
        """SSE-Stream dauerhaft offen halten (mit Wiederverbindung)."""
        session = async_get_clientsession(self.hass)
        backoff = 1
        while not self._stop.is_set():
            try:
                async with session.get(
                    self.api.events_url(),
                    headers=self.api.headers,
                    timeout=aiohttp.ClientTimeout(total=None, connect=15, sock_read=90),
                ) as resp:
                    if resp.status in (401, 403):
                        raise HmRestAuthError("API-Key wurde abgelehnt")
                    if resp.status != 200:
                        raise HmRestError(f"Events: HTTP {resp.status}")
                    _LOGGER.info("HM-REST: Event-Stream verbunden")
                    self._set_connected(True)
                    backoff = 1
                    if self._needs_resync:
                        self._needs_resync = False
                        self.hass.async_create_task(self.async_resync())
                    buf: list[str] = []
                    async for raw in resp.content:
                        line = raw.decode("utf-8", "replace").rstrip("\r\n")
                        if line == "":
                            if buf:
                                self._dispatch_sse("\n".join(buf))
                                buf = []
                            continue
                        if line.startswith(":"):
                            continue  # Kommentar / Ping
                        if line.startswith("data:"):
                            buf.append(line[5:].lstrip())
                    _LOGGER.warning("HM-REST: Event-Stream vom Server beendet")
            except asyncio.CancelledError:
                raise
            except HmRestAuthError as err:
                _LOGGER.error("HM-REST: %s", err)
                backoff = 60
            except Exception as err:  # noqa: BLE001
                if self.connected:
                    _LOGGER.warning("HM-REST: Event-Stream unterbrochen: %s", err)
                else:
                    _LOGGER.debug("HM-REST: Verbindung fehlgeschlagen: %s", err)
            self._set_connected(False)
            self._needs_resync = True
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 60)

    @callback
    def _dispatch_sse(self, data: str) -> None:
        try:
            ev = json.loads(data)
        except ValueError:
            _LOGGER.debug("Ungültiges Event: %s", data)
            return
        if isinstance(ev, dict):
            try:
                self.handle_event(ev)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Event konnte nicht verarbeitet werden: %s", data, exc_info=True)

    async def run_scanner(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.scan_minutes * 60)
                return
            except asyncio.TimeoutError:
                pass
            await self.async_scan_new_devices()

    def stop(self) -> None:
        self._stop.set()
