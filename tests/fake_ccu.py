"""Simuliertes HM-REST-Add-on (gleiches JSON-Format wie das echte) für Tests."""

from __future__ import annotations

import asyncio
import copy
import json

from aiohttp import web

KEY = "testkey"


def p(t, ops, value=None, **kw):
    m = {"type": t, "readable": bool(ops & 1), "writable": bool(ops & 2), "event": bool(ops & 4), "flags": 1}
    m.update(kw)
    if ops & 1:
        m["value"] = value
    return m


def maint(*, bat=True, rssi=True):
    v = {"UNREACH": p("BOOL", 5, False), "CONFIG_PENDING": p("BOOL", 5, False)}
    if bat:
        v["LOW_BAT"] = p("BOOL", 5, False)
        v["OPERATING_VOLTAGE"] = p("FLOAT", 5, 2.9, unit="V", min=0, max=25.2)
    if rssi:
        v["RSSI_DEVICE"] = p("INTEGER", 5, -60, min=-128, max=127)
    return v


def ch(addr, idx, typ, values, name=None, rooms=None):
    c = {"address": f"{addr}:{idx}", "interface": "HmIP-RF", "index": idx, "parent": addr, "type": typ,
         "paramsets": ["MASTER", "VALUES"], "values": values}
    if name:
        c["name"] = name
    if rooms:
        c["rooms"] = rooms
    return c


def build_devices():
    roll = "00111111111111"
    etrv = "00222222222222"
    swdo = "00333333333333"
    psm = "00444444444444"
    sw = "NEQ0000001"
    dim = "NEQ0000002"
    rcv = "BidCoS-RF"
    devs = [
        {
            "address": roll, "interface": "HmIP-RF", "type": "HmIP-BROLL", "firmware": "2.2.4",
            "name": "Rollladen Wohnzimmer",
            "channels": [
                ch(roll, 0, "MAINTENANCE", maint(bat=False)),
                ch(roll, 1, "KEY_TRANSMITTER", {"PRESS_SHORT": p("ACTION", 4), "PRESS_LONG": p("ACTION", 4)},
                   rooms=["Wohnzimmer"]),
                ch(roll, 3, "SHUTTER_TRANSMITTER", {
                    "LEVEL": p("FLOAT", 5, 0.5, unit="100%", min=0, max=1.01),
                    "ACTIVITY_STATE": p("ENUM", 5, 3, min=0, max=3, valueList=["UNKNOWN", "UP", "DOWN", "STABLE"]),
                }, rooms=["Wohnzimmer"]),
                *[ch(roll, i, "SHUTTER_VIRTUAL_RECEIVER", {
                    "LEVEL": p("FLOAT", 7, 0.5, unit="100%", min=0, max=1.01),
                    "STOP": p("ACTION", 2),
                }) for i in (4, 5, 6)],
            ],
        },
        {
            "address": etrv, "interface": "HmIP-RF", "type": "HmIP-eTRV-2", "firmware": "2.2.8",
            "name": "Heizung Bad",
            "channels": [
                ch(etrv, 0, "MAINTENANCE", maint()),
                ch(etrv, 1, "HEATING_CLIMATECONTROL_TRANSCEIVER", {
                    "ACTUAL_TEMPERATURE": p("FLOAT", 5, 21.3, unit="°C", min=-3276.8, max=3276.7),
                    "SET_POINT_TEMPERATURE": p("FLOAT", 7, 21.0, unit="°C", min=4.5, max=30.5),
                    "SET_POINT_MODE": p("INTEGER", 5, 0, min=0, max=3),
                    "CONTROL_MODE": p("INTEGER", 2, min=0, max=3),
                    "BOOST_MODE": p("BOOL", 7, False),
                    "LEVEL": p("FLOAT", 5, 0.3, unit="100%", min=0, max=1.01),
                    "WINDOW_STATE": p("ENUM", 7, 0, min=0, max=1, valueList=["CLOSED", "OPEN"]),
                }, rooms=["Bad"]),
            ],
        },
        {
            "address": swdo, "interface": "HmIP-RF", "type": "HmIP-SWDO", "firmware": "1.2.0",
            "name": "Fenster Küche",
            "channels": [
                ch(swdo, 0, "MAINTENANCE", maint()),
                ch(swdo, 1, "SHUTTER_CONTACT", {"STATE": p("ENUM", 5, 0, min=0, max=1, valueList=["CLOSED", "OPEN"])}),
            ],
        },
        {
            "address": psm, "interface": "HmIP-RF", "type": "HmIP-PSM", "firmware": "2.6.2",
            "name": "Steckdose Kühlschrank",
            "channels": [
                ch(psm, 0, "MAINTENANCE", maint(bat=False)),
                ch(psm, 2, "SWITCH_TRANSMITTER", {"STATE": p("BOOL", 5, True)}),
                *[ch(psm, i, "SWITCH_VIRTUAL_RECEIVER", {
                    "STATE": p("BOOL", 7, True),
                    "ON_TIME": p("FLOAT", 2, min=0, max=111600, unit="s"),
                }) for i in (3, 4, 5)],
                ch(psm, 6, "ENERGIE_METER_TRANSMITTER", {
                    "POWER": p("FLOAT", 5, 85.2, unit="W", min=0, max=163830),
                    "ENERGY_COUNTER": p("FLOAT", 5, 12345.6, unit="Wh", min=0, max=21474836.47),
                    "VOLTAGE": p("FLOAT", 5, 231.2, unit="V", min=0, max=255),
                    "CURRENT": p("FLOAT", 5, 410.0, unit="mA", min=0, max=50000),
                    "FREQUENCY": p("FLOAT", 5, 50.01, unit="Hz", min=48.72, max=51.27),
                }),
            ],
        },
        {
            "address": sw, "interface": "BidCos-RF", "type": "HM-LC-Sw1-Pl-2", "firmware": "2.5",
            "name": "Licht Flur",
            "channels": [
                ch(sw, 0, "MAINTENANCE", {"UNREACH": p("BOOL", 5, False), "STICKY_UNREACH": p("BOOL", 7, False)}),
                ch(sw, 1, "SWITCH", {
                    "STATE": p("BOOL", 7, False),
                    "ON_TIME": p("FLOAT", 2, min=0, max=85825945.6, unit="s"),
                    "INHIBIT": p("BOOL", 7, False),
                    "WORKING": p("BOOL", 5, False),
                }, name="Flurlicht"),
            ],
        },
        {
            "address": dim, "interface": "BidCos-RF", "type": "HM-LC-Dim1T-Pl-3", "firmware": "2.9",
            "name": "Dimmer Esstisch",
            "channels": [
                ch(dim, 0, "MAINTENANCE", {"UNREACH": p("BOOL", 5, False)}),
                ch(dim, 1, "DIMMER", {
                    "LEVEL": p("FLOAT", 7, 0.0, unit="100%", min=0, max=1),
                    "OLD_LEVEL": p("ACTION", 2),
                    "RAMP_TIME": p("FLOAT", 2, min=0, max=85825945.6, unit="s"),
                    "DIRECTION": p("ENUM", 5, 0, min=0, max=3, valueList=["NONE", "UP", "DOWN", "UNDEFINED"]),
                }),
            ],
        },
        {
            "address": rcv, "interface": "BidCos-RF", "type": "HM-RCV-50", "firmware": "3.71",
            "channels": [ch(rcv, i, "VIRTUAL_KEY", {"PRESS_SHORT": p("ACTION", 6)}) for i in (1, 2)],
        },
    ]
    for d in devs:
        for c in d["channels"]:
            c["interface"] = d["interface"]
    return devs


