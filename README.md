# HANSA Connect BLE für Home Assistant

Inoffizielle Home-Assistant-Integration für elektronische **HANSA-Armaturen mit Bluetooth**.
Das sind die Armaturen, die sich mit der App „HANSA360“ (früher „HANSA Connect“) einstellen lassen.

- **Vorlaufen:** Die Armatur läuft X Sekunden, damit morgens schon warmes Wasser kommt. Mehrere Armaturen laufen dabei parallel.
- **Identifizieren:** Die Armatur blinkt. Damit findest du heraus, welche von zwei Armaturen welche ist.
- **Reinigungssperre:** Der Sensor ist zum Putzen gesperrt. Die Sperrdauer lässt sich einstellen.
- **Verbrauch:** Liter, Öffnungen, Nutzungen und Öffnungszeit. Die Wassermenge funktioniert direkt im Energie-Dashboard.

> ⚠️ Kein offizielles Produkt, keine Verbindung zu HANSA, Oras oder Taelek. Nutzung auf eigenes Risiko.
> Das Protokoll ist in [HANSA_BLE_PROTOKOLL.md](HANSA_BLE_PROTOKOLL.md) dokumentiert.

```
┌──────────────┐   Bluetooth LE    ┌─────────────────────┐   WLAN (ESPHome-API)   ┌──────────────────────────┐
│ HANSA links  │◄────────────────► │ ESP32-S3            │◄──────────────────────►│ Home Assistant           │
│ HANSA rechts │                   │ ESPHome BT-Proxy    │                        │ Integration hansa_ble    │
└──────────────┘                   └─────────────────────┘                        └──────────────────────────┘
```

Der ESP32 bekommt **keine eigene Firmware**. Er ist ein normaler ESPHome-Bluetooth-Proxy.
Die ganze HANSA-Logik (Login, Befehle, Zähler) steckt in der Integration.
Updates gibt es deshalb über HACS, ohne den ESP32 neu zu flashen.

---

## Inhalt

