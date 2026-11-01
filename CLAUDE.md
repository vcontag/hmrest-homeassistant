# HomeMatic (HM-REST) – Home-Assistant-Integration

Custom Component `custom_components/hmrest` (Domain `hmrest`). Bindet eine HomeMatic-CCU über das Add-on
**HM-REST** (eigenes Repo `vcontag/hmrest`, Go) an: Geräte per REST, Wertänderungen per Server-Sent Events (`/api/events`),
Systemvariablen per Polling, Wochenprogramme über `/api/devices/{adr}/weekprogram`.
Alle Entity-IDs beginnen mit `homematic_`.

## Befehle
- Testumgebung: `python3 -m venv .venv && .venv/bin/pip install -r requirements_test.txt`
- Tests: `.venv/bin/python -m pytest -q` (Ende-zu-Ende gegen `tests/fake_ccu.py`, ein simuliertes HM-REST)
- Installationspaket: `./package.sh` → `dist/hmrest-install-<version>.zip` (nur `custom_components/hmrest`)
- Version: `custom_components/hmrest/manifest.json` – bei jeder Auslieferung erhöhen, Änderungen im README notieren

## Aufbau
- `hub.py` – `HmRestApi` (REST-Client), Datenmodell (`HmDevice`/`HmChannel`/`HmParam`/`HmSysVar`),
  `HmRestHub` (SSE-Stream mit Wiederverbindung + Resync, Gerätescan, Sysvar-Poller, Listener-Verteilung)
- `mapping.py` – ordnet Kanäle/Datenpunkte HA-Plattformen zu (climate, cover, light, switch, sensor, …)
- `entity.py` – Basis-Entität, Geräteinfo (`identifiers={(DOMAIN, Geräteadresse)}`), Verfügbarkeit (UNREACH)
- `sysvar.py` – Entitäten für CCU-Systemvariablen
- `services.py` / `services.yaml` – Aktionen `hmrest.set_week_program`, `hmrest.get_week_program`
- `config_flow.py` – Einrichtung (Host, Port 8099, API-Key, SSL), Reauth, Optionen
- `strings.json` + `translations/de.json`, `en.json` – Texte (strings.json = deutsch, beide Übersetzungen pflegen)

## Regeln / Stolperfallen
- Ein fehlerhafter Einzelwert darf den Event-Stream nie abbrechen (Listener-Aufrufe in `_set` sind abgesichert).
- Neue Add-on-Funktionen brauchen eine passende Mindestversion von HM-REST – im README vermerken.
- `custom_components/__init__.py` existiert nur für pytest und gehört NICHT ins Installationspaket.
- Betrieb beim Nutzer: Home Assistant im Docker-Container auf einem QNAP; Installation per Upload/Entpacken
  von `hmrest-install-*.zip` in den Config-Ordner und Neustart.
- Texte für Nutzer auf Deutsch.
- HACS: Installation als benutzerdefiniertes Repository (Typ Integration); HACS nimmt `custom_components/hmrest` aus dem
  jeweiligen Release-Tag. `hacs.json` und Manifest-Felder (`documentation`, `issue_tracker`, `codeowners`) aktuell halten;
  CI-Job `validate` prüft mit hacs/action und hassfest. HACS setzt ein öffentliches Repo voraus.

## Releases
- Ein Release entsteht automatisch, wenn auf `main` eine Versionsnummer landet, für die es noch kein Release gibt
  (Job `release` in `.github/workflows/ci.yml`, nur nach grünen Tests).
- Für ein neues Release: Version erhöhen (`custom_components/hmrest/manifest.json`) **und** oben in `CHANGELOG.md` einen Abschnitt `## <Version>`
  ergänzen – der wird als Release-Beschreibung übernommen. Ohne Versionssprung passiert nichts.
- Das Paket (`hmrest-install-<version>.zip`) hängt am Release unter *Releases* auf GitHub.
