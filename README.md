# 🧊 BlenderRenderServer

**Roblox-Avatare & Szenen als 3D-Modell herunterladen und mit Blender Cycles rendern – gesteuert über `manage_render` in Roblox Studio.**

```
┌─────────────────────────┐   HTTP (localhost)   ┌──────────────────────────────┐
│  Roblox Studio          │ ◄──────────────────► │  Dein PC (dieses Programm)  │
│  ─────────────          │                      │  ──────────────────────────  │
│  manage_render          │  1. "Create", Folder │  1. Szene & Avatare laden    │
│  (BindableFunction)     │                      │     (3D OBJ + MTL + Texturen)│
│  - "Create", Folder     │  2. "Status", JobID  │  2. Custom Models & Posing   │
│  - "Status", JobID      │     ("active", 14s)  │  3. Cycles High-End Render   │
│  - "Download", JobID    │  3. "Download", JobID│  4. RGBA Pixelbuffer senden  │
│                         │     (Pixelbuffer)    │  5. 7 Tage Speicher & Clean  │
└─────────────────────────┘                      └──────────────────────────────┘
```

## ✨ Highlights & Features

- **BindableFunction `manage_render` in `ServerStorage`**:
  - `"Create", FolderInstance` $\rightarrow$ Registriert neuen Render-Auftrag mit allen Avataren, Posen und 3D-Modellen
  - `"Status", JobID` $\rightarrow$ Liefert den aktuellen Status (`queued`, `active`, `done`, `not_found`), Warteschlangen-Position und sekundengenaue Restzeitschätzung
  - `"Download", JobID` $\rightarrow$ Lädt das fertige Bild stückweise als RGBA-Pixelbuffer für `EditableImage`
- **Exakte Posen-Übernahme**: Überträgt die exakten CFrames (Position & 3D-Rotation) aller R15/R6-Körperteile aus Roblox Studio direkt nach Blender.
- **Multi-Avatar & Szenen-Rendering**: Mehrere Avatare und Objekte können gleichzeitig in einer Szene gerendert werden.
- **Spezial-Herzform-Hände (Heart Hands GFX)**: Ersetzt die Hände des Avatars automatisch durch ein 3D-Herz-Hände-Modell und passt die Hautfarbe an (`HeartHands = true`).
- **Benutzerdefinierte 3D-Modelle (`assets/models/`)**: Eigene `.obj`-Modelle im Repository ablegen und per `ModelName`-Attribut in der Szene platzieren.
- **3 Material-Modi**:
  - `MATT`: Diffuser, matter Studio-Look
  - `GLAS`: Signature-Klarlack-Glasur mit stufenloser Glanz-Stärke (`GlassStrength`)
  - `DURCHSICHTIGES_GLAS`: Echtes, lichtbrechendes transparentes Glas
- **Unendliche FIFO-Warteschlange**: Aufträge werden nacheinander sequenziell abgearbeitet.
- **7-Tage-Aufbewahrung**: Fertige Render-Bilder werden auf dem Server gespeichert und nach 7 Tagen automatisch gelöscht.
- **Token-Schutz**: Passwort in `.env` (`BRS_ACCESS_TOKEN`) und Lua-Skript (`RENDER_ACCESS_TOKEN`) schützt deinen Server vor fremden Zugriffen.

---

## 🚀 Schnellstart

1. `01_setup.bat` ausführen (installiert Python + Blender 4.5 automatisch).
2. `06_config_bearbeiten.bat` ausführen: `ROBLOX_API_KEY` (und optional `BRS_ACCESS_TOKEN`) eintragen.
3. `02_start.bat` starten.
4. `roblox/RenderServerService.server.lua` in Roblox Studio in den `ServerScriptService` einfügen.
5. In einem Script `manage_render:Invoke("Create", workspace.Folder)` aufrufen!

📖 **Vollständige Anleitung & Attribute:** Siehe [`ANLEITUNG.md`](ANLEITUNG.md) und [`roblox/ANLEITUNG_ROBLOX.md`](roblox/ANLEITUNG_ROBLOX.md).

---

## 📁 Ordnerstruktur

```
BlenderRenderServer/
├── assets/
│   ├── models/                   ← Eigene 3D-Modelle (z.B. Sword.obj, heart_hands.obj)
│   └── hands/                    ← Spezial-Hände Modelle (heart_hands.obj)
├── roblox/
│   ├── RenderServerService.server.lua ← ServerScript mit manage_render BindableFunction
│   └── ANLEITUNG_ROBLOX.md
├── server/
│   ├── app.py                    ← FastAPI Server & Warteschlange
│   ├── avatar.py                 ← Roblox 3D Avatar Downloader
│   ├── blender_render.py         ← Blender Cycles Szenen- & Material-Renderer
│   ├── blender_runner.py         ← Blender Prozess-Starter
│   └── config.py                 ← Konfiguration (.env) & 7-Tage-Retention
├── data/jobs/                    ← Gespeicherte Render-Bilder (7 Tage Retention)
├── 01_setup.bat / 02_start.bat
└── ANLEITUNG.md                  ← Ausführliche Dokumentation
```

## 📝 Lizenz

MIT – siehe [LICENSE](LICENSE).
