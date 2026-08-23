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
4. Du siehst jetzt ungefähr sowas (Reihenfolge kann leicht abweichen):

```
[BlenderRender] Server-Skript geladen!
[BlenderRender] Render-Server : http://localhost:8000
[BlenderRender] Avatar-User   : DeinRobloxName
==============================================================
[BlenderRender] 🔴 SERVER DOWN – keine Verbindung ...   ← nur, wenn der Server AUS ist
[BlenderRender] 🟢 Render-Server ONLINE (Version abc1234, Blender: bereit)
[BlenderRender] 📤 Auftrag angenommen: Avatar von 'DeinRobloxName' (job f727e9b4)
[BlenderRender] ⏳ Avatar wird von Roblox heruntergeladen (3D-Modell inkl. Texturen) ...
[BlenderRender] ⏳ 3D-Modell wird in Blender geladen, Glas-Material wird erstellt ...
[BlenderRender] ⏳ Blender Cycles RENDERT den Avatar ... 34 %
[BlenderRender] ⏳ Blender Cycles RENDERT den Avatar ... 71 %
[BlenderRender] ✅ Render abgeschlossen! ('DeinRobloxName')
[BlenderRender] 📦 Bild ist fertig: 1024x1024 Pixel - uebertrage es stueckweise ...
[BlenderRender] 🖼️ Server-EditableImage erstellt (1024x1024)
[BlenderRender] 📡 Bild-Uebertragung: 8 / 64 Pakete (12 % der Zeilen)
[BlenderRender] 📡 Bild-Uebertragung: 32 / 64 Pakete (50 % der Zeilen)
[BlenderRender] 🎉 FERTIG! Bild (1024x1024) komplett - es sollte im Client-GUI sichtbar sein.
```

5. Gleichzeitig erscheint in der Spielszene das GUI-Fenster
   **„🧊 Avatar-Render (Blender Cycles)“** – erst mit dem Statustext, dann
   füllt sich das Bild von oben nach unten mit deinem Glas-Avatar. 🧊

## Extra: Weitere Renders starten

Tippe im **Chat** (Testspiel, Taste `/`):
- `!render` → rendert den Avatar aus `ROBLOX_USERNAME` noch einmal
- `!render AndererName` → rendert einen beliebigen anderen Avatar

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