1. [Was du brauchst](#1-was-du-brauchst)
2. [Armaturen vorbereiten (HANSA360-App)](#2-armaturen-vorbereiten-hansa360-app)
3. [ESP32 als Bluetooth-Proxy einrichten](#3-esp32-als-bluetooth-proxy-einrichten)
4. [Integration über HACS installieren](#4-integration-über-hacs-installieren)
5. [Armaturen hinzufügen und zuordnen](#5-armaturen-hinzufügen-und-zuordnen)
6. [Was du in Home Assistant bekommst](#6-was-du-in-home-assistant-bekommst)
7. [Morgen-Automatik „Warmwasser-Vorlauf“](#7-morgen-automatik-warmwasser-vorlauf)
8. [Wasserverbrauch im Energie-Dashboard](#8-wasserverbrauch-im-energie-dashboard)
9. [Fehlersuche](#9-fehlersuche)
10. [Für Entwickler: Tests](#10-für-entwickler-tests)

---

## 1. Was du brauchst

| | |
|---|---|
| Home Assistant | **2026.10 oder neuer**, mit HACS. Für den ESP32 ist das Add-on „ESPHome Device Builder“ am bequemsten |
| ESP32 | **ESP32-S3-DevKitC-1** (andere ESP32 mit Bluetooth gehen auch, **nicht** ESP32-S2) |
| Standort | ESP32 im Bad oder direkt hinter der Wand. Fliesen und Leitungen dämpfen das Signal stark |
| Strom | USB-Netzteil (5 V, 1 A reicht) |
| Handy | Mit der App **HANSA360** für die Vorbereitung |

Ein Shelly-Gateway oder ein anderer reiner Bluetooth-Empfänger reicht **nicht**. Die Armaturen brauchen eine aktive Verbindung, und die kann nur ein ESPHome-Proxy oder ein lokaler Bluetooth-Adapter aufbauen.

## 2. Armaturen vorbereiten (HANSA360-App)

Mach Folgendes **für jede Armatur** in der App: Verbinden → anmelden (Standardpasswort `Electra`) → Einstellungen.

1. **Bluetooth Mode → „Always ON“.** Sonst ist die Armatur morgens nicht erreichbar.
2. **App control → „All allowed“.** Sonst ignoriert sie das Öffnen per Funk.
3. **Product location** (optional, empfehlenswert): `Links` bzw. `Rechts`. Der Text wird per Bluetooth mitgesendet und erleichtert die Zuordnung in Home Assistant.
4. Hast du das Passwort geändert, notiere es. Du brauchst es bei der Einrichtung.

Falls 1. oder 2. später nicht stimmen, meldet Home Assistant das unter **Einstellungen → Reparaturen**.

## 3. ESP32 als Bluetooth-Proxy einrichten

1. Installiere in Home Assistant das Add-on **ESPHome Device Builder**: *Einstellungen → Add-ons → Add-on-Store → ESPHome*. Starte es und öffne die Weboberfläche.
2. Klicke oben rechts auf **Secrets** und trage die Werte aus [`esphome/secrets.example.yaml`](esphome/secrets.example.yaml) ein: WLAN, einen API-Schlüssel und ein OTA-Passwort.
   Den API-Schlüssel kannst du dir auf <https://esphome.io/components/api/> erzeugen lassen. Alternativ übernimmst du den Schlüssel, den der Assistent beim Anlegen eines neuen Geräts anzeigt.
3. **+ New Device** → Name `hansa-bt-proxy` → **ESP32-S3** wählen → „Skip“ (nicht installieren).
4. Beim neuen Gerät auf **Edit** klicken, den Inhalt komplett durch [`esphome/hansa-bt-proxy.yaml`](esphome/hansa-bt-proxy.yaml) ersetzen und speichern.
5. **Install** → **Plug into this computer**. Steck den ESP32 per USB an den Rechner, an dem der Browser läuft (Chrome oder Edge), und wähle den Port.
   Beim S3-DevKit nimmst du die USB-Buchse mit der Aufschrift **USB**. Klappt das Flashen nicht, hältst du **BOOT** gedrückt, tippst kurz **RST** und lässt BOOT dann los.
6. Danach steckst du den ESP32 an sein Netzteil im Bad.
   Home Assistant meldet *„Neues Gerät gefunden: HANSA Bluetooth Proxy“* → **Konfigurieren** → mit dem API-Schlüssel bestätigen.
7. Prüfen: Unter *Einstellungen → Geräte & Dienste → Bluetooth* sollte `hansa-bt-proxy` als Adapter stehen und **Verbindungen (3 Slots)** anzeigen.

## 4. Integration über HACS installieren

### 4.1 Repository

Die Integration liegt öffentlich unter <https://github.com/StefanW86/hansa-ble-homeassistant>, weil HACS nur öffentliche Repos einbinden kann.
Das Repo enthält ausschließlich eigenen Code und Doku: keine App, keinen dekompilierten Code. Das stellt die `.gitignore` sicher.

### 4.2 In HACS hinzufügen

1. **HACS** → oben rechts **⋮** → **Benutzerdefinierte Repositories**.
2. Repository: `https://github.com/StefanW86/hansa-ble-homeassistant`, Typ **Integration** → **Hinzufügen**.
3. In HACS nach **HANSA Connect BLE** suchen → **Herunterladen**.
4. **Home Assistant neu starten** (*Einstellungen → System → oben rechts ⏻ → Home Assistant neu starten*).

Updates: Du änderst Code, pushst und erhöhst `version` in `manifest.json`. Dann zeigt HACS das Update an.

## 5. Armaturen hinzufügen und zuordnen

Nach dem Neustart erkennt Home Assistant die Armaturen von selbst:
*Einstellungen → Geräte & Dienste* → **„Entdeckt: HANSA Connect BLE (Links)“** → **Hinzufügen**.
Erscheint nichts, gehst du über **+ Integration hinzufügen → HANSA Connect BLE** und wählst die Armatur aus der Liste.

Pro Armatur läuft der Dialog so:

1. Er zeigt Bluetooth-Name, MAC-Adresse und Standort-Text.
2. **„Armatur blinken lassen (identifizieren)“**: Die Armatur blinkt. Schau, welche es ist. „Letztes Ergebnis: ✅“ heißt, der Befehl ist angekommen.
3. **Weiter** → **Name** vergeben (z. B. `Waschtisch links`) → **Gerätepasswort** (vorbelegt `Electra`).
4. Die Integration prüft das Passwort mit einem Login an der Armatur. Danach ist das Gerät angelegt.

Dasselbe machst du für die zweite Armatur. Das Passwort änderst du später über *Gerät → Integration → Konfigurieren*.

## 6. Was du in Home Assistant bekommst

Jede Armatur ist ein eigenes Gerät mit diesen Entities:

| Entity | Typ | Bedeutung |
|---|---|---|
| **Vorlaufen** | Button | Öffnet, wartet die *Vorlaufdauer* ab und schaltet zurück in den Normalbetrieb |
| **Identifizieren** | Button | Die Armatur blinkt |
| **Reinigungssperre** | Schalter | An: Sensor gesperrt (das Gerät beendet die Sperre selbst nach *Reinigungsdauer*). Aus: sofort wieder normal |
| Vorlaufdauer | Zahl (Konfiguration) | Standard 30 s; höchstens so lang wie die „Manual flush time“ (`maxOpenTime`) der Armatur |
| Reinigungsdauer | Zahl (Konfiguration) | Wird direkt in der Armatur gespeichert (`maxCloseTime`), braucht das Passwort |
| Max. Öffnungszeit | Zahl (Konfiguration) | „Manual flush time“ (`maxOpenTime`): so lange läuft das Wasser bei einmal Öffnen höchstens. In der Armatur gespeichert, mindestens 30 s |
| Durchflussrate | Zahl (Konfiguration, l/min) | In der Armatur gespeichert (`flowRate`). Daraus berechnet sie die Liter, also einmal mit dem Messbecher nachmessen |
| Zähler zurücksetzen | Button (Konfiguration) | Setzt die Zähler „seit Reset“ auf 0. Die Gesamtzähler bleiben |
| Ventil | Binärsensor | offen / zu |
| Wasser gesamt / seit Reset | Sensor (L) | Von der Armatur berechnet, aus Öffnungszeit × eingestellter Durchflussrate |
| Öffnungen, Nutzungen, Hygienespülungen | Sensor | Zähler gesamt bzw. seit Reset |
| Öffnungszeit gesamt / seit Reset | Sensor (s) | |
| Zeit seit letzter Nutzung | Sensor | |
| Diagnose | Sensoren | Bluetooth-Modus, App-Steuerung, Gerätetyp-Code, Sensorfehler, Zeit seit Zählerreset |

Die Werte werden alle **15 Minuten** abgefragt und zusätzlich direkt nach jeder Aktion.

**Service `hansa_ble.flush`:** Vorlaufen für eine oder mehrere Armaturen, optional mit eigener Dauer:

```yaml
action: hansa_ble.flush
data:
  device_id:
    - <Geräte-ID links>
    - <Geräte-ID rechts>
  duration: 30
```

Die Geräte-IDs musst du nicht abtippen: Im Automationseditor wählst du „Aktion → HANSA Connect BLE: Vorlaufen“ und klickst die Armaturen an.

**Sicherheit:** Bricht der Vorlauf ab (Funkstörung, Neustart von Home Assistant), schließt die Armatur trotzdem selbst, spätestens nach ihrer `maxOpenTime`.
Kommt das Öffnen nicht bei der Armatur an, schickt die Integration zur Sicherheit trotzdem „Normalbetrieb“.

## 7. Morgen-Automatik „Warmwasser-Vorlauf“

*Einstellungen → Automationen & Szenen → + Automation erstellen → ⋮ → In YAML bearbeiten*.
Füge das Folgende ein, wechsle zurück in den visuellen Editor und wähle bei der Aktion deine beiden Armaturen aus:

```yaml
alias: Warmwasser-Vorlauf morgens
description: Lässt beide Waschtischarmaturen morgens 30 s vorlaufen
triggers:
  - trigger: time
    at: "06:15:00"
conditions:
  - condition: time
    weekday: [mon, tue, wed, thu, fri]
actions:
  - action: hansa_ble.flush
    data:
      device_id: []        # im visuellen Editor beide Armaturen auswählen
      duration: 30
mode: single
```

Varianten:
- **Nur eine Armatur:** nur ein Gerät auswählen, oder stattdessen `button.press` auf die Entity „Vorlaufen“.
- **Uhrzeit per Dashboard änderbar:** einen Helfer *Datum/Uhrzeit* (nur Uhrzeit) anlegen und als Auslöser `at: input_datetime.warmwasser_vorlauf` eintragen.
- **Nicht in den Ferien oder am Wochenende:** weitere Bedingungen ergänzen, z. B. deine Ferien-Integration oder „jemand ist zu Hause“.

## 8. Wasserverbrauch im Energie-Dashboard

*Einstellungen → Dashboards → Energie → Wasserverbrauch → Wasserquelle hinzufügen* → „**Wasser gesamt**“ der jeweiligen Armatur.
Für Tages- und Monatswerte eignet sich der Helfer *Verbrauchszähler* (Utility Meter) mit „Wasser gesamt“ als Quelle.

## 9. Fehlersuche

| Problem | Lösung |
|---|---|
| Armatur wird nicht gefunden | ESP32 näher an die Armatur bringen. Bluetooth Mode in der App auf „Always ON“ stellen. Unter *Bluetooth → hansa-bt-proxy → Werbedaten* nach `ORAS…`/`CYPRESS…` suchen |
| „Keine Verbindung“ / Entities nicht verfügbar | Proxy-Reichweite prüfen. Belegen andere Geräte die 3 Verbindungsslots? Log unter *Einstellungen → System → Protokolle*, Filter `hansa_ble` |
| „Passwort von der Armatur abgelehnt“ | Das Passwort wurde in der App geändert. *Konfigurieren* → richtiges Passwort eintragen |
| Vorlaufen: „device did not confirm the command“ | Die Armatur hat nicht geöffnet. „App control“ muss auf „All allowed“ stehen (siehe Reparaturen) |
| Vorlauf kürzer als eingestellt | Die Armatur begrenzt auf ihre „Manual flush time“; die lässt sich über *Max. Öffnungszeit* erhöhen |
| Mehr Details | *Gerät → ⋮ → Debug-Protokollierung aktivieren*, Aktion wiederholen, Protokoll herunterladen |

**Noch nicht an echter Hardware getestet:**
Alles ist aus der App abgeleitet und gegen eine simulierte Armatur in Home Assistant 2026.10 getestet.
Unklar ist zum Beispiel, ob deine Firmware Befehle ohne Login annimmt. Die Integration loggt sich dann automatisch ein.
Ebenfalls offen ist, in welcher Einheit die Armatur einzelne Werte liefert.
Fällt dir etwas auf, öffne ein Issue mit dem Debug-Protokoll.

## 10. Für Entwickler: Tests

```bash
pip install pytest-homeassistant-custom-component
```
```bash
python -m pytest
```

- `tests/test_protocol.py`: Krypto gegen Prüfwerte aus dem App-JavaScript, Zeitformat, Parsing.
- `tests/test_integration.py`: echter Home-Assistant-Core mit simulierter Armatur (`tests/fake_fitting.py`). Abgedeckt sind Einrichtungsdialog, Entities, Vorlaufen (auch mit Login-Fallback und falschem Passwort), Reinigungssperre, Zähler-Reset und das Schreiben der Geräteparameter (auch verschlüsselt).

Die Tests laufen unter Linux und macOS. Home Assistant unterstützt Windows offiziell nicht.

Protokolldetails: [HANSA_BLE_PROTOKOLL.md](HANSA_BLE_PROTOKOLL.md)
