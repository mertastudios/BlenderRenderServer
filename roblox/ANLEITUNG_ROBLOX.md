# 🎮 Anleitung: Roblox-Studio-Teil einrichten (Schritt für Schritt)

Diese Anleitung gehört zum BlenderRenderServer. Der PC-Teil muss zuerst
eingerichtet sein und laufen (siehe `ANLEITUNG.md` im Hauptordner).

**Was du hier machst:**
1. Einmalig „HTTP-Anfragen“ in deinem Projekt erlauben
2. Das Server-Skript einfügen (fragt deinen Render-PC ab)
3. Das Client-Skript einfügen (zeigt das Bild im GUI)

---

## Schritt 0: Projekt öffnen

1. Roblox Studio starten.
2. **New** → Vorlage **Baseplate** auswählen (oder ein bestehendes Projekt öffnen).

## Schritt 1: HTTP-Anfragen erlauben (WICHTIG – ohne das geht nichts!)

1. Oben im Menü: **Home** → **Game Settings** (Zahnrad „Spieleinstellungen“).
2. Links im Fenster: **Security** (Sicherheit).
3. **„Allow HTTP Requests“** (HTTP-Anfragen zulassen) auf **ON** stellen.
4. Mit **Save** speichern. (Falls Studio fragt, ob das Spiel „veröffentlicht“
   werden soll, kannst du einfach bestätigen – es bleibt dein privates Projekt.)

> ⚠️ Wenn du das vergisst, meldet Roblox später:
> „Http requests are not enabled“ – dann diesen Schritt nachholen.

## Schritt 2: Server-Skript einfügen

1. Öffne den **Explorer** (Ansicht/View → Explorer).
2. Klicke im Explorer auf **ServerScriptService**.
3. Rechtsklick darauf → **Insert Object** → **Script** (nicht LocalScript!).
4. Klicke im Explorer auf das neue „Script“.
5. Lösche den Inhalt (`print("Hello world!")`) und füge den **kompletten
   Inhalt** der Datei `RenderServerService.server.lua` ein.
6. **Passe oben im Skript zwei Zeilen an:**
   ```lua
   local RENDER_SERVER_URL = "http://localhost:8000" -- Adresse deines Render-Servers
   local ROBLOX_USERNAME   = "DeinRobloxName"         -- <<< DEIN NAME!
   ```
   - `RENDER_SERVER_URL`: bleibt `http://localhost:8000`, wenn Studio auf
     demselben PC läuft wie der Render-Server. **Für ein veröffentlichtes
     Spiel reicht das nicht** – dann `08_oeffentliche_adresse.bat` starten
     und die `https://....trycloudflare.com` URL hier eintragen
     (siehe `ANLEITUNG.md`, Abschnitt 8b).
   - `RENDER_ACCESS_TOKEN`: nur nötig, wenn in der `.env` `BRS_ACCESS_TOKEN`
     gesetzt ist. Dann **derselbe** Wert.
   - `ROBLOX_USERNAME`: der Avatar, der gerendert wird.
7. Bennene das Skript um in `BlenderRenderServer` (Doppelklick auf den Namen
   im Explorer) – hilft, den Überblick zu behalten.

## Schritt 3: Client-Skript einfügen

1. Klicke im Explorer auf **StarterPlayer** → **StarterPlayerScripts**.
   (Beide Punkte aufklappen, bis du StarterPlayerScripts siehst.)
2. Rechtsklick → **Insert Object** → **LocalScript** (jetzt wirklich Local!).
3. Inhalt leeren und den kompletten Inhalt der Datei `RenderClient.client.lua`
   einfügen.
4. Umtauufen in `BlenderRenderClient`.

## Schritt 4: Testen! 🚀

1. Stelle sicher, dass auf deinem PC der Render-Server läuft (`02_start.bat`,
   schwarzes Fenster mit „ist ONLINE“).
2. In Studio oben auf **Play** drücken.
3. Öffne die Konsole: **View** → **Output** (Ausgabe).
4. Du siehst jetzt die genauen Schritte mit Fortschritt und Restzeit:

