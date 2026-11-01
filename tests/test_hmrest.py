"""Ende-zu-Ende-Test: Integration gegen simuliertes HM-REST."""

from __future__ import annotations

import asyncio

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.hmrest.const import DOMAIN

from .fake_ccu import KEY, FakeHmRest


@pytest.fixture(autouse=True)
def auto_enable(enable_custom_integrations):
    yield


@pytest.fixture
async def fake(socket_enabled):
    f = FakeHmRest()
    await f.start()
    yield f
    await f.stop()


async def _setup(hass: HomeAssistant, fake: FakeHmRest) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "127.0.0.1", "port": fake.port, "api_key": KEY, "ssl": False},
        unique_id=f"127.0.0.1:{fake.port}",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    for _ in range(100):
        await hass.async_block_till_done()
        if entry.runtime_data.connected:
            break
        await asyncio.sleep(0.05)
    assert entry.runtime_data.connected
    await hass.async_block_till_done()
    return entry


async def _wait(hass, cond, msg=""):
    for _ in range(60):
        await hass.async_block_till_done()
        if cond():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"Timeout: {msg}")


async def test_config_flow(hass: HomeAssistant, fake: FakeHmRest) -> None:
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert r["type"] is FlowResultType.FORM
    r2 = await hass.config_entries.flow.async_configure(
        r["flow_id"], {"host": "127.0.0.1", "port": fake.port, "api_key": "falsch", "ssl": False}
    )
    assert r2["errors"] == {"base": "invalid_auth"}
    r3 = await hass.config_entries.flow.async_configure(
        r["flow_id"], {"host": "http://127.0.0.1/", "port": fake.port, "api_key": KEY, "ssl": False}
    )
    assert r3["type"] is FlowResultType.CREATE_ENTRY, r3
    assert r3["data"]["host"] == "127.0.0.1"
    await hass.async_block_till_done()


