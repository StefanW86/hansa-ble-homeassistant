# HANSA BLE-Armatur: Protokoll für ESP32

Quelle: statische Analyse von **HANSA360 v1.9.3** (`de.hansa.b2b`, früher „HANSA Connect“).
Die BLE-Logik steckt in der eingebetteten Bibliothek `fi.taelek.taelekblelibrary` (Taelek Oy / Oras-Gruppe).
Die relevanten Stellen im dekompilierten Code stehen jeweils dabei.

> **Status:** Alles stammt aus dem App-Code. Mit echter Hardware ist noch nichts getestet.
> Die Krypto ist gegen den Original-JS-Code der App verifiziert (`node verify_crypto.js`).

---

## 0. Badezimmerarmatur (Waschtisch): was für dich gilt

Bei Waschtischarmaturen gibt es drei Gerätevarianten. Welche du hast, verrät **Byte 0 der Manufacturer Data** im Advertising (siehe Abschnitt 2):

| Typcode | Variante | Spec | Ereignis-Log | Uhrzeit-Format (`time`) |
|---|---|---|---|---|
| 0 | BASIN (ältere Generation) | olderPeripheral | **nein** | 4 × 1 Byte: Std, Min, Sek, ISO-Wochentag |
| 6 | BASIN_LONG („Touchless“) | urinalAndBasinLong | **nein** | 4 × 1 Byte: Std, Min, Sek, ISO-Wochentag |
| 10 | BASIN_V2 (neuere Generation) | basinV2 | ja | 4 Byte LE, Sekunden seit 2000 (Ortszeit) |

(7 = SPOUT, also ein Auslauf mit separater Elektronik, verhält sich wie Typ 0.)

**Bei allen drei Varianten gleich:** Login, Befehle (OPEN `0x62`, NORMAL `0x84`, CLOSE `0x73`), alle UUIDs, die Zähler (Abschnitt 8) und `maxCloseTime` an Offset 14 in `productParamA` (20 Byte).
Die ESP32-Logik aus den Abschnitten 1, 5 und 6 gilt also unverändert.

**Speziell beim Waschtisch:**
- **`flowRate`** steht in productParamC an Offset 2, 2 Byte, in **0,1 l/min**. Daraus berechnet die Armatur die Literzähler.
- **productStateA:** Byte 2 = `operationMode` (Typ 0/6) bzw. `supplyMode` (Typ 10), Byte 3 = `valveState`, Offset 4 = `batteryVolt` (×0,01 V), Offset 6 = `batteryLeft` (%).
- **productStateB:** Bei Typ 0/6 steht an Offset 16 `timeFromLastOpen` (4 Byte, s). Bei Typ 10 steht dort `temperatureMeas`.

> ⚠️ **Bluetooth-Modus prüfen, besonders bei Batteriegeräten.** Parameter `bluetoothMode` in productParamC, Offset 9:
> 0 = immer an, 1 = nur nach Benutzung aktiv, 2 = nur nach dem Einschalten aktiv, 3 = IR-Erkennung aus.
> Bei 1 oder 2 findet der ESP32 die Armatur morgens eventuell gar nicht, weil sie nicht sendet.
> Für die Automatik muss der Wert **0** sein. Das lässt sich in der HANSA360-App unter Einstellungen ändern.
> Das kostet Batterie. Den Füllstand liest du über `batteryLeft`.
>
> ⚠️ **`appControl`** (productParamC, Offset 13): 0 = alles erlaubt, **1 = Öffnen per App gesperrt**, 2 = alles gesperrt. Er muss 0 sein.

---

## 1. Ablauf für „30 s Wasser laufen lassen“

```
1. Scannen        → Gerät mit Name "ORAS…"/"CYPRESS…" finden, über MAC/Standort die richtige Armatur wählen (Abschnitt 9)
2. Verbinden      → GATT, Services discovern
3. Uhrzeit        → time-Characteristic schreiben (Abschnitt 8). Danach gilt die Verbindung in der App als bereit.
4. OPEN           → 0x62 an productCommands schreiben     (Wasser an)
5. 30 s warten
6. NORMAL         → 0x84 an productCommands schreiben     (Wasser aus, zurück in Sensorbetrieb)
7. Trennen
```

