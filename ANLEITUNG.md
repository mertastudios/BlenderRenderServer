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
- [ ] Optional (nicht nötig!): ein Roblox Open-Cloud-API-Key (siehe Abschnitt 9)

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
| `ROBLOX_API_KEY` | Optionaler Roblox-API-Key (siehe Abschnitt 9). **Darf leer bleiben!** | leer |
| `AUTO_UPDATE` | `true` = automatische Updates von GitHub (empfohlen). | `true` |
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
- **Kostenlos auf einem Online-PC hosten:** Möglich, aber nicht nötig – für
  dein Szenario (Studio-Tests zuhause) ist der eigene PC die einfachste,
  sorgenfreieste Lösung.

⚠️ Sicherheit: Gib den Port **nicht** im Router nach außen frei (kein
„Port-Forwarding“). Der Server ist fürs Heimnetz gedacht.

---

## 9) (Optional) Roblox Open-Cloud-API-Key hinterlegen

Der Avatar-Download funktioniert **auch ohne** API-Key über die öffentlichen
Roblox-Endpunkte. Der Key ist ein Zusatzweg (u.a. „asset-legacy-delivery“),
falls einzelne Roblox-Assets sonst nicht ladbar sind.

So erstellst du ihn (optional):
1. Gehe zu https://create.roblox.com/dashboard/credentials (Creator-Dashboard →
   „Open Cloud“ → „API Keys“ bzw. „Credentials“).
2. **Add API Key** (bzw. „Create“), Name z.B. `render-server`.
3. Bei Berechtigungen **Assets → Asset Legacy Delivery → Read** hinzufügen.
4. Schlüssel kopieren.
5. Bei uns eintragen: `06_config_bearbeiten.bat` → bei `ROBLOX_API_KEY=` den
   Schlüssel einfügen (alles in einer Zeile, keine Anführungszeichen).
6. Server mit `03_stop.bat` + `02_start.bat` neu starten.

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
