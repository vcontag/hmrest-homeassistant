"""Ordnet HomeMatic-Kanäle/Datenpunkte den Home-Assistant-Plattformen zu."""

from __future__ import annotations

from dataclasses import dataclass, field

from homeassistant.util import slugify

from .const import ENTITY_PREFIX
from .hub import HmChannel, HmDevice, HmParam

# Datenpunkte auf Kanal 0 (Wartungskanal), die standardmäßig aktiv sind
CH0_ENABLED = {"LOW_BAT", "LOWBAT", "UNREACH", "OPERATING_VOLTAGE", "SABOTAGE", "ERROR_SABOTAGE", "RSSI_DEVICE"}

# Datenpunkte, die angelegt, aber standardmäßig deaktiviert werden
DISABLED_PARAMS = {
    "AES_KEY", "INHIBIT", "INSTALL_TEST", "CONFIG_PENDING", "UPDATE_PENDING", "DUTY_CYCLE", "RSSI_PEER",
    "DEVICE_IN_BOOTLOADER", "ERROR_CODE", "SECTION", "SECTION_STATUS", "PROCESS", "LEVEL_STATUS",
    "COMBINED_PARAMETER", "WORKING", "STATE_UNCERTAIN", "ERROR", "STATUS", "PARTY_MODE_SUBMIT",
    "DEW_POINT_ALARM", "FROST_PROTECTION", "QUICK_VETO_TIME", "ACTIVITY_STATE", "DIRECTION",
    "ERROR_JAMMED", "ERROR_OVERHEAT", "ERROR_POWER_FAILURE", "ERROR_REDUCED", "ERROR_OVERLOAD",
    "ERROR_UNDERVOLTAGE", "ERROR_DEGRADED_CHAMBER", "ERROR_COMMUNICATION_SENSOR",
}

# Diese Parameter sind reine Hilfsparameter (z.B. Einschaltdauer zusammen mit STATE)
WRITE_HELPER_PREFIXES = ("ON_TIME", "RAMP_TIME", "DURATION_", "RAMP_STOP", "OFF_DELAY", "ON_DELAY", "PARTY_")

PARAM_NAMES = {
    "ACTUAL_TEMPERATURE": "Temperatur",
    "TEMPERATURE": "Temperatur",
    "HUMIDITY": "Luftfeuchte",
    "ACTUAL_HUMIDITY": "Luftfeuchte",
    "LOW_BAT": "Batterie",
    "LOWBAT": "Batterie",
    "UNREACH": "Nicht erreichbar",
    "STICKY_UNREACH": "War nicht erreichbar",
    "OPERATING_VOLTAGE": "Betriebsspannung",
    "BATTERY_STATE": "Batteriespannung",
    "RSSI_DEVICE": "Signal Gerät",
    "RSSI_PEER": "Signal CCU",
    "POWER": "Leistung",
    "ENERGY_COUNTER": "Energiezähler",
    "CURRENT": "Strom",
    "VOLTAGE": "Spannung",
    "FREQUENCY": "Frequenz",
    "ILLUMINATION": "Helligkeit",
    "CURRENT_ILLUMINATION": "Helligkeit",
    "AVERAGE_ILLUMINATION": "Helligkeit Mittel",
    "BRIGHTNESS": "Helligkeit",
    "MOTION": "Bewegung",
    "PRESENCE_DETECTION_STATE": "Anwesenheit",
    "STATE": "Status",
    "LEVEL": "Level",
    "LEVEL_2": "Lamellen",
    "SABOTAGE": "Sabotage",
    "ERROR_SABOTAGE": "Sabotage",
    "DUTY_CYCLE": "Duty Cycle",
    "CONFIG_PENDING": "Konfiguration ausstehend",
    "UPDATE_PENDING": "Update ausstehend",
    "WINDOW_STATE": "Fenster",
    "BOOST_MODE": "Boost",
    "BOOST_TIME": "Boost-Restzeit",
    "SET_POINT_MODE": "Modus",
    "VALVE_STATE": "Ventilstatus",
    "VALVE_ADAPTION": "Ventil-Adaption",
    "WIND_SPEED": "Windgeschwindigkeit",
    "WIND_DIRECTION": "Windrichtung",
    "RAINING": "Regen",
    "RAIN_COUNTER": "Regenmenge",
    "SUNSHINEDURATION": "Sonnenscheindauer",
    "AIR_PRESSURE": "Luftdruck",
    "ERROR_CODE": "Fehlercode",
    "ACTIVITY_STATE": "Aktivität",
    "SMOKE_DETECTOR_ALARM_STATUS": "Rauchalarm",
    "WATERLEVEL_DETECTED": "Wasserstand",
    "MOISTURE_DETECTED": "Feuchtigkeit",
    "WATER_LEVEL": "Wasserstand",
}