> **Ein Login ist für Befehle nicht nötig, jedenfalls nicht in der App.**
> Die App verbindet sich, schreibt die Uhrzeit und sendet OPEN/NORMAL/CLOSE/WINK direkt. Weder `ConnectDetailFragment` noch `performTask`/`connect` rufen einen Login auf.
> Einloggen muss man sich nur, um Einstellungen zu ändern (Konfigurationsseite).
> Lehnt eine Firmware den Befehl trotzdem ab, führt man vorher den Login aus Abschnitt 5 aus.

> ⚠️ **Nicht `CLOSE` (0x73) zum Ausschalten nehmen.** In der App schickt der Button „Schließen“
> den Befehl `NORMAL` (0x84). `CLOSE` (0x73) hängt am Button „Reinigen“. Das ist der Reinigungsmodus:
> Das Ventil bleibt zu und der Sensor ist gesperrt.
> (`de/hansa/b2b/fragment/ConnectDetailFragment.java:178-195`)

---

## 2. Gerät finden (Advertising)

| Was | Wert |
|---|---|
| Scan-Filter | Gerätename enthält `ORAS`, `CYPRESS`, `oras`, `cypress` (bzw. `taelek_OTA` im Update-Modus) |
| Manufacturer Specific Data | Die App nimmt den **letzten** Eintrag, die Company-ID ist egal |
| Byte 0 | Gerätetyp-Code (siehe unten) |
| Byte 1 | Batteriestand |
| Byte 2 | Fehlercode |
| Byte 3..n | Standort-String (UTF-8, `0x00` herausfiltern, trimmen) |

Die App ignoriert die Typcodes 2, 3, 4, 5, 8, 9, 12 und 16.

| Code | Typ | Spec-Datei |
|---|---|---|
| **0** | **BASIN (Waschtisch)** | **olderPeripheral** |
| 1 | URINAL | urinalAndBasinLong |
| **6** | **BASIN_LONG (Waschtisch)** | **urinalAndBasinLong** |
| 7 | SPOUT | olderPeripheral |
| **10** | **BASIN_V2 (Waschtisch)** | **basinV2** |
| 11 | MIRA | miraKitchen |
| 13 | PHOTOCELL | photocell |
| 14 | KITCHEN | miraKitchen |
| 15 | SHOWER | shower |
| 17 | TOUCH_BUTTON | touchButton |
| 19/20 | BIDE/BUTTON | newerPeripheral |
| 21 | REMOTE_CONTROL | remotecontrol |
| 39/40 | CONTROL_BOX_1/2 | newerPeripheral |

(`TaelekPeripheral.java:165-290`, `util/UtilsKt.java`, `ValveScanner.java`)

---

## 3. GATT: die nötigen Characteristics

Die UUIDs sind bei allen Gerätetypen gleich (in allen Spec-Dateien geprüft).

| Name | UUID | Zugriff | Zweck |
|---|---|---|---|
| Service „settings“ | `2be32db1-5f6b-5bd8-8033-8d6dfb164900` | | enthält die folgenden Characteristics |
| **productPassword** | `2be32db1-5f6b-5bd8-8b38-d6dfb1649000` | read / write | Lesen: 24 Byte verschlüsselter Temp-Key. Schreiben: 16 Byte Login-Antwort |
| **nonce** | `2be32db1-5f6b-5bd8-8e8d-6dfb16490000` | read | Nonce für den Login. Letztes Byte `0xFF` heißt eingeloggt |
| **productCommands** | `2be32db1-5f6b-5bd8-8a38-d6dfb1649000` | write | 1-Byte-Befehle, **unverschlüsselt** |
| time | `2be32db1-5f6b-5bd8-8c38-d6dfb1649000` | read / write | Geräteuhr. Format siehe Abschnitt 8 (abhängig vom Typcode, siehe Abschnitt 0) |
| Service „info“ | `2be32db1-5f6b-4cbd-8803-38d6dfb16490` | | |
| productStateA | `2be32db1-5f6b-4cbd-8843-8d6dfb164900` | read | Byte 3 = `valveState` (0 = zu, 1 = offen). Guter Test, ob OPEN gewirkt hat |
| productStateB | `2be32db1-5f6b-4cbd-8853-8d6dfb164900` | read | Zeiten seit letzter Nutzung usw., Layout je Typ siehe Abschnitt 0 |

Byte-Layout von **productStateA**: `deviceState:1, sensorErrorFlag:1, operationMode|supplyMode:1, valveState:1, batteryVolt:2, batteryLeft:2, …`.
Zahlen sind Little Endian, außer ein Parameter hat `isBigEndian`.

