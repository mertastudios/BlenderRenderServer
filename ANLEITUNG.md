# 📖 Anleitung: Blender Render Server einrichten (für absolute Anfänger)

Diese Anleitung führt dich in winzigen Schritten durch die komplette Einrichtung.
Du brauchst **kein** Vorwissen. Versprochen.

**Was du am Ende hast:**
Ein kleines Programm auf deinem PC, das den Roblox-Avatar von einem Benutzernamen
als 3D-Modell (inkl. Texturen) herunterlädt, ihn mit Blender Cycles in einem
glasigen Material rendert, und das fertige Bild an Roblox Studio schickt – dort
wird es Stück für Stück in ein **EditableImage** übertragen und in einem GUI
angezeigt. Der Server startet beim PC-Neustart automatisch mit, aktualisiert
sich selbst, wenn es neue Versionen auf GitHub gibt, und lässt sich jederzeit
manuell ausschalten.

---

## 📋 Was du brauchst (Checkliste)

- [ ] PC mit **Windows 10 oder 11** (ca. 2 GB freier Speicherplatz)
- [ ] **Internetverbindung** (für die einmalige Installation und die Avatar-Downloads)
- [ ] **Roblox Studio** (kostenlos: https://create.roblox.com )
- [ ] Einen Roblox-Account. Für EditableImages in echten Online-Spielen muss der
      Account **13+ und ID-verifiziert** sein (https://www.roblox.com/my/account )
      – **zum Testen in Studio reicht das normalerweise auch ohne.**
- [ ] Ein Roblox Open-Cloud-API-Key mit Recht **thumbnails: Read** (Abschnitt 9) – seit März 2026 nötig für den 3D-Avatar

⚠️ **Kosten:** Alles hier Genutzte ist kostenlos (Python, Blender, Roblox-APIs).

---

## 1) Das Programm herunterladen und entpacken

1. Öffne die GitHub-Seite dieses Projekts im Browser.
2. Klicke auf den grünen **`<> Code`**-Knopf oben rechts.
3. Klicke auf **`Download ZIP`**.
4. Öffne den **Download-Ordner**. Dort liegt jetzt z.B. `BlenderRenderServer-main.zip`.
5. Rechtsklick auf die ZIP-Datei → **„Alle extrahieren“** → **„Extrahieren“**.
6. Verschiebe den entstandenen Ordner an einen festen Ort, z.B. nach
   `C:\BlenderRenderServer` (wichtig: der Pfad darf sich später nicht mehr
   ändern, sonst muss das Setup neu ausgeführt werden).

💡 **Nicht** in einen OneDrive-/Cloud-Ordner legen – das macht manchmal Probleme.

---

## 2) Das Setup ausführen (einmalig, ca. 5–15 Minuten)

1. Öffne den Ordner (z.B. `C:\BlenderRenderServer`).
2. **Doppelklick auf `01_setup.bat`**.
   - Falls eine blaue Meldung „Windows hat Ihren PC geschützt“ erscheint:
     klicke auf **„Weitere Informationen“** → **„Trotzdem ausführen“**.
     (Das ist nur Windows’ generelle Warnung für unbekannte Programme – die
     Datei kommt aus deinem eigenen Ordner und macht nur das, was hier steht.)
3. Es öffnet sich ein schwarzes Fenster mit einer Übersicht. Drücke eine
   **beliebige Taste** zum Start.
4. Das Setup macht jetzt automatisch Folgendes (du musst nichts tun):
   - **Python installieren** (falls noch nicht vorhanden, ~25 MB)
   - **Python-Pakete** für den Server installieren (klein)
   - **Blender 4.5 herunterladen und entpacken** (~400 MB – das ist der
     längste Teil, einfach laufen lassen)
   - Die Konfigurationsdatei **`.env`** anlegen
5. Am Ende erscheint **„SETUP FERTIG!“**.

⚠️ Wenn beim allerersten Start später die **Windows-Firewall** fragt, ob Python
„auf Netzwerke zugreifen“ darf: **„Zulassen“** klicken (mindestens bei
„Private Netzwerke“). Das ist nur dein eigener Render-Server im Heimnetz.

---

## 3) Einstellungen anpassen (ganz einfach)

1. Doppelklick auf **`06_config_bearbeiten.bat`** → die Datei `.env` öffnet
   sich im Editor.
2. Die wichtigsten Einstellungen:

| Einstellung | Was sie bedeutet | Standard |
|---|---|---|
| `BRS_PORT` | Der „Türnummer“-Port des Servers. Nur ändern, wenn 8000 schon belegt ist (dann aber auch im Roblox-Skript ändern!). | `8000` |
| `RENDER_SAMPLES` | Bildqualität. Mehr = schöner, aber langsamer. `48` = schnell, `96` = Standard, `192` = sehr schön & langsam. | `96` |
| `RENDER_MATERIAL` | `glass` = ganzer Avatar in Glas. `original` = Avatar mit echten Texturen. | `glass` |
| `RENDER_TRANSPARENT_BG` | `false` = schöner Himmelshintergrund (sieht bei Glas am besten aus). `true` = durchsichtiges PNG. | `false` |
| `RENDER_DEVICE` | `CPU` = immer sicher. `GPU` = schneller, wenn eine gute Grafikkarte eingebaut ist. | `CPU` |
| `ROBLOX_API_KEY` | Open-Cloud-API-Key mit Recht **thumbnails: Read**. Seit März 2026 **nötig** für den 3D-Avatar-Download (sonst HTTP 403). Siehe Abschnitt 9. | leer |
| `AUTO_UPDATE` | `true` = automatische Updates von GitHub. Wenn „GitHub nicht erreichbar“ kommt: Rendern geht trotzdem, siehe Abschnitt 12. | `true` |
| `BRS_ACCESS_TOKEN` | Gemeinsames Geheimnis für öffentliche URLs (dann denselben Wert im Lua-Skript bei `RENDER_ACCESS_TOKEN`). | leer |
| `BRS_TEST_MODE` | `true` = rendert eine eingebaute Testfigur **ohne** Verbindung zu Roblox (super für den ersten Test!). Danach wieder auf `false` stellen. | `false` |

3. Speichern (Strg+S) und Editor schließen.
4. Änderungen greifen nach dem nächsten (Neu-)Start des Servers.

💡 **Welcher Avatar gerendert wird, stellst du NICHT hier ein, sondern oben im
Roblox-Server-Skript** (siehe Abschnitt 5 bzw. `roblox/ANLEITUNG_ROBLOX.md`).

---

## 4) Erster Starttest (ohne Roblox)

1. **Tipp für den allerersten Test:** In der `.env` (über
   `06_config_bearbeiten.bat`) kurzzeitig `BRS_TEST_MODE=true` setzen.
   Dann wird eine Testfigur gerendert – ganz ohne Roblox-Verbindung.
2. Doppelklick auf **`02_start.bat`**. Ein schwarzes Fenster öffnet sich.
   Nach ein paar Sekunden steht dort:
   `BlenderRenderServer ist ONLINE … Adresse: http://localhost:8000`
   **Das Fenster offen lassen!** Es ist der laufende Server.
3. Doppelklick auf **`07_im_browser_testen.bat`** → im Browser erscheint die
   Statusseite (aktualisiert sich alle 5 Sekunden selbst).
4. Du kannst dort oben in der Adresszeile des Browsers auch direkt testen:
   `http://localhost:8000/health` → es sollte `{"status":"ok",...}` erscheinen.
5. Wenn du willst: Test-Render starten – dazu in der Browser-Adresszeile die
   „Konsole“ des Servers nicht verfügbar ist, nutze einfach Roblox (Abschnitt 5)
   oder den Befehl aus Abschnitt 12 („Auftrag per Browser senden“).
6. **Test-Modus wieder ausschalten:** `BRS_TEST_MODE=false` in der `.env` und
   Server mit `03_stop.bat` + `02_start.bat` neu starten.

✅ Wenn die Seite im Browser erscheint: **Der PC-Teil läuft perfekt!**

---

## 5) Roblox Studio einrichten

Dafür gibt es eine eigene, sehr genaue Anleitung mit allen Klicks:
👉 **`roblox/ANLEITUNG_ROBLOX.md`** (im selben Download enthalten)

Kurzform:
1. Neues Projekt in Roblox Studio öffnen (z.B. „Baseplate“).
2. **Home → Game Settings → Security → „Allow HTTP Requests“ auf ON.**
3. Das Skript `roblox/RenderServerService.server.lua` als **Script** in den
   **ServerScriptService** einfügen und oben `ROBLOX_USERNAME` auf deinen
   Roblox-Namen setzen.
4. Das Skript `roblox/RenderClient.client.lua` als **LocalScript** in
   **StarterPlayer → StarterPlayerScripts** einfügen.
5. **Play** drücken. Im Output-Fenster siehst du jetzt live:
   - `🟢 Render-Server ONLINE …`
   - `📤 Auftrag angenommen: Avatar von 'DeinName' …`
   - `⏳ Avatar wird von Roblox heruntergeladen …`
   - `⏳ Blender Cycles RENDERT den Avatar … 42 %`
   - `📡 Bild wird übertragen: 8 / 64 Pakete …`
   - `🎉 FERTIG! Bild komplett – im Client-GUI sichtbar.`
6. Auf dem Bildschirm erscheint das GUI mit deinem Glas-Avatar.

---

## 6) Autostart einrichten (empfohlen)

Damit der Server **nach jedem PC-Neustart automatisch läuft**:

1. Doppelklick auf **`04_autostart_installieren.bat`**.
2. Fertig! Ab jetzt passiert Folgendes:
   - Nach der Windows-Anmeldung startet der Server nach ca. 20 Sekunden von
     selbst (du siehst kurz ein schwarzes Fenster – einfach minimieren).
   - **Ausschalten:** jederzeit mit **`03_stop.bat`**.
     ⚠️ Nach dem nächsten Neustart ist er wieder an. Das ist gewollt.
   - **Ganz entfernen:** `05_autostart_entfernen.bat`.

Kein Passwort, keine Administratorentscheidung nötig – die Aufgabe läuft nur
für deinen Windows-Benutzer.

---

## 7) So funktionieren die automatischen Updates

- Der Server prüft alle **5 Minuten** (einstellbar über `AUTO_UPDATE_CHECK_SECONDS`),
  ob auf GitHub im `main`-Branch neue Änderungen angekommen sind (z.B. wenn ein
  neuer Pull Request gemergt wurde).
- Wenn ja: Die neuen Dateien werden automatisch heruntergeladen und installiert
  – **aber nur, wenn gerade kein Render-Auftrag läuft**. Der Server startet
  danach selbst neu.
- Deine Einstellungen (`.env`), Blender-Installation, heruntergeladene Avatare
  und gerenderten Bilder bleiben dabei unberührt.
- Manuell sofort updaten: `03_stop.bat` und dann `02_start.bat` ausführen.

---

## 8) Vom Handy/zweiten PC aus? (Auf anderen Geräten nutzen)

Der Server läuft auf dem PC, auf dem du ihn installiert hast.

- **Roblox Studio auf demselben PC:** Adresse bleibt `http://localhost:8000`.
- **Roblox Studio auf einem anderen Gerät im selben WLAN:**
  1. Auf dem **Server-PC** die IP-Adresse herausfinden: `Windows-Taste` →
     `cmd` eingählen → `ipconfig` → bei „IPv4-Adresse“ steht z.B. `192.168.1.50`.
  2. Im Roblox-Server-Skript `RENDER_SERVER_URL` auf
     `http://192.168.1.50:8000` ändern.
  3. Windows-Firewall muss den Port erlauben (beim ersten Start „Zulassen“
     klicken; sonst Systemsteuerung → Windows Defender Firewall → „App durch
     Firewall lassen“ → Python aktivieren).
- **Veroeffentlichtes Spiel im echten Roblox-Client:** `localhost` geht
  **nicht**. Roblox startet das Spiel auf Cloud-Servern – die kennen deinen
  PC nicht. Siehe Abschnitt 8b.

⚠️ Sicherheit: Gib den Port **nicht** im Router nach außen frei (kein
„Port-Forwarding“). Für die Öffentlichkeit nutzen wir einen Tunnel
(Abschnitt 8b), der HTTPS mitbringt.

---

## 8b) Spiel veröffentlichen: die richtige URL finden

In **Roblox Studio** auf demselben PC reicht:

```lua
local RENDER_SERVER_URL = "http://localhost:8000"
```

Sobald Spieler das Spiel **im Roblox-Client** öffnen (Play-Button auf der
Website / App), läuft der Game-Server **bei Roblox**, nicht auf deinem PC.
`localhost` zeigt dann auf Roblox selbst – dein Render-Server wird nie erreicht.

Zusätzlich verlangt Roblox im Live-Spiel **HTTPS** (nicht `http://`).

**So bekommst du die richtige Adresse (kostenlos):**

1. Render-Server wie immer starten: `02_start.bat` (Fenster offen lassen).
2. Zusätzlich `08_oeffentliche_adresse.bat` doppelklicken.
3. Nach ein paar Sekunden erscheint eine Adresse wie
   `https://irgendwas-zufaellig.trycloudflare.com`.
4. Diese Adresse **komplett** im Lua-Skript eintragen:
   ```lua
   local RENDER_SERVER_URL = "https://irgendwas-zufaellig.trycloudflare.com"
   ```
5. Wenn du in der `.env` ein `BRS_ACCESS_TOKEN` gesetzt hast, denselben Wert
   bei `RENDER_ACCESS_TOKEN` im Skript eintragen.
6. Spiel in Studio speichern / veröffentlichen. **Beide schwarzen Fenster
   offen lassen**, solange jemand spielt. Der PC muss an sein.

Die Quick-Tunnel-Adresse **ändert sich nach jedem Neustart** von
`08_oeffentliche_adresse.bat`. Dann die neue URL wieder ins Skript kopieren.

**Woran erkenne ich, welche URL ich brauche?**

| Wo testest du? | Welche URL? |
|---|---|
| Studio, Play auf **diesem** PC | `http://localhost:8000` |
| Studio auf einem **anderen** Gerät im WLAN | `http://192.168.x.x:8000` (ipconfig) |
| Echtes Spiel / Roblox-App / Freunde | `https://….trycloudflare.com` aus `08_oeffentliche_adresse.bat` |

Tipp: `09_verbindung_pruefen.bat` zeigt an, ob gerade eine öffentliche URL
aktiv ist. Dieselbe Info steht auch auf http://localhost:8000.

---

## 9) Roblox Open-Cloud-API-Key anlegen (seit März 2026 nötig!)

Der Server lädt **kein Profilbild**. Er holt das echte **3D-Modell** deines
Avatars (OBJ + Materialien + Texturen) über Roblox’ `avatar-3d`-API
(`thumbnails.roblox.com/v1/users/avatar-3d`). Der Name „Thumbnail“ ist
irreführend: die Antwort ist ein JSON-Manifest mit 3D-Dateien, kein PNG.

Seit dem **23. März 2026** blockiert Roblox diesen 3D-Download ohne Login.
Ohne Key siehst du genau den Fehler aus deinem Test:

`3D-Avatar-Download von Roblox abgelehnt (HTTP 403)` bzw. `HTTP 401`.

**So legst du den Key an (einmalig, kostenlos):**

1. Gehe zu https://create.roblox.com/dashboard/credentials
   (Creator-Dashboard → **Open Cloud** → **Credentials** / API Keys).
2. **Create API Key**, Name z.B. `blender-render`.
3. Unter **Access Permissions**:
   - System / API-System: **`thumbnails`**
   - Operation: **`Read`**
   - Das ist der wichtige Teil. Optional zusätzlich
     **Assets → Asset Legacy Delivery → Read** (nur Ausweichweg).
4. Bei **IP Access** am einfachsten **keine Einschränkung** (oder deine
   aktuelle öffentliche IP erlauben). Eine falsche IP-Sperre erzeugt wieder 403.
5. Key erzeugen und **sofort kopieren** (wird nur einmal angezeigt).
6. `06_config_bearbeiten.bat` → Zeile
   `ROBLOX_API_KEY=` und den Key **direkt dahinter**, eine Zeile, **keine**
   Anführungszeichen, keine Leerzeichen.
7. Speichern. Server neu starten: `03_stop.bat`, dann `02_start.bat`.
8. Kontrolle: Im Server-Fenster muss stehen `API-Key: gesetzt`.
   Zusätzlich `09_verbindung_pruefen.bat` ausführen – die Zeile
   „Roblox 3D-Avatar-API“ sollte OK sein.

---

## 10) Wo finde ich die gerenderten Bilder?

Alle Ergebnisse liegen im Projektordner:

```
BlenderRenderServer\
  └── data\jobs\<Auftrags-ID>\
        ├── model\avatar.obj      ← das 3D-Modell (plus avatar.mtl + Texturen)
        └── render.png            ← das fertige Render-Bild
```

Du kannst die Bilder jederzeit direkt öffnen oder weiterverwenden.

---

## 11) Beenden, Neustart, Rückgängig

| Ich will … | Das tun |
|---|---|
| den Server **jetzt aus** machen | `03_stop.bat` |
| den Server wieder anmachen | `02_start.bat` |
| den Server **nie wieder automatisch** starten | `05_autostart_entfernen.bat` |
| alles komplett löschen | Autostart entfernen, Ordner löschen. Fertig (Python/Blender im Ordner werden mitgelöscht; ein evtl. separat installiertes Python bleibt). |

---

## 12) Fehlersuche (häufige Probleme)

| Problem | Ursache & Lösung |
|---|---|
| Roblox-Console zeigt `🔴 SERVER DOWN` | Server läuft nicht → `02_start.bat` starten. Falls er läuft: stimmt die Adresse/der Port im Lua-Skript mit `BRS_PORT` aus der `.env` überein? Studio auf anderem Gerät? Dann IP statt `localhost` benutzen (Abschnitt 8). |
| Roblox-Fehler `Http requests are not enabled` | In Studio: Home → Game Settings → Security → **Allow HTTP Requests = ON**, dann Play neu starten. |
| `01_setup.bat` bleibt beim Blender-Download hängen | Internet prüfen und Setup einfach nochmal starten (es macht da weiter, wo es aufgehört hat – Blender wird erst entpackt, wenn es komplett geladen ist). Alternativ Blender manuell von blender.org laden (ZIP-Version 4.5) und in den Ordner `tools\blender` entpacken (so, dass `tools\blender\blender.exe` existiert), dann Setup erneut starten. |
| `HTTP 403` / `HTTP 401` beim Avatar / „3D-Avatar-Download abgelehnt“ | Kein oder falscher API-Key. Abschnitt 9 befolgen (`thumbnails: Read`, Server neu starten). Das ist der 3D-Modell-Download, kein Profilbild. |
| `GitHub nicht erreichbar` | Nur das Auto-Update ist betroffen, **Rendern geht trotzdem**. Firewall/Antivirus für `github.com` + `python.exe` erlauben, oder `AUTO_UPDATE=false` in der `.env`. Details: `09_verbindung_pruefen.bat`. |
| Im echten Spiel keine Verbindung, in Studio schon | `localhost` geht nur in Studio. Abschnitt 8b: `08_oeffentliche_adresse.bat` und die `https://`-URL ins Lua-Skript. |
| `Expected identifier … got '<'` | Du hast eine `.rbxmx`-XML-Datei als Skript eingefügt. Nur den **Text** aus den `.lua`-Dateien kopieren. |
| `user_exporter.rbxmx` / `Animation Spoofer` in der Konsole | Andere Studio-Plugins, nicht dieser Render-Server. Kann ignoriert werden. |
| `Benutzername 'x' wurde nicht gefunden` | Schreibweise des Roblox-Namens im Server-Skript prüfen. |
| Render dauert sehr lange | `RENDER_SAMPLES` in der `.env` auf z.B. `48` setzen und neu starten. |
| Bild sieht „geisterhaft“ aus | Das ist Glas! 😄 Für kräftigere Optik: `RENDER_TRANSPARENT_BG=false` (Himmelshintergrund) und ggf. `RENDER_MATERIAL=original` testen. |
| In der GUI erscheint kein Bild / Meldung „EditableImage konnte nicht erstellt werden“ | In Studio sollte das normalerweise gehen. Im echten Online-Spiel braucht der Ersteller-Account 13+ ID-Verifizierung. Auch prüfen, ob beide Skripte korrekt liegen (Server-Script in ServerScriptService, LocalScript in StarterPlayerScripts). |
| `CreateEditableImage`-Fehler in der Konsole | Studio auf dem neuesten Stand halten (EditableImage ist ein neueres Feature). |
| Port 8000 schon belegt | In `.env` z.B. `BRS_PORT=8010` setzen **und** im Lua-Skript `RENDER_SERVER_URL = "http://localhost:8010"`. |
| Antivirus meckert | Die Skripte machen nichts Verbotenes (Downloads nur von python.org, blender.org, roblox.com und github.com). Bei Bedarf eine Ausnahme für den Projektordner hinzufügen. |
| Auftrag hängt in `queued` fest | Es läuft noch ein anderer Auftrag (nur einer gleichzeitig!). Einfach warten oder Server mit `03_stop.bat`/`02_start.bat` neu starten. |

**Auftrag per Browser senden (zum Testen):** In die Adresszeile kann man kein
POST schicken – nutze einfach Roblox (`!render Name` im Chat geht auch!) oder
den Test-Modus. Der einfachste Test bleibt `BRS_TEST_MODE=true`.

---

## 13) Häufige Fragen

**Kostet das etwas?** Nein. Python, Blender und die Roblox-APIs sind kostenlos.

**Kann der Server Schaden anrichten?** Er lädt nur Dateien von bekannten
Adressen (python.org, blender.org, roblox.com, github.com), rendert Bilder und
antwortet auf Anfragen aus deinem Heimnetz. Er führt nichts von Fremden aus.

**Was passiert bei einem Stromausfall mitten im Rendern?** Nicht Schlimmes –
der Auftrag bricht ab. Nach dem Neustart startet der Server automatisch neu
(wenn Autostart aktiv) und Roblox reicht den Auftrag einfach erneut ein.

**Warum nur ein Auftrag gleichzeitig?** Damit die Konsole und der Ablauf immer
klar bleiben und dein PC nicht überlastet wird. Weitere Aufträge landen in der
Warteschlange (maximal einer wartet, der Neueste gewinnt).

**Ist „Thumbnail-API“ nicht nur das Profilbild?** Nein. Roblox nennt den
Endpunkt `avatar-3d` intern „Thumbnail“, aber die Antwort ist ein JSON mit
**OBJ + MTL + Texturen** – genau das 3D-Modell, das Blender braucht. Das
normale Profilbild wäre `avatar-headshot` (ein PNG). Das verwenden wir nicht.

**Warum sagt Studio etwas von `user_exporter.rbxmx` / Animation Spoofer?**
Das kommt von anderen Plugins, nicht von diesem Projekt. Unsere Skripte
heißen `RenderServerService` / `RenderClient` und schreiben immer
`[BlenderRender]` davor.

---

## 14) Für Neugierige: Was passiert da technisch?

1. Das Roblox-Server-Skript schickt `POST /jobs {"username":"..."}` an deinen PC.
2. Der Server löst den Namen zur Roblox-UserId auf (users.roblox.com).
3. Er holt das **3D-Thumbnail-Manifest** (thumbnails.roblox.com, Format
   `avatar-3d`): das enthält OBJ-, Material- und Textur-Verweise.
4. OBJ/MTL/Texturen werden vom Roblox-CDN in den Auftragordner geladen.
5. Blender (headless) importiert das Modell, richtet es aus, setzt ein
   physikalisches **Glas-Material** (Transmission 100 %, IOR 1.45, klarlack-
   Beschichtung für schöne Reflexe), positioniert Kamera + Himmel + Lichter
   automatisch und rendert mit **Cycles** (Denoising an).
6. Das PNG wird in rohe RGBA-Pixel zerlegt. Roblox lädt es zeilenweise
   (`image/rows`) und schreibt es in ein **EditableImage** – und leitet dieselben
   Pakete per **RemoteEvent** an den Client weiter, der sein eigenes
   EditableImage in einem GUI anzeigt.
