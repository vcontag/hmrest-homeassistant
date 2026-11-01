# Änderungen

Neue Einträge oben. Die Überschrift `## <Version>` muss zu `version` in
`custom_components/hmrest/manifest.json` passen – der Abschnitt wird beim Release automatisch als Beschreibung übernommen.

## 1.2.0
*Benötigt HM-REST ≥ 1.6.0.*
- Aktionen `hmrest.set_week_program` und `hmrest.get_week_program` für Wochenprogramme von Heizungsthermostaten.
- Ein einzelner Wert, an dem eine Entität scheitert, bricht den Event-Stream nicht mehr ab
  (Ursache der Meldung „Event-Stream unterbrochen: could not convert string to float").

## 1.1.0
- Systemvariablen der CCU als Schalter, Zahlen-, Auswahl- und Textfelder (Abfrage alle 30 s, einstellbar).

## 1.0.0
- Erste Version: alle Geräte per REST, Live-Werte per Server-Sent Events, Entity-IDs mit `homematic_`.