Die vollständige Liste aller Characteristics und Parameter je Gerätetyp steht in
[analysis/spec_summary.txt](analysis/spec_summary.txt). Die JSON-Rohdaten liegen in `analysis/*.txt`.

---

## 4. Befehle (`productCommands`, 1 Byte)

| Befehl | Byte | App-Button / Bedeutung |
|---|---|---|
| WINK | `0x51` | Gerät identifizieren (blinkt) |
| **OPEN** | `0x62` | „Öffnen“: Wasser an |
| CLOSE | `0x73` | „Reinigen“: Reinigungssperre für `maxCloseTime` Sekunden (siehe Abschnitt 7) |
| **NORMAL** | `0x84` | „Schließen“: Wasser aus, Sensor wieder aktiv |
| FACTORY_RESET | `0x95` | ⚠️ |
| COUNTER_RESET | `0xA6` | Zähler zurücksetzen |
| RESET_LOG | `0x52` | |
| REMOVE_PAIRINGS | `0x42` | |
| START_PAIRING | `0x40` | |
| RESET | `0xC7` | Neustart |

(`CommandHelper.java`, `TaelekService.sendTypedCommand/sendCommand`)

Für Typcode 10–14 gibt es zusätzlich „Custom Commands“ (`sendCustomCommand`). Für den Anwendungsfall braucht man sie nicht.

**Sicherheitsgrenze im Gerät:** Der Parameter `maxOpenTime` (Sekunden, in `productParamA`) begrenzt wahrscheinlich, wie lange OPEN wirkt.
Steht er unter 30 s, schließt das Ventil schon früher.
Schickt der ESP32 kein NORMAL (etwa wegen Absturz oder Funkabbruch), sollte das Gerät spätestens nach `maxOpenTime` selbst schließen. Das ist noch zu prüfen.

---

## 5. Login (Challenge-Response, AES-128-CCM)

Benutzerpasswort: Standard ist **`Electra`** (`strings.xml: connect_login_password_hint`).
Wurde es in der App geändert, gilt das neue.

### Ablauf (`TaelekService.login` → `handleLogin`)

```
encPw  = READ(productPassword)     // 24 Byte = 16 Byte Ciphertext + 8 Byte CCM-Tag
nonce  = READ(nonce)
n      = nonce[0 .. min(len,13)-1] // SJCL kürzt auf 13 Byte (L=2)

FIXED_KEY = 01 01 01 … 01 (16 Byte)

tempKey = AES-CCM-Decrypt(key=FIXED_KEY, nonce=n, ct=encPw[0..15], tag=encPw[16..23])   // Tag wird von der App NICHT geprüft
md5pw   = MD5(UTF-8(passwort))                                                       // 16 Byte
resp    = AES-CCM-Encrypt(key=tempKey, nonce=n, pt=md5pw, tagLen=8)[0..15]              // nur Ciphertext, Tag verwerfen

WRITE(productPassword, resp)       // 16 Byte, Write mit Response
check  = READ(nonce)
login_ok = (check[last] == 0xFF)
```

CCM-Parameter: Tag 8 Byte, keine AAD, Längenfeld L = 2 (bei 13-Byte-Nonce), also Standard-RFC-3610.
Liefert das Gerät weniger als 24 Byte, füllt die App mit `0x00` auf 24 Byte auf.

**Trick für den ESP32:** CCM verschlüsselt im CTR-Modus. „Verschlüsselt“ man den Ciphertext noch einmal, kommt der Klartext heraus, ohne dass der Tag geprüft wird. So macht es die App auch.
Man braucht also nur `mbedtls_ccm_encrypt_and_tag`. Der Test `verify_crypto.js` deckt genau diesen Weg ab.

### Alternative: „globalLogin“

Gibt der Nutzer das Passwort in Anführungszeichen ein (`"…"`), nimmt die App es als Hex-String.
Sie füllt es links mit `0` auf 32 Zeichen auf, wandelt es in 16 Byte und schreibt es **direkt** in productPassword (ohne Krypto).
Das ist vermutlich ein Service- oder Master-Code. Für den Anwendungsfall braucht man es nicht.

### Verschlüsseltes Schreiben von Parametern

