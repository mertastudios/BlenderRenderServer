# 🧊 BlenderRenderServer

**Roblox-Avatare automatisch als 3D-Modell herunterladen und mit Blender Cycles in Glas rendern – komplett auf deinem eigenen PC, kostenlos.**

Das System besteht aus zwei Teilen:

```
┌─────────────────────┐   HTTP (localhost)   ┌──────────────────────────────┐
│  Roblox Studio      │ ◄──────────────────► │  Dein PC (dieses Programm)  │
│  ─────────────      │                      │  ──────────────────────────  │
│  Server-Skript      │  1. "Rendere Avatar  │  1. Avatar von Roblox laden  │
│  (ServerScript-     │      von MaxMuste    │     (OBJ + Material +        │
│   Service)          │      Erman!"         │      Texturen)               │
│  Client-Skript      │  2. Status abfragen  │  2. Blender Cycles: Glas-    │
│  (LocalScript)      │     ("rendert...",   │     Render in 1024x1024      │
│                     │     "Warteschlange") │  3. fertiges Bild als Pixel- │
│  GUI zeigt das      │  3. Bild stückweise  │     Daten bereitstellen      │
│  fertige Bild       │     abholen          │  4. Auto-Update von GitHub   │
└─────────────────────┘                      └──────────────────────────────┘
```

## ✨ Features

- **Ein-Klick-Setup**: `01_setup.bat` installiert Python + Blender 4.5 automatisch (Windows 10/11)
- **Komplett kostenlos** – alles läuft lokal auf deinem PC
- **Auto-Start**: startet nach jedem PC-Neustart automatisch (auf Wunsch)
- **Auto-Update**: sobald auf GitHub neue Änderungen (gemergte Pull Requests) im `main`-Branch ankommen, aktualisiert sich das System selbst und startet neu
- **Nur ein Auftrag gleichzeitig** (+ maximal einer in der Warteschlange) – immer klar, was gerade passiert
- **Roblox-Integration**: fertiges Bild wird stückweise als **EditableImage**-Pixelpuffer an Roblox übertragen und dort per RemoteEvent im Client in einem GUI angezeigt
- **Konfiguration per `.env`-Datei** (mit `06_config_bearbeiten.bat` bequem im Editor änderbar)
- **3D-Avatar, kein Profilbild**: es wird das echte OBJ/MTL/Textur-Modell geladen (Roblox-Endpunkt `avatar-3d`)
- **Öffentliche HTTPS-Adresse** für veröffentlichte Spiele (`08_oeffentliche_adresse.bat`)

## 🚀 Schnellstart (Windows)

| Schritt | Aktion |
|---|---|
| 1 | Repository herunterladen (grüner **Code**-Knopf → **Download ZIP**) und entpacken |
| 2 | `01_setup.bat` doppelklicken (installiert alles, einmalig, ~10 Minuten) |
| 3 | `02_start.bat` doppelklicken → Server läuft |
| 4 | In Roblox Studio die zwei Skripte aus dem Ordner `roblox/` einfügen (Anleitung: [`ANLEITUNG.md`](ANLEITUNG.md)) |
| 5 | Open-Cloud-API-Key mit Recht **thumbnails: Read** in die `.env` (sonst HTTP 403 beim 3D-Download) |
| 6 | Optional: `04_autostart_installieren.bat` → startet künftig automatisch bei PC-Start |
| 7 | Für ein **veröffentlichtes** Spiel: `08_oeffentliche_adresse.bat` und die `https://`-URL ins Lua-Skript |

📖 **Die komplette, sehr ausführliche Anleitung für Anfänger steht in [`ANLEITUNG.md`](ANLEITUNG.md)!**
🎮 Die Roblox-Studio-Einrichtung zusätzlich Schritt für Schritt: [`roblox/ANLEITUNG_ROBLOX.md`](roblox/ANLEITUNG_ROBLOX.md)

## 📁 Ordnerstruktur

```
BlenderRenderServer/
├── 01_setup.bat                  ← 1x ausführen: installiert Python, Pakete, Blender
├── 02_start.bat                  ← Server starten
├── 03_stop.bat                   ← Server stoppen
├── 04_autostart_installieren.bat ← Autostart bei PC-Start einrichten
├── 05_autostart_entfernen.bat    ← Autostart entfernen
├── 06_config_bearbeiten.bat      ← Einstellungen (.env) im Editor öffnen
├── 07_im_browser_testen.bat      ← Statusseite im Browser öffnen
├── 08_oeffentliche_adresse.bat   ← HTTPS-URL für veröffentlichte Spiele
├── 09_verbindung_pruefen.bat     ← Roblox / GitHub / API-Key testen
├── .env                          ← Deine Einstellungen (wird beim Setup erstellt)
├── run.py                        ← Starter/Watchdog (von 02_start.bat benutzt)
├── server/                       ← Der eigentliche Server-Code (Python)
│   ├── app.py                    ← Web-API (FastAPI)
│   ├── avatar.py                 ← Roblox-Avatar-Download (OBJ/MTL/Texturen)
│   ├── blender_render.py         ← Rendering in Blender (Glas-Material, Cycles)
│   ├── blender_runner.py         ← Findet & startet Blender
│   ├── updater.py                ← Auto-Update von GitHub
│   ├── tunnel.py                 ← Öffentliche HTTPS-Adresse (Cloudflare)
│   └── diagnostics.py            ← Verbindungscheck (09_verbindung_pruefen.bat)
├── roblox/                       ← Die zwei Lua-Skripte für Roblox Studio
├── tools/blender/                ← Blender-Installation (kommt vom Setup)
├── data/jobs/                    ← Gerenderte Bilder + heruntergeladene Avatare
└── logs/                         ← Protokolle
```

## 🔌 API (für Fortgeschrittene)

| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/health` | Ist der Server erreichbar? (inkl. `api_key_set`, `public_url`) |
| GET | `/diagnostics` | Roblox-3D-API, GitHub, Blender, API-Key prüfen |
| POST | `/jobs` | Auftrag anlegen: `{"username": "Name"}` |
| GET | `/jobs/current` | Status des aktuellen Auftrags (state, progress, ...) |
| GET | `/jobs/{id}/image/info` | Bildgröße (wenn fertig) |
| GET | `/jobs/{id}/image/rows?y=0&rows=16` | Rohe RGBA-Pixelzeilen (stückweise) |
| GET | `/jobs/{id}/image.png` | Fertiges Bild als PNG |

Zustände: `queued → downloading → loading → rendering → encoding → done` (oder `error`).

## 📝 Lizenz

MIT – siehe [LICENSE](LICENSE).
