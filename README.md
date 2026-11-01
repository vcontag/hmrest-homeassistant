# HomeMatic (HM-REST) – Home-Assistant-Integration

Bindet alle Geräte der CCU über das Add-on **HM-REST** ein. Beim Start werden alle Geräte
mit ihren Werten per REST geladen, danach kommen Änderungen sofort über den Event-Stream
(`/api/events`, Server-Sent Events) – kein Polling.

## Installation

Voraussetzung: das CCU-Add-on [HM-REST](https://github.com/vcontag/hmrest) läuft auf der CCU
(für Wochenprogramme ≥ 1.6.0).

### Über HACS (empfohlen)
1. HACS öffnen → Menü ⋮ oben rechts → **Benutzerdefinierte Repositories**.
2. Repository `https://github.com/vcontag/hmrest-homeassistant`, Typ **Integration** → *Hinzufügen*.
3. In HACS nach **HomeMatic (HM-REST)** suchen → *Herunterladen*.
4. Home Assistant neu starten.
5. *Einstellungen → Geräte & Dienste → Integration hinzufügen → „HomeMatic (HM-REST)"*,
   CCU-Adresse, Port (8099) und API-Key eintragen.

Neue Versionen zeigt HACS danach automatisch als Update an (auch unter *Einstellungen → Updates*).

### Manuell
`hmrest-install-<version>.zip` unter *Releases* herunterladen, im Config-Ordner von Home Assistant entpacken
(es entsteht `custom_components/hmrest`), neu starten und wie oben ab Schritt 5 einrichten.

## Was angelegt wird
- Ein HA-Gerät pro HomeMatic-Gerät (Name, Typ, Firmware, Raum als Bereichsvorschlag).
- Alle Entity-IDs beginnen mit `homematic_`, z.B. `cover.homematic_rollladen_wohnzimmer`,
  `climate.homematic_heizung_bad`, `sensor.homematic_steckdose_kuhlschrank_power`.
  Hat ein Kanal in der CCU einen eigenen Namen, wird dieser verwendet.
- Aktoren: Schalter, Dimmer (Licht), Rollläden/Jalousien (inkl. Lamellen), Thermostate
  (Auto / Manuell / Aus, Boost).
- Alle übrigen Datenpunkte: Sensoren, Binärsensoren, Number, Select, Text, Buttons.
- Tasten: Event-Entität (`event.homematic_…_taste`) und zusätzlich das Bus-Event
  `homematic_keypress` (Felder: device, channel, address, param, entity_id).
- Selten benötigte Datenpunkte (Diagnose, Einschaltdauer, 2./3. virtueller HmIP-Kanal …)
  werden angelegt, sind aber deaktiviert und lassen sich bei Bedarf einschalten.
- Ist ein Gerät nicht erreichbar (UNREACH), werden seine Entitäten „nicht verfügbar".

## Systemvariablen
Alle Systemvariablen der CCU landen im Gerät **„CCU Systemvariablen"** mit Entity-IDs
`…homematic_sysvar_<name>`:

| Typ in der CCU | Entität |
|---|---|
| Logikwert, Alarm | `switch` (Anzeigetext wie „anwesend" im Attribut `anzeige`) |
| Zahl | `number` (mit Einheit, Min/Max aus der CCU) |
| Werteliste | `select` |
| Zeichenkette | `text` |

Die CCU meldet Änderungen an Systemvariablen nicht per Event. Sie werden daher zyklisch
abgefragt (Standard alle 30 s, einstellbar). Werte, die aus Home Assistant gesetzt werden,
sind sofort aktuell. Neue Variablen erscheinen beim nächsten Abruf automatisch, gelöschte
werden „nicht verfügbar".

## Optionen
- Virtuelle Fernbedienungen der CCU (HM-RCV-50) anlegen – standardmäßig aus.
- Intervall für die Suche nach neu angelernten Geräten (Standard 10 min).
- Systemvariablen anlegen (Standard an) und Abfrageintervall (Standard 30 s).

Nach einem Verbindungsabbruch verbindet sich die Integration selbst neu und liest alle
Werte einmal komplett nach.

## Wochenprogramme von Heizungsthermostaten (ab 1.2.0, benötigt HM-REST ≥ 1.6.0)

**Aktion `hmrest.set_week_program`** – Plan in einer Funkübertragung an das Thermostat schicken:

```yaml
action: hmrest.set_week_program
data:
  entity_id: climate.homematic_heizung_bad   # oder device_id
  days: [workdays]                           # monday … sunday, workdays, weekend, all
  schedule: "06:00 17; 22:00 21; 24:00 17"   # bis 6 Uhr 17 °C, bis 22 Uhr 21 °C, danach 17 °C
  profile: 1                                 # optional (HM-CC-RT-DN: 1–3)
  activate: true                             # optional: Profil aktiv schalten
```

Der Plan geht auch als Liste: `[{end: "06:00", temp: 17}, {end: "24:00", temp: 21}]`.
Nur das Profil umschalten (z. B. Urlaub/Homeoffice): `profile: 2` + `activate: true`, ohne `days`/`schedule`.

**Aktion `hmrest.get_week_program`** liefert das aktuelle Programm als Antwort
(Entwicklerwerkzeuge → Aktionen, oder in Skripten mit `response_variable`).

Batteriebetriebene Thermostate übernehmen die Änderung beim nächsten Funkkontakt (einige Minuten).

## Änderungen
Siehe [CHANGELOG.md](CHANGELOG.md). Fertige Pakete gibt es unter *Releases*.