Diesen Weg braucht man nur, wenn man Einstellungen ändern will, nicht für OPEN/NORMAL.
Ist im Service `bfb53bad-6b00-402d-a0e5-be625ffaf10e` (Characteristic `…a1e5…`, `enabled`) die Verschlüsselung aktiv, werden Parameter-Writes so geschützt:
`AES-CCM(tempKey, nonce, data)` **inklusive** 8-Byte-Tag (`encrypt_data`).

---

## 6. ESP32-Referenz (Skizze, ungetestet)

```c
#include "mbedtls/ccm.h"
#include "mbedtls/md5.h"

// encPw: 24 Byte aus productPassword, nonce/nonceLen: aus nonce-Characteristic
// out: 16 Byte, die nach productPassword geschrieben werden
int hansa_login_response(const uint8_t encPw[24], const uint8_t *nonce, size_t nonceLen,
                         const char *password, uint8_t out[16]) {
    static const uint8_t FIXED_KEY[16] = {1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1};
    size_t n = nonceLen > 13 ? 13 : nonceLen;   // muss >= 7 sein
    uint8_t tempKey[16], md5pw[16], tag[8];
    mbedtls_ccm_context ccm;

    // 1) tempKey = CCM-"Decrypt" ohne Tag-Check (CTR ist symmetrisch)
    mbedtls_ccm_init(&ccm);
    mbedtls_ccm_setkey(&ccm, MBEDTLS_CIPHER_ID_AES, FIXED_KEY, 128);
    int rc = mbedtls_ccm_encrypt_and_tag(&ccm, 16, nonce, n, NULL, 0, encPw, tempKey, tag, 8);
    mbedtls_ccm_free(&ccm);
    if (rc) return rc;

    // 2) MD5(passwort)
    mbedtls_md5((const unsigned char *)password, strlen(password), md5pw);

    // 3) Antwort = CCM-Encrypt(tempKey, nonce, md5) -> nur die 16 Byte Ciphertext
    mbedtls_ccm_init(&ccm);
    mbedtls_ccm_setkey(&ccm, MBEDTLS_CIPHER_ID_AES, tempKey, 128);
    rc = mbedtls_ccm_encrypt_and_tag(&ccm, 16, nonce, n, NULL, 0, md5pw, out, tag, 8);
    mbedtls_ccm_free(&ccm);
    return rc;
}
```

Ablauf mit NimBLE-Arduino (Pseudocode):

```cpp
auto svc  = client->getService("2be32db1-5f6b-5bd8-8033-8d6dfb164900");
auto pw   = svc->getCharacteristic("2be32db1-5f6b-5bd8-8b38-d6dfb1649000");
auto nc   = svc->getCharacteristic("2be32db1-5f6b-5bd8-8e8d-6dfb16490000");
auto cmd  = svc->getCharacteristic("2be32db1-5f6b-5bd8-8a38-d6dfb1649000");

std::string enc = pw->readValue();  enc.resize(24, '\0');
std::string non = nc->readValue();
uint8_t resp[16];
hansa_login_response((uint8_t*)enc.data(), (uint8_t*)non.data(), non.size(), "Electra", resp);
pw->writeValue(resp, 16, true);
if ((uint8_t)nc->readValue().back() != 0xFF) { /* Login fehlgeschlagen */ }

cmd->writeValue((uint8_t)0x62, true);   // OPEN
delay(30000);
cmd->writeValue((uint8_t)0x84, true);   // NORMAL (= "Schließen" in der App)
```

---

## 7. Reinigungssperre („Reinigen“)

Ablauf:

```
Verbinden + Uhrzeit schreiben   // Login laut App nicht nötig (Abschnitt 1)
WRITE(productCommands, 0x73)   // CLOSE: Sensor gesperrt, Ventil bleibt zu
… Armatur putzen …
WRITE(productCommands, 0x84)   // NORMAL: Sperre vorzeitig beenden (optional)
```

- **Wie lange gesperrt wird, bestimmt das Gerät selbst**, nicht die App. Dafür gibt es den Parameter `maxCloseTime`.
  In der App heißt er „Cleaning mode time“ (`strings.xml: connect_maxCloseTime`).
  Er liegt in **productParamA**, Offset 14, 2 Byte Little Endian, in Sekunden.
  Es gibt ihn bei allen Waschtisch- und Küchenarmaturen, nicht aber bei Spender, Fernbedienung und Touch-Button.