```
[BlenderRender] Server-Skript initialisiert!
[BlenderRender] Server-Adresse: http://localhost:8000
[BlenderRender] Standard-User : DeinRobloxName
==============================================================
[BlenderRender] [1/5] Server verbunden: Render-Server ONLINE (Version abc1234) (5% - Rest: ~30s)
[BlenderRender] [1/5] Auftrag angenommen: Auftrag fuer 'DeinRobloxName' registriert (8% - Rest: ~28s)
[BlenderRender] [2/5] Avatar-Koerperteile & Texturen laden: 15 Teile geladen (15% - Rest: ~25s)
[BlenderRender] [3/5] 3D-Rig & Materialien in Blender vorbereiten: R15-Armature aufgebaut (25% - Rest: ~20s)
[BlenderRender] [4/5] Blender Cycles High-End Rendern: Sample 48/96 (65% - Rest: ~12s)
[BlenderRender] [5/5] Bild uebertragen: Empfange 1024x1024 Pixel ... (95% - Rest: ~2s)
[BlenderRender] [5/5] Fertig!: Bild (1024x1024) erfolgreich im GUI angezeigt. (100% - Rest: ~0s)
```

5. Im Spiel öffnet sich das moderne GUI-Fenster **„🧊 Blender Render Studio“**:
   - Oben: Eingabefeld für beliebige Benutzernamen & **„🚀 Rendern“**-Knopf
   - Mitte: Live-Bildanzeige mit EditableImage
   - Unten: Schritt-Badge (`Schritt 4 von 5`), geschätzte Restzeit (`⏱️ Restzeit: ~12 s`),
     präziser Statustext und animierter Farbverlauf-Ladebalken mit Prozentangabe!

## Extra: Weitere Renders starten

- **Direkt im GUI:** Namen in das Textfeld eingeben und auf **„🚀 Rendern“** klicken!
- **Oder im Chat (Taste `/`):**
  - `!render` → rendert den aktuellen Benutzer erneut
  - `!render AndererName` → rendert den Avatar eines beliebigen anderen Spielers

---

## 🛠️ Probleme & Lösungen

| Meldung / Problem | Lösung |
|---|---|
| `Http requests are not enabled` | Schritt 1 machen (Allow HTTP Requests = ON) |
| `🔴 SERVER DOWN` wiederholt | Render-Server läuft nicht: `02_start.bat` starten; Port im Skript mit `BRS_PORT` aus `.env` abgleichen |
| `❌ FEHLER: Roblox-Benutzername 'x' wurde nicht gefunden` | Namen im Skript korrekt schreiben (Groß-/Kleinschreibung ist egal) |
| `❌ FEHLER: 3D-Thumbnail wurde nicht rechtzeitig fertig` | Roblox-Server hatten Schluckauf – einfach nochmal (`!render`) |
| GUI bleibt leer, Konsole sagt aber „FERTIG“ | Liegt das Client-Skript wirklich als **LocalScript** in StarterPlayerScripts? Play neu starten |
| „EditableImage konnte nicht erstellt werden“ | Studio aktualisieren; im echten Online-Spiel braucht der Account 13+ ID-Verifizierung (in Studio normalerweise unnötig) |
| Bild wird sehr langsam übertragen | Das ist normal (1024×1024 Pixel kommen in kleinen Paketen an). Auf dem Server-PC (nicht Studio!) kann man in der `.env` auch `RENDER_WIDTH=512`, `RENDER_HEIGHT=512` einstellen – dann ist alles schneller (aber etwas unschärfer). |
| Ich sehe das GUI nicht | Esc/Menü prüfen; das GUI ist zentriert und kann mit ✕ geschlossen werden – danach Play neu starten |

---

## 📡 Was die Skripte genau tun (Kurzform)

**Server-Skript (`RenderServerService.server.lua`):**
- Legt das RemoteEvent `BlenderRender_Image` im ReplicatedStorage an
- Startet automatisch die Render-Pipeline (wiederholte Statusabfragen alle 3 s)
- Holt das fertige Bild zeilenweise als **RGBA-Pixelpuffer** vom Render-Server
- Schreibt es serverseitig in ein **EditableImage** (liegt dann im ServerStorage)
- Leitet jedes Pixel-Paket per RemoteEvent an den ersten Spieler weiter

**Client-Skript (`RenderClient.client.lua`):**
- Baut das GUI (Fenster, Bildfläche, Statuszeile, Schließen-Button)
- Erstellt beim ersten Paket sein eigenes clientseitiges **EditableImage**
  (EditableImages werden nicht automatisch server→client synchronisiert,
  deshalb der Umweg über die RemoteEvents)
- Schreibt jede ankommende Pixelzeile per `WritePixelsBuffer` hinein und
  zeigt das Bild über `ImageContent = Content.fromObject(...)` an