@dataclass
class Spec:
    """Beschreibung einer zu erzeugenden Entität."""

    platform: str
    kind: str  # generic | switch | light | cover | climate | event
    channel: HmChannel  # Kanal, an den Befehle gehen
    param: str | None = None
    state_channel: HmChannel | None = None  # Kanal, aus dem der Zustand gelesen wird
    enabled: bool = True
    category: str | None = None  # "diagnostic" | "config"
    name: str | None = None
    object_id: str = ""
    unique_id: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def device(self) -> HmDevice:
        return self.channel.device  # type: ignore[return-value]

    @property
    def state(self) -> HmChannel:
        return self.state_channel or self.channel

    def p(self, name: str) -> HmParam | None:
        """Parameter bevorzugt vom Zustandskanal, sonst vom Befehlskanal."""
        return self.state.params.get(name) or self.channel.params.get(name)


def param_label(name: str) -> str:
    return PARAM_NAMES.get(name) or name.replace("_", " ").title()


def _generic_platform(p: HmParam) -> str | None:
    t = p.type
    if t == "ACTION":
        if p.writable:
            return "button"
        return "binary_sensor" if p.event else None
    if t == "BOOL":
        if p.writable and p.readable:
            return "switch"
        if p.writable:
            return "button"
        return "binary_sensor"
    if t == "ENUM":
        if p.writable:
            return "select"
        if p.value_list and [str(v).upper() for v in p.value_list] == ["CLOSED", "OPEN"]:
            return "binary_sensor"
        return "sensor"
    if t in ("FLOAT", "INTEGER"):
        return "number" if p.writable else "sensor"
    if t == "STRING":
        return "text" if p.writable else "sensor"
    return None