def build_sysvars():
    return [
        {"id": "1234", "name": "Anwesenheit", "type": "bool", "value": True, "name0": "abwesend",
         "name1": "anwesend", "timestamp": "2026-10-11 16:00:00"},
        {"id": "1235", "name": "Alarmzone 1", "type": "alarm", "value": False, "name0": "nicht ausgelöst",
         "name1": "ausgelöst", "timestamp": "2026-10-11 16:00:00"},
        {"id": "1240", "name": "Außentemperatur", "type": "float", "value": 12.5, "unit": "°C", "min": -50,
         "max": 60, "timestamp": "2026-10-11 16:00:00"},
        {"id": "1241", "name": "Zähler", "type": "integer", "value": 7, "timestamp": "2026-10-11 16:00:00"},
        {"id": "1250", "name": "Modus", "type": "enum", "value": 1, "valueList": ["Tag", "Nacht", "Urlaub"],
         "timestamp": "2026-10-11 16:00:00"},
        {"id": "1260", "name": "Letzte Meldung", "type": "string", "value": "alles ok",
         "timestamp": "2026-10-11 16:00:00"},
    ]


class FakeHmRest:
    def __init__(self) -> None:
        self.sysvar_list = build_sysvars()
        self.sysvar_fail = False
        self.devices = build_devices()
        self.writes: list[tuple[str, dict]] = []
        self.queues: set[asyncio.Queue] = set()
        self.app = web.Application()
        self.app.router.add_get("/api/info", self.info)
        self.app.router.add_get("/api/devices", self.list)
        self.app.router.add_get("/api/devices/{addr}", self.one)
        self.app.router.add_put("/api/devices/{addr}/values/{param}", self.put_one)
        self.app.router.add_put("/api/devices/{addr}/values", self.put_many)
        self.app.router.add_get("/api/events", self.events)
        self.app.router.add_get("/api/sysvars", self.sysvars)
        self.app.router.add_put("/api/sysvars/{ref}", self.set_sysvar)
        self.app.router.add_get("/api/devices/{addr}/weekprogram", self.get_wp)
        self.app.router.add_put("/api/devices/{addr}/weekprogram", self.put_wp)
        self.wp_writes: list[tuple[str, dict]] = []
        self.runner: web.AppRunner | None = None
        self.port = 0

    async def start(self) -> None:
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        for q in list(self.queues):
            q.put_nowait(None)
        if self.runner:
            await self.runner.cleanup()

    def _auth(self, req) -> None:
        if req.headers.get("X-API-Key") != KEY:
            raise web.HTTPUnauthorized(text=json.dumps({"error": "API-Key fehlt oder falsch"}))

    async def info(self, req):
        self._auth(req)
        return web.json_response({"name": "HM-REST", "version": "1.3.0", "interfaces": []})

    def _strip(self, d, full):
        d = copy.deepcopy(d)
        if not full:
            for c in d["channels"]:
                c.pop("values", None)
        return d

    async def list(self, req):
        self._auth(req)
        full = req.query.get("values") == "full"
        return web.json_response([self._strip(d, full) for d in self.devices])

    async def one(self, req):
        self._auth(req)
        for d in self.devices:
            if d["address"] == req.match_info["addr"]:
                return web.json_response(self._strip(d, True))
        raise web.HTTPNotFound()

    def _apply(self, addr, values):
        dev, idx = addr.split(":")
        for d in self.devices:
            if d["address"] != dev:
                continue
            for c in d["channels"]:
                if str(c["index"]) == idx:
                    for k, v in values.items():
                        meta = c["values"].get(k)
                        if meta is None:
                            raise web.HTTPNotFound(text=json.dumps({"error": f"{k} fehlt"}))
                        if meta["readable"]:
                            meta["value"] = v
                            self.push(addr, k, v)
                    return
        raise web.HTTPNotFound()

    async def put_one(self, req):
        self._auth(req)
        body = await req.json()
        addr, param = req.match_info["addr"], req.match_info["param"]
        self.writes.append((addr, {param: body["value"]}))
        self._apply(addr, {param: body["value"]})
        return web.json_response({"ok": True})

    async def put_many(self, req):
        self._auth(req)
        body = await req.json()
        addr = req.match_info["addr"]
        self.writes.append((addr, body))
        self._apply(addr, body)
        return web.json_response({"ok": True})

    async def sysvars(self, req):
        self._auth(req)
        if self.sysvar_fail:
            raise web.HTTPBadGateway(text=json.dumps({"error": "ReGa nicht erreichbar"}))
        return web.json_response(self.sysvar_list)

    async def set_sysvar(self, req):
        self._auth(req)
        body = await req.json()
        ref = req.match_info["ref"]
        for sv in self.sysvar_list:
            if sv["id"] == ref or sv["name"] == ref:
                v = body["value"]
                if sv["type"] in ("bool", "alarm"):
                    v = bool(v)
                elif sv["type"] in ("enum", "integer"):
                    v = int(v)
                elif sv["type"] == "float":
                    v = float(v)
                sv["value"] = v
                sv["timestamp"] = "2026-10-11 17:30:00"
                self.writes.append(("SYSVAR:" + sv["id"], {"value": body["value"]}))
                return web.json_response(sv)
        raise web.HTTPNotFound(text=json.dumps({"error": "nicht gefunden"}))

    # Wochenprogramm (gleiches Format wie HM-REST /weekprogram)
    WP_DEVICE = "00222222222222"

    async def get_wp(self, req):
        self._auth(req)
        addr = req.match_info["addr"].split(":")[0].upper()
        if addr != self.WP_DEVICE:
            raise web.HTTPNotFound(text=json.dumps({"error": f"{addr} hat kein Wochenprogramm"}))
        day = [{"end": "06:00", "temp": 17.0}, {"end": "22:00", "temp": 21.0}, {"end": "24:00", "temp": 17.0}]
        days = {d: day for d in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")}
        return web.json_response({"device": addr, "address": f"{addr}:1", "prefixed": True, "profiles": [1, 2, 3],
                                  "activeProfile": 1, "slots": 13, "minTemp": 5.0, "maxTemp": 30.5,
                                  "program": {"1": days, "2": days, "3": days}})

    async def put_wp(self, req):
        self._auth(req)
        addr = req.match_info["addr"].upper()
        if addr.split(":")[0] != self.WP_DEVICE:
            raise web.HTTPNotFound(text=json.dumps({"error": f"{addr} hat kein Wochenprogramm"}))
        body = await req.json()
        for key, slots in (body.get("days") or {}).items():
            if slots[-1]["end"] not in ("24:00", 1440):
                raise web.HTTPBadRequest(text=json.dumps({"error": f"{key}: der letzte Abschnitt muss um 24:00 enden"}))
        self.wp_writes.append((addr, body))
        return web.json_response({"ok": True})

    def push(self, address, param, value) -> None:
        ev = {"interface": "HmIP-RF", "address": address, "param": param, "value": value, "ts": "2026-10-11T17:00:00Z"}
        for q in list(self.queues):
            q.put_nowait(ev)

    async def events(self, req):
        self._auth(req)
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(req)
        await resp.write(b": verbunden\n\n")
        q: asyncio.Queue = asyncio.Queue()
        self.queues.add(q)
        try:
            while True:
                ev = await q.get()
                if ev is None:
                    break
                await resp.write(f"data: {json.dumps(ev)}\n\n".encode())
        finally:
            self.queues.discard(q)
        return resp