- Nach Ablauf dieser Zeit kehrt das Gerät vermutlich von selbst in den Normalbetrieb zurück. Das Log enthält dafür die Ereignisse 20 und 21 („Cleaning mode start/end“).
- Den aktuellen Wert liest man aus `productParamA` (unverschlüsselt).
  Die erlaubten Grenzen stehen in `productParamAmin` (`…5bd8-8438…`) und `productParamAmax` (`…5bd8-8738…`), jeweils an Offset 14.
- Für eine Sperrdauer **nur bei diesem einen Mal** schickt man CLOSE und nach der gewünschten Zeit NORMAL.
  Das ist einfacher als den Parameter zu ändern, funktioniert aber nur bis höchstens `maxCloseTime`.

Bei Touch-Button- und Fernbedienungs-Varianten heißt der Parameter `cleaningTime` (bzw. `shortCleaningTime`/`longCleaningTime`). Für Waschtische ist das nicht relevant.

### Sperrdauer dauerhaft ändern (`maxCloseTime` schreiben)

Die App schreibt nie einen einzelnen Parameter, sondern immer die **ganze Characteristic** (`writeParameter` → `replaceDataSlice`):

```
alt  = READ(productParamA)                  // 20 Byte (Waschtisch und Küche)
neu  = alt; neu[14..15] = sekunden (LE)      // Wert muss zwischen min und max liegen
```

Danach hängt es vom Characteristic `Encryption` (Service `bfb53bad-6b00-402d-a0e5-be625ffaf10e`, Char `bfb53bad-6b00-402d-a1e5-be625ffaf10e`) ab.
Ist dort Bit 0 = 1, gilt `cyberSecurityVersion = 1` (`TaelekService.java:1340-1362`):

| Encryption Bit 0 | Schreiben auf productParamA/B/C |
|---|---|
| 0 | `WRITE(productParamA, neu)`, Klartext |
| 1 | `encPw = READ(productPassword)`, `nonce = READ(nonce)` (beide frisch lesen), dann `tempKey` wie beim Login berechnen. Anschließend `WRITE(productParamA, AES-CCM-Encrypt(tempKey, nonce[0..12], neu) inkl. 8-Byte-Tag)`, also 20 + 8 = 28 Byte (`handleEncryptedWrite`, JS `encrypt_data`) |

Die Verschlüsselungspflicht betrifft nur `productParamA/B/C` (`5bd8-8138/8238/8338`, siehe `TaelekServiceKt.java`).
Befehle, Zeit und Lesezugriffe gehen immer im Klartext.
Nach dem Schreiben liest die App den Wert zurück, um ihn zu prüfen. Das sollte der ESP32 auch tun.
Der Test `verify_crypto.js` deckt auch `encrypt_data` ab.

> ⚠️ Nur `maxCloseTime` ändern und den Rest der 20 Byte unverändert zurückschreiben. Ein falscher Wert z. B. in `maxIrPower` oder in der Sensorkalibrierung verstellt die Armatur.

---

## 8. Verbrauch, Öffnungen und Nutzungen auslesen

Alles hier ist **nur lesend** und unverschlüsselt.
Ob die Armatur dafür einen Login verlangt, ist noch zu testen.
Zahlen sind 4 Byte Little Endian, unsigned.

### Zähler (Service „info“ `2be32db1-5f6b-4cbd-8803-38d6dfb16490`)

| Characteristic | UUID | Offset: Wert |
|---|---|---|
| productCountersA | `2be32db1-5f6b-4cbd-8863-8d6dfb164900` | 0: `totalOpenCounter` (Öffnungen gesamt) · 4: `totalUseCount` (Nutzungen) · 8: `totalOpenTime` (×0,1 s) · 12: `totalAutoFlowCount` (Hygienespülungen) · 16: `totalManualFlowCount` |
| productCounterB | `2be32db1-5f6b-4cbd-8873-8d6dfb164900` | 0: **`totalConsumption` (Liter gesamt)** · 4: `tripOpenCount` · 8: `tripUseCount` · 12: `tripOpenTime` (×0,1 s) · 16: `tripAutoFlowCount` |
| productCounterC | `2be32db1-5f6b-4cbd-8883-8d6dfb164900` | 0: `tripManualFlowCount` · 4: **`tripConsumption` (Liter seit Reset)** · 8: `timeFromLastCounterReset` (s) |