async def test_entities_and_events(hass: HomeAssistant, fake: FakeHmRest) -> None:
    entry = await _setup(hass, fake)
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    ents = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    ids = sorted(e.entity_id for e in ents)
    print("\n".join(f"{e.entity_id:65} {'AUS' if e.disabled_by else 'an '} {e.original_name}" for e in sorted(ents, key=lambda e: e.entity_id)))

    # Alle Entity-IDs beginnen mit homematic_
    assert all(i.split(".", 1)[1].startswith("homematic_") for i in ids)
    # Virtuelle Fernbedienung ausgelassen
    assert not any("bidcos_rf" in i or "hm_rcv" in i for i in ids)

    devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
    assert len(devices) == 7  # 6 Geräte + „CCU Systemvariablen"
    roll = next(d for d in devices if d.name == "Rollladen Wohnzimmer")
    assert roll.model == "HmIP-BROLL" and roll.manufacturer == "eQ-3"

    # Erwartete Hauptentitäten
    expected = {
        "cover.homematic_rollladen_wohnzimmer": "50",
        "climate.homematic_heizung_bad": "auto",
        "binary_sensor.homematic_fenster_kuche_state": "off",
        "switch.homematic_steckdose_kuhlschrank": "on",
        "sensor.homematic_steckdose_kuhlschrank_power": "85.2",
        "sensor.homematic_steckdose_kuhlschrank_energy_counter": "12345.6",
        "switch.homematic_flurlicht": "off",
        "light.homematic_dimmer_esstisch": "off",
        "sensor.homematic_heizung_bad_actual_temperature": "21.3",
        "binary_sensor.homematic_heizung_bad_low_bat": "off",
        "event.homematic_rollladen_wohnzimmer_1_taste": "unknown",
    }
    for eid, st in expected.items():
        s = hass.states.get(eid)
        assert s is not None, f"{eid} fehlt"
        val = s.attributes.get("current_position") if eid.startswith("cover.") else s.state
        assert str(val) == st, f"{eid}: {val} != {st}"

    # Zweiter/dritter virtueller Empfänger deaktiviert
    rx5 = [e for e in ents if e.unique_id == "00111111111111:5:cover"]
    assert rx5 and rx5[0].disabled_by is not None
    # Diagnose standardmäßig aus
    cfg = ent_reg.async_get("binary_sensor.homematic_heizung_bad_config_pending")
    assert cfg is not None and cfg.disabled_by is not None

    # ---- Events aus dem SSE-Stream ----
    fake.push("00444444444444:6", "POWER", 120.5)
    await _wait(hass, lambda: hass.states.get("sensor.homematic_steckdose_kuhlschrank_power").state == "120.5", "POWER")

    fake.push("00333333333333:1", "STATE", 1)
    await _wait(hass, lambda: hass.states.get("binary_sensor.homematic_fenster_kuche_state").state == "on", "Fenster")

    fake.push("00111111111111:3", "LEVEL", 0.2)
    await _wait(
        hass,
        lambda: hass.states.get("cover.homematic_rollladen_wohnzimmer").attributes.get("current_position") == 20,
        "Rollladen",
    )

    # Tastendruck -> Event-Entität + Bus-Event
    bus = []
    hass.bus.async_listen("homematic_keypress", lambda e: bus.append(e.data))
    fake.push("00111111111111:1", "PRESS_SHORT", True)
    await _wait(hass, lambda: bus, "keypress")
    st = hass.states.get("event.homematic_rollladen_wohnzimmer_1_taste")
    assert st.attributes["event_type"] == "press_short"
    assert bus[0]["param"] == "PRESS_SHORT"

    # Gerät nicht erreichbar -> Entitäten unavailable
    fake.push("00222222222222:0", "UNREACH", True)
    await _wait(hass, lambda: hass.states.get("climate.homematic_heizung_bad").state == "unavailable", "unreach")
    fake.push("00222222222222:0", "UNREACH", False)
    await _wait(hass, lambda: hass.states.get("climate.homematic_heizung_bad").state == "auto", "reach")

    # ---- Schreiben ----
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.homematic_flurlicht"}, blocking=True)
    assert fake.writes[-1] == ("NEQ0000001:1", {"STATE": True})
    await _wait(hass, lambda: hass.states.get("switch.homematic_flurlicht").state == "on", "Flur an")

    await hass.services.async_call(
        "light", "turn_on", {"entity_id": "light.homematic_dimmer_esstisch", "brightness": 128}, blocking=True
    )
    assert fake.writes[-1][0] == "NEQ0000002:1"
    assert abs(fake.writes[-1][1]["LEVEL"] - 0.502) < 0.01
    await _wait(hass, lambda: hass.states.get("light.homematic_dimmer_esstisch").state == "on", "Dimmer")

    await hass.services.async_call(
        "cover", "set_cover_position", {"entity_id": "cover.homematic_rollladen_wohnzimmer", "position": 70}, blocking=True
    )
    assert fake.writes[-1] == ("00111111111111:4", {"LEVEL": 0.7})
    await hass.services.async_call("cover", "stop_cover", {"entity_id": "cover.homematic_rollladen_wohnzimmer"}, blocking=True)
    assert fake.writes[-1] == ("00111111111111:4", {"STOP": True})

    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": "climate.homematic_heizung_bad", "temperature": 22.5}, blocking=True
    )
    assert fake.writes[-1] == ("00222222222222:1", {"SET_POINT_TEMPERATURE": 22.5})
    await _wait(hass, lambda: hass.states.get("climate.homematic_heizung_bad").attributes.get("temperature") == 22.5, "Soll")
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": "climate.homematic_heizung_bad", "hvac_mode": "off"}, blocking=True
    )
    assert fake.writes[-1] == ("00222222222222:1", {"CONTROL_MODE": 1, "SET_POINT_TEMPERATURE": 4.5})
    await _wait(hass, lambda: hass.states.get("climate.homematic_heizung_bad").state == "off", "aus")

    # ---- Verbindungsabbruch und Wiederverbindung ----
    for q in list(fake.queues):
        q.put_nowait(None)
    await _wait(hass, lambda: hass.states.get("switch.homematic_flurlicht").state == "unavailable", "getrennt")
    fake.devices[4]["channels"][1]["values"]["STATE"]["value"] = False  # während Trennung geändert
    await _wait(hass, lambda: hass.states.get("switch.homematic_flurlicht").state == "off", "resync")

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_new_device_detected(hass: HomeAssistant, fake: FakeHmRest) -> None:
    entry = await _setup(hass, fake)
    hub = entry.runtime_data
    from .fake_ccu import ch, maint, p

    addr = "00555555555555"
    fake.devices.append({
        "address": addr, "interface": "HmIP-RF", "type": "HmIP-STHD", "firmware": "1.0", "name": "Thermostat Büro",
        "channels": [
            ch(addr, 0, "MAINTENANCE", maint()),
            ch(addr, 1, "HEATING_CLIMATECONTROL_TRANSCEIVER", {
                "ACTUAL_TEMPERATURE": p("FLOAT", 5, 20.0, unit="°C"),
                "HUMIDITY": p("INTEGER", 5, 45, min=0, max=100),
                "SET_POINT_TEMPERATURE": p("FLOAT", 7, 20.0, unit="°C", min=4.5, max=30.5),
                "SET_POINT_MODE": p("INTEGER", 5, 1, min=0, max=3),
                "CONTROL_MODE": p("INTEGER", 2, min=0, max=3),
            }),
        ],
    })
    await hub.async_scan_new_devices()
    await hass.async_block_till_done()
    s = hass.states.get("climate.homematic_thermostat_buro")
    assert s is not None and s.state == "heat"
    assert s.attributes["current_humidity"] == 45
    assert hass.states.get("sensor.homematic_thermostat_buro_humidity").state == "45"
    assert hass.states.get("sensor.homematic_thermostat_buro_humidity").attributes["unit_of_measurement"] == "%"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_sysvars(hass: HomeAssistant, fake: FakeHmRest) -> None:
    entry = await _setup(hass, fake)
    hub = entry.runtime_data
    dev_reg = dr.async_get(hass)

    exp = {
        "switch.homematic_sysvar_anwesenheit": "on",
        "switch.homematic_sysvar_alarmzone_1": "off",
        "number.homematic_sysvar_aussentemperatur": "12.5",
        "number.homematic_sysvar_zahler": "7",
        "select.homematic_sysvar_modus": "Nacht",
        "text.homematic_sysvar_letzte_meldung": "alles ok",
    }
    for eid, val in exp.items():
        s = hass.states.get(eid)
        assert s is not None, f"{eid} fehlt"
        assert s.state == val, f"{eid}: {s.state} != {val}"
    s = hass.states.get("switch.homematic_sysvar_anwesenheit")
    assert s.attributes["anzeige"] == "anwesend"
    assert hass.states.get("number.homematic_sysvar_aussentemperatur").attributes["unit_of_measurement"] == "°C"
    d = dev_reg.async_get_device(identifiers={("hmrest", f"{entry.entry_id}_sysvars")})
    assert d is not None and d.name == "CCU Systemvariablen"

    # Schreiben aus HA -> sofort aktualisiert (ohne auf den Poll zu warten)
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.homematic_sysvar_anwesenheit"}, blocking=True)
    assert fake.writes[-1] == ("SYSVAR:1234", {"value": False})
    await hass.async_block_till_done()
    s = hass.states.get("switch.homematic_sysvar_anwesenheit")
    assert s.state == "off" and s.attributes["anzeige"] == "abwesend"

    await hass.services.async_call("select", "select_option",
                                   {"entity_id": "select.homematic_sysvar_modus", "option": "Urlaub"}, blocking=True)
    assert fake.writes[-1] == ("SYSVAR:1250", {"value": 2})
    await hass.services.async_call("number", "set_value",
                                   {"entity_id": "number.homematic_sysvar_aussentemperatur", "value": 3.25}, blocking=True)
    assert fake.writes[-1] == ("SYSVAR:1240", {"value": 3.25})
    await hass.services.async_call("text", "set_value",
                                   {"entity_id": "text.homematic_sysvar_letzte_meldung", "value": "Fenster offen"}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get("text.homematic_sysvar_letzte_meldung").state == "Fenster offen"
    assert hass.states.get("select.homematic_sysvar_modus").state == "Urlaub"

    # Änderung in der CCU + neue Variable -> beim nächsten Abruf
    fake.sysvar_list[0]["value"] = True
    fake.sysvar_list.append({"id": "1300", "name": "Neue Variable", "type": "bool", "value": True, "timestamp": "x"})
    await hub.async_poll_sysvars()
    await hass.async_block_till_done()
    assert hass.states.get("switch.homematic_sysvar_anwesenheit").state == "on"
    assert hass.states.get("switch.homematic_sysvar_neue_variable").state == "on"

    # ReGa nicht erreichbar -> nur Systemvariablen unavailable, Geräte bleiben
    fake.sysvar_fail = True
    await hub.async_poll_sysvars()
    await hass.async_block_till_done()
    assert hass.states.get("select.homematic_sysvar_modus").state == "unavailable"
    assert hass.states.get("switch.homematic_flurlicht").state != "unavailable"
    fake.sysvar_fail = False

    # Gelöschte Variable -> unavailable
    fake.sysvar_list = [v for v in fake.sysvar_list if v["id"] != "1241"]
    await hub.async_poll_sysvars()
    await hass.async_block_till_done()
    assert hass.states.get("number.homematic_sysvar_zahler").state == "unavailable"
    assert hass.states.get("select.homematic_sysvar_modus").state == "Urlaub"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_sysvars_disabled(hass: HomeAssistant, fake: FakeHmRest) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "127.0.0.1", "port": fake.port, "api_key": KEY, "ssl": False},
        options={"include_sysvars": False},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("switch.homematic_sysvar_anwesenheit") is None
    assert hass.states.get("switch.homematic_flurlicht") is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_options_flow(hass: HomeAssistant, fake: FakeHmRest) -> None:
    entry = await _setup(hass, fake)
    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["type"] is FlowResultType.FORM
    r = await hass.config_entries.options.async_configure(
        r["flow_id"],
        {"include_virtual_remotes": False, "include_sysvars": True, "sysvar_poll_seconds": 15, "device_scan_minutes": 10},
    )
    assert r["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["sysvar_poll_seconds"] == 15
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


# ---------- Wochenprogramm ----------


async def test_week_program_services(hass: HomeAssistant, fake: FakeHmRest) -> None:
    from homeassistant.exceptions import ServiceValidationError

    await _setup(hass, fake)
    dev_reg = dr.async_get(hass)
    dev = dev_reg.async_get_device(identifiers={(DOMAIN, fake.WP_DEVICE)})
    assert dev is not None
    assert hass.services.has_service(DOMAIN, "set_week_program")

    # Textform, Gerät, Werktage, Profil 2 aktivieren
    await hass.services.async_call(DOMAIN, "set_week_program", {
        "device_id": dev.id, "days": ["workdays"], "schedule": "06:00 17; 22:00 21,5; 24:00 17",
        "profile": 2, "activate": True}, blocking=True)
    addr, body = fake.wp_writes[-1]
    assert addr == fake.WP_DEVICE
    assert body == {"profile": 2, "activeProfile": 2, "days": {"workdays": [
        {"end": "06:00", "temp": 17.0}, {"end": "22:00", "temp": 21.5}, {"end": "24:00", "temp": 17.0}]}}

    # Listenform über die Klima-Entität, mehrere Tage
    ent_reg = er.async_get(hass)
    climate_id = next(e.entity_id for e in er.async_entries_for_device(ent_reg, dev.id) if e.domain == "climate")
    await hass.services.async_call(DOMAIN, "set_week_program", {
        "entity_id": climate_id, "days": ["saturday", "sunday"],
        "schedule": [{"end": "08:00", "temp": 17}, {"end": 1440, "temp": "20,5"}]}, blocking=True)
    _, body = fake.wp_writes[-1]
    assert body == {"days": {"saturday,sunday": [{"end": "08:00", "temp": 17.0}, {"end": 1440, "temp": 20.5}]}}

    # Fehler des Add-ons kommen als verständlicher Validierungsfehler an
    with pytest.raises(ServiceValidationError, match="24:00"):
        await hass.services.async_call(DOMAIN, "set_week_program", {
            "device_id": dev.id, "days": ["monday"], "schedule": "06:00 17"}, blocking=True)
    # Plan ohne Tage / Aktivieren ohne Profil
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "set_week_program", {
            "device_id": dev.id, "schedule": "24:00 20"}, blocking=True)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "set_week_program", {"device_id": dev.id, "activate": True}, blocking=True)
    # Gerät ohne Wochenprogramm
    other = dev_reg.async_get_device(identifiers={(DOMAIN, "00111111111111")})
    with pytest.raises(ServiceValidationError, match="kein Wochenprogramm"):
        await hass.services.async_call(DOMAIN, "set_week_program", {
            "device_id": other.id, "days": ["all"], "schedule": "24:00 20"}, blocking=True)

    # Lesen mit Antwort
    res = await hass.services.async_call(DOMAIN, "get_week_program", {"device_id": dev.id},
                                         blocking=True, return_response=True)
    (info,) = res.values()
    assert info["active_profile"] == 1 and info["profiles"] == [1, 2, 3]
    assert info["program"]["1"]["monday"][1] == {"end": "22:00", "temp": 21.0}


async def test_bad_value_does_not_break_stream(hass: HomeAssistant, fake: FakeHmRest) -> None:
    """Ein Wert, an dem eine Entität scheitert, darf den Event-Stream nicht abbrechen."""
    entry = await _setup(hass, fake)
    hub = entry.runtime_data
    calls = []

    def boom():
        raise ValueError("could not convert string to float: ''")

    hub.subscribe("00444444444444:6", "POWER", boom)
    hub.subscribe("00444444444444:6", "POWER", lambda: calls.append(1))
    fake.push("00444444444444:6", "POWER", "")
    fake.push("00444444444444:6", "POWER", 12.5)
    await _wait(hass, lambda: len(calls) >= 2, "Events nach fehlerhaftem Wert")
    assert hub.connected