def build_specs(dev: HmDevice) -> list[Spec]:
    """Alle Entitäten eines Geräts bestimmen."""
    specs: list[Spec] = []
    chans = sorted(dev.channels.values(), key=lambda c: c.index)
    consumed: set[tuple[int, str]] = set()
    dev_slug = slugify(dev.title)

    # ----- HmIP: Sender-/virtuelle Empfängerkanäle gruppieren -----
    state_of: dict[int, HmChannel] = {}
    secondary: set[int] = set()
    for ch in chans:
        if not ch.type.endswith("_VIRTUAL_RECEIVER"):
            continue
        prefix = ch.type[: -len("_VIRTUAL_RECEIVER")]
        txs = [c for c in chans if c.index < ch.index and c.type == f"{prefix}_TRANSMITTER"]
        if not txs:
            continue
        tx = txs[-1]
        state_of[ch.index] = tx
        first_rx = min(c.index for c in chans if c.index > tx.index and c.type == ch.type)
        if ch.index != first_rx:
            secondary.add(ch.index)

    def naming(ch: HmChannel, alt: HmChannel | None, need_index: bool) -> tuple[str, str | None]:
        """(Slug-Basis für die entity_id, Kanal-Bezeichnung im Anzeigenamen)."""
        for c in (ch, alt):
            if c is not None and c.has_custom_name:
                return slugify(c.name or ""), c.name
        if need_index:
            return f"{dev_slug}_{ch.index}", f"Kanal {ch.index}"
        return dev_slug, None

    def ids(spec: Spec, base: str, suffix: str | None) -> None:
        spec.object_id = f"{ENTITY_PREFIX}_{base}" + (f"_{slugify(suffix)}" if suffix else "")
        spec.unique_id = f"{spec.channel.address}:{spec.param or spec.kind}"

    # ----- Aktoren (primäre Entitäten) -----
    actors: list[Spec] = []
    for ch in chans:
        st = state_of.get(ch.index)
        enabled = ch.index not in secondary
        ps = ch.params
        spec: Spec | None = None

        sp = ps.get("SET_POINT_TEMPERATURE") or ps.get("SET_TEMPERATURE")
        level = ps.get("LEVEL")
        state = ps.get("STATE")
        dim_level = level is not None and level.writable and level.type == "FLOAT"
        if sp is not None and sp.writable:
            spec = Spec("climate", "climate", ch, state_channel=st, enabled=enabled)
            for n in ("SET_POINT_TEMPERATURE", "SET_TEMPERATURE", "SET_POINT_MODE", "CONTROL_MODE",
                      "AUTO_MODE", "MANU_MODE", "BOOST_MODE", "COMFORT_MODE", "LOWERING_MODE"):
                consumed.add((ch.index, n))
        elif dim_level and ("DIMMER" in ch.type or "OLD_LEVEL" in ps):
            spec = Spec("light", "light", ch, state_channel=st, enabled=enabled)
            for n in ("LEVEL", "OLD_LEVEL"):
                consumed.add((ch.index, n))
                if st:
                    consumed.add((st.index, n))
        elif dim_level and "STOP" in ps:
            spec = Spec("cover", "cover", ch, state_channel=st, enabled=enabled)
            for n in ("LEVEL", "STOP", "LEVEL_2"):
                consumed.add((ch.index, n))
                if st:
                    consumed.add((st.index, n))
        elif state is not None and state.writable and state.type == "BOOL":
            spec = Spec("switch", "switch", ch, state_channel=st, enabled=enabled)
            consumed.add((ch.index, "STATE"))
            if st:
                consumed.add((st.index, "STATE"))
        if spec:
            actors.append(spec)

    # Mehrere gleichartige Aktoren im Gerät -> Kanalnummer anhängen
    for spec in actors:
        same = [a for a in actors if a.platform == spec.platform and a.enabled]
        base, label = naming(spec.channel, spec.state_channel, not spec.enabled or len(same) > 1)
        spec.name = label
        ids(spec, base, None)
        specs.append(spec)

    # ----- Tasten -> Event-Entität -----
    for ch in chans:
        presses = [n for n, p in ch.params.items() if n.startswith("PRESS_") and (p.event or not p.readable)]
        if not presses:
            continue
        base, label = naming(ch, None, True)
        if not ch.has_custom_name:
            label = f"Taste {ch.index}"
        spec = Spec("event", "event", ch, name=label, extra={"types": sorted(presses)})
        ids(spec, base, "taste")
        spec.unique_id = f"{ch.address}:EVENT"
        specs.append(spec)
        for n in presses:
            consumed.add((ch.index, n))

    # ----- Alle übrigen Datenpunkte generisch -----
    remaining = [
        (ch, name, p)
        for ch in chans
        for name, p in sorted(ch.params.items())
        if (ch.index, name) not in consumed and _generic_platform(p) is not None
    ]
    count: dict[str, int] = {}
    for _ch, name, _p in remaining:
        count[name] = count.get(name, 0) + 1

    for ch, name, p in remaining:
        platform = _generic_platform(p)
        enabled = True
        category = None
        if ch.index == 0:
            category = "config" if p.writable else "diagnostic"
            enabled = name in CH0_ENABLED
        if name in DISABLED_PARAMS or ch.index in secondary or ch.index in state_of:
            enabled = False
        if name.startswith(WRITE_HELPER_PREFIXES):
            enabled = False
            category = category or "config"
        if p.writable and not p.readable and p.type not in ("ACTION", "BOOL"):
            enabled = False
        base, label = naming(ch, None, count[name] > 1)
        plabel = param_label(name)
        spec = Spec(
            platform,  # type: ignore[arg-type]
            "generic",
            ch,
            param=name,
            enabled=enabled,
            category=category,
            name=f"{label} {plabel}" if label else plabel,
        )
        ids(spec, base, name)
        specs.append(spec)
    return specs