- „total…“-Zähler laufen über die gesamte Lebensdauer. „trip…“-Zähler setzt `COUNTER_RESET` (`0xA6`) zurück, praktisch für Tages- oder Monatswerte.
- **Wassermenge:** Das Gerät misst den Durchfluss vermutlich nicht. Wahrscheinlich rechnet es Öffnungszeit × eingestellte Durchflussrate (`flowRate` in productParamC, Offset 2, 2 Byte, 0,1 l/min).
  Die Literangabe ist also nur so genau wie dieser Wert. Hat man `flowRate` nicht passend eingestellt, misst man besser `totalOpenTime` und rechnet selbst.
- Eine **Schließung** zählt das Gerät nicht separat: Jede Öffnung endet mit einer Schließung.
  Den aktuellen Zustand liefert `productStateA` Byte 3 (`valveState`). `productStateB` Offset 4 enthält `timeFromLastUse` (s).

### Ereignis-Log (einzelne Öffnungen mit Zeitstempel)

> Nur bei **Waschtisch Typ 10 (BASIN_V2)** und neueren Geräten. Bei Typ 0 und 6 fehlt der Service „testing“, dort bleiben nur die Zähler.

Service „testing“ `2be32db1-5f6b-6bd8-8033-8d6dfb164900`, Characteristic **logParams** `2be32db1-5f6b-6bd8-8138-d6dfb1649000`.
Jeder `READ` liefert den **nächsten** Eintrag (20 Byte). Man liest so lange, bis `downCount == 0` ist (`TaelekService.readLog`).

| Offset | Länge | Feld | Kodierung |
|---|---|---|---|
| 0 | 2 | `downCount` (noch verbleibende Einträge) | **Big Endian** |
| 2 | 4 | Zeitstempel | LE, Sekunden seit 01.01.2000 00:00 **Gerätezeit** |
| 6 | 1 | `action` | siehe unten |
| 7 | 2 | `duration` | **Big Endian**. Einheit nicht dokumentiert, vermutlich s oder 0,1 s, am Gerät prüfen |
| 9..16 | 4×2 | `param1..4` | Big Endian |
| 17 | 2 | `param5` | LE |
| 19 | 1 | `param6` | |

Aktionscodes (`strings.xml: connect_actionCode_*`):
1 Normal (Sensor), 5 Bidet, 6 Taster, 7 Desinfektion, **8 App** (also auch deine ESP32-Öffnungen), 9 Wink, 10–13 Hygienespülung (normal/fix/Volumen/Kalender), **20/21 Reinigungsmodus Start/Ende**, 30/31 Vandalismus, 40/41 Waschmaschine, 50/51 Shutdown, 99 Log gelöscht.

- Ob überhaupt geloggt wird, steuert `loggingMode` in productParamC: 0 = alles, 1 = nur Sonderereignisse, 2 = aus.
- Zeitstempel stimmen nur, wenn die Geräteuhr gestellt ist. Die App stellt sie bei jedem Verbinden über die `time`-Characteristic (`…5bd8-8c38…`, Klartext). Das Format hängt vom Typcode ab (`TaelekService.writeTimeCharacteristic`):
  - **Typcode ≥ 10 (u. a. Waschtisch BASIN_V2 = 10):** 4 Byte LE = `jetzt_UTC_Sekunden (+3600 bei Sommerzeit) − Epoch(01.01.2000 00:00 Ortszeit)`.
    Das sind die Sekunden seit 01.01.2000 nach lokaler Uhrzeit, im selben Format wie der Log-Zeitstempel.
  - Typcode < 10: `hours, minutes, seconds, isoWeekday` (je 1 Byte, Montag = 1).

  Der ESP32 sollte das nach dem NTP-Sync genauso machen.
- `RESET_LOG` (`0x52`) leert das Log.

---

## 9. Zwei Armaturen nebeneinander: Identifizieren und Zuordnen

### Identifizieren (WINK) wie in der App

In der Geräteliste der App gibt es pro gefundener Armatur einen „Identifizieren“-Knopf (`ConnectDevicesFragment` → `ConnectViewModel.identifyDevice`):

```
1. Verbinden + Services discovern
2. Uhrzeit schreiben (time-Characteristic)      // so wartet die App auf ACTION_TIME_WRITE_SUCCESS
3. WRITE(productCommands, 0x51)                 // WINK, ohne Login
4. Die Armatur blinkt winkTime Sekunden lang
5. Die App trennt die Verbindung nach einem Timer
```

`winkTime` liegt in productParamC an Offset 6. Bei Typ 0 hat er 2 Byte, bei Typ 6 und 10 1 Byte, jeweils in Sekunden.

### Merkmale zum Unterscheiden

| Merkmal | Woher | Eignung |
|---|---|---|
| **MAC-Adresse** | Scan-Ergebnis | ✅ Am einfachsten. Sie ist bei diesen Geräten in der Praxis fest; die App nutzt sie ebenfalls (`ValveScanCallback.address`). Prüfen, ob sie über einen Neustart stabil bleibt |
| **Standort-Text** | Advertising, Manufacturer Data ab Byte 3 (UTF-8, `0x00` entfernen) | ✅ Ohne Verbindung lesbar. Lässt sich mit eigenem Text belegen, z. B. „Links“ / „Rechts“ (siehe unten) |
| **Seriennummer** | `productName` `2be32db1-5f6b-4cbd-8823-8d6dfb164900`, Offset 0, 4 Byte LE | ✅ Eindeutig und steht auf dem Typenschild, braucht aber eine Verbindung |
| Produktname | dieselbe Characteristic, Offset 4, 15 Byte String | ❌ Bei zwei gleichen Armaturen identisch |

### Standort-Text setzen (einmalig)

Am bequemsten geht das in der HANSA360-App: Feld „Product location“ in der Gerätekonfiguration (Login nötig).
Vom ESP32 aus geht es so:

```
Login (Abschnitt 5)                                   // die App verlangt ihn für die Konfiguration
alt = READ(productLocation 2be32db1-5f6b-4cbd-8833-8d6dfb164900)   // 15 Byte Standort + 4 Byte productionDate
neu = alt; neu[0..14] = 00…00 + "Links"                // linksbündig mit 0x00 aufgefüllt (stringToByteArray)
WRITE(productLocation, neu)                            // Klartext, gehört nicht zu den verschlüsselten Characteristics
```

Der Text darf höchstens 15 Byte lang sein. Danach erscheint er im Advertising. Ob das sofort passiert oder erst nach einem Neustart der Armatur, ist zu prüfen.

### Einrichtung auf dem ESP32 (Vorschlag)

1. **Anlernen:** Alle Armaturen scannen und auflisten (MAC, Standort-Text, RSSI). Nacheinander an jede WINK senden, du schaust, welche blinkt, und ordnest ihr „Links“ oder „Rechts“ zu.
2. Die Zuordnung **MAC → Name** im NVS (Preferences) speichern.
3. **Morgens** nur die gewünschte(n) MAC(s) ansteuern. Bei zwei Armaturen geht man sie nacheinander durch: verbinden, OPEN, trennen, nächste Armatur, und nach 30 s für beide NORMAL. Alternativ hält man zwei Verbindungen gleichzeitig; NimBLE schafft standardmäßig 3.

> Feste Stromversorgung: Die Hinweise zur Batterie in Abschnitt 0 entfallen. `bluetoothMode` sollte trotzdem auf 0 = „Always ON“ stehen.

---

## 10. Offene Punkte für den ersten Hardwaretest

- **Typcode** (Byte 0 der Manufacturer Data) ermitteln, um festzulegen, welche Zeile in Abschnitt 0 gilt.
- `bluetoothMode` = 0 und `appControl` = 0 prüfen (Abschnitt 0).
- Prüfen, ob OPEN/WINK wie in der App **ohne Login** akzeptiert werden.
- Bleiben die MAC-Adressen beider Armaturen nach einem Stromausfall gleich?

- Name im Advertising und Typcode der eigenen Armatur mit nRF Connect prüfen.
- Länge der `nonce` lesen. Erwartet werden 7 bis 16 Byte. Bei mehr als 13 Byte nimmt man die ersten 13.
- Prüfen, ob ein Befehl ohne Login abgelehnt wird. Die App loggt sich vor Detailaktionen nicht immer explizit ein.
- `maxOpenTime` aus `productParamA` lesen. Er muss mindestens 30 s sein.
- Parameter `appControl` / `bluetoothControl` (`productParamC`): Sie können die Fernsteuerung eventuell sperren.
- Die App hält während der Steuerung keine Dauerverbindung. Für den ESP32 reicht es also, jeden Morgen zu verbinden, den Befehl zu senden und wieder zu trennen.
