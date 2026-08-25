# 📖 Anleitung: Blender Render Server einrichten

Diese Anleitung führt dich durch die komplette Einrichtung des Blender Render Servers.

**Was du hast:**
Ein leistungsstarker Render-Server auf deinem PC, der direkt aus Roblox Studio über eine **`BindableFunction` in `ServerStorage` (`manage_render`)** gesteuert wird:
- Beliebige Szenen mit **mehreren Avataren** und **benutzerdefinierten 3D-Modellen**
- **Exakte Posen-Übernahme** (jede Körperteil-Rotation & Position aus Roblox)
- **3 Material-Modi:** `MATT`, `GLAS` (mit einstellbarer Prozent-Stärke) und `DURCHSICHTIGES_GLAS` (echtes transparentes Lichtbrechungsglas)
- **Spezial-Herzform-Hände** (Heart Hands GFX) mit automatischer Hautfarben-Anpassung
- **Unendliche FIFO-Warteschlange** mit sequenzieller Abarbeitung und sekundengenauer Restzeitschätzung
- **Automatische 7-Tage-Speicherung** aller Bilder auf dem Server
- **Passwort- / Token-Schutz** gegen unbefugten Zugriff

---

## 📋 Was du brauchst

- [ ] PC mit **Windows 10 oder 11** (oder Linux)
- [ ] **Roblox Studio** (kostenlos: https://create.roblox.com)
- [ ] **Roblox Open-Cloud-API-Key** mit dem Recht **`thumbnails: Read`** (Abschnitt 8) für den 3D-Avatar-Download
- [ ] Internetverbindung

---

## 1) Einrichtung auf dem PC (Schnellstart)

1. Lade das Repository herunter und entpacke es (z. B. nach `C:\BlenderRenderServer`).
2. Führe **`01_setup.bat`** aus (installiert Python, Pakete und Blender automatisch).
3. Öffne **`06_config_bearbeiten.bat`**, um deine `.env`-Datei anzupassen:
   - Trage deinen `ROBLOX_API_KEY` ein (Abschnitt 8).
   - Optional: Trage ein Passwort bei `BRS_ACCESS_TOKEN` ein (z. B. `BRS_ACCESS_TOKEN=MeinGeheimesPasswort123`).
4. Starte den Server mit **`02_start.bat`**.

---

## 2) Steuerung in Roblox Studio (`manage_render`)

In Roblox Studio wird die gesamte Steuerung über eine `BindableFunction` in `ServerStorage` namens **`manage_render`** abgewickelt.

### 🌟 1. Aktion: `"Create", FolderImWorkspace`
Erstellt einen neuen Render-Auftrag aus einem beliebigen Ordner oder Model im Workspace.

```lua
local ServerStorage = game:GetService("ServerStorage")
local manage_render = ServerStorage:WaitForChild("manage_render")

-- Beliebigen Ordner im Workspace übergeben
local success, result = manage_render:Invoke("Create", workspace.MeineRenderSzene)

if success then
    local jobId = result
    print("✅ Auftrag erfolgreich erstellt! Job-ID:", jobId)
else
    local errorMsg = result
    warn("❌ Fehler beim Erstellen des Auftrags:", errorMsg)
end
```

**Rückgabewerte bei `"Create"`:**
- `success` (`boolean`): `true` bei erfolgreicher Auftragserstellung, sonst `false`.
- `result` (`string`): Bei Erfolg die eindeutige **`jobId`** (z. B. `"a1b2c3d4e5f6"`), bei Fehler die **Fehlermeldung**.

---

### 🌟 2. Aktion: `"Status", jobId`
Fragt den aktuellen Status, die Warteschlangenposition und die geschätzte Restzeit ab.

```lua
local success, status = manage_render:Invoke("Status", jobId)

if success then
    print("Status:", status.state)              -- "queued", "active", "done" oder "not_found"
    print("Warteschlangen-Position:", status.queue_position) -- 1, 2, ... (0 wenn aktiv/fertig)
    print("Geschätzte Restzeit:", status.est_seconds_left, "Sekunden")
    print("Nachricht:", status.message)
else
    warn("Fehler bei der Statusabfrage:", status)
end
```

**Mögliche Status-Zustände (`status.state`):**
- `"queued"`: Auftrag wartet in der Warteschlange (`queue_position` = Platzierung, `est_seconds_left` = Restzeit).
- `"active"`: Render aktiv (Avatar-Download, Rigging, Blender Cycles Rendering).
- `"done"`: Fertig gerendert! Das Bild liegt auf dem Server bereit zum Download.
- `"not_found"`: Auftrag existiert nicht oder ist nach 7 Tagen abgelaufen.

---

### 🌟 3. Aktion: `"Download", jobId`
Lädt die fertigen Pixeldaten des gerenderten Bildes in Chunks herunter und liefert einen Buffer für `EditableImage`.

```lua
local success, imageData = manage_render:Invoke("Download", jobId)

if success then
    print("Bild heruntergeladen:", imageData.width, "x", imageData.height)
    
    -- Direkt in ein EditableImage schreiben:
    local AssetService = game:GetService("AssetService")
    local editableImage = AssetService:CreateEditableImage({ Size = imageData.size })
    editableImage:WritePixelsBuffer(Vector2.zero, imageData.size, imageData.buffer)
else
    warn("Download fehlgeschlagen:", imageData)
end
```

**Rückgabewerte bei `"Download"`:**
- `success` (`boolean`): `true` wenn Bild vorhanden und geladen, sonst `false`.
- `imageData` (`table`):
  - `width` (`number`): z. B. `1024`
  - `height` (`number`): z. B. `1024`
  - `size` (`Vector2`): `Vector2.new(1024, 1024)`
  - `buffer` (`buffer`): Kompletter RGBA-Pixelbuffer für `EditableImage:WritePixelsBuffer`

---

## 3) Attribute in Roblox Studio (Rigs & 3D-Modelle)

Alle Einstellungen nimmst du bequem über **Attributes** an deinen Objekten im Workspace-Ordner vor:

### 👤 Avatar-Rigs (R15 / R6)
Lege diese Attribute an deinem Rig-Model an:

| Attribut | Typ | Beschreibung | Standard |
|---|---|---|---|
| `Username` | `string` | Roblox-Benutzername des Avatars (z. B. `"MertaStudios"`). | Model-Name |
| `IsRig` | `boolean` | Markiert das Model explizit als Avatar-Rig. | `true` |
| `MaterialMode` | `string` | Material des Avatars: `"MATT"`, `"GLAS"` oder `"DURCHSICHTIGES_GLAS"`. | `"GLAS"` |
| `GlassStrength` | `number` | Stärke der Glas-Reflexion (`0.0` bis `1.0` oder `0` bis `100`). | `0.85` (85%) |
| `HeartHands` | `boolean` | **Herzform-Hände:** Ersetzt die Hände des Avatars durch das 3D-Herz-Hände-Modell! | `false` |
| `SkinColor` | `Color3` | Hautfarbe für Herz-Hände (wird sonst automatisch aus `Head.Color` ermittelt). | Kopf-Farbe |

> 💡 **Posen speichern:** Der Server übernimmt automatisch die **exakten Positionen, Größen und Rotationen** (CFrames) aller Körperteile des Rigs aus Roblox Studio nach Blender.

---

### 📦 Benutzerdefinierte 3D-Modelle & Parts
Für MeshParts, Parts mit SpecialMesh oder normale Parts:

| Attribut | Typ | Beschreibung | Standard |
|---|---|---|---|
| `ModelName` | `string` | Name der 3D-Datei im Ordner `assets/models/` (z. B. `"Sword"` für `assets/models/Sword.obj`). | Part-Name |
| `MaterialMode` | `string` | `"MATT"`, `"GLAS"` oder `"DURCHSICHTIGES_GLAS"`. | `"MATT"` |
| `GlassStrength` | `number` | Stärke des Glanzes (`0.0` bis `1.0`). | `0.85` |

---

## 4) Die 3 Material-Modi im Detail

1. **`MATT`**:
   - Klassischer, diffuser Studio-Look ohne störende Glanzreflexe.
   - Ideal für Kleidung, Hintergründe, Möbel und realistische Props.

2. **`GLAS`**:
   - Der legendäre BlenderRenderServer-Signature-Look: Opaker Körper mit edlem Klarlack-Glasur-Überzug.
   - Die Glanz-Stärke lässt sich über `GlassStrength` (z. B. `0.5` = 50 %, `0.85` = 85 %) stufenlos einstellen.

3. **`DURCHSICHTIGES_GLAS`**:
   - Echtes, transparentes Glas mit Lichtbrechung (Transmission 1.0, IOR 1.52, Cycles Raytracing).
   - Ideal für Kristall-Figuren, Diamanten, Brillen oder transparente Avatare.

---

## 5) Wo lege ich eigene 3D-Modelle & Spezial-Hände ab?

Im Projektordner gibt es den Ordner **`assets/models/`**:

```
BlenderRenderServer\
  ├── assets\
  │     ├── models\
  │     │     ├── heart_hands.obj     ← Herzform-Hände 3D-Modell (bereits enthalten!)
  │     │     ├── heart_hands.mtl
  │     │     ├── Sword.obj           ← Eigenes Modell (z. B. ModelName="Sword")
  │     │     └── Table.obj
  │     └── hands\
  │           └── heart_hands.obj
```

- Lege deine `.obj`-Dateien (inklusive `.mtl` und `.png`-Texturen) einfach in **`assets/models/`** ab.
- Setze in Roblox Studio an deinem Part das Attribut `ModelName = "Sword"`.
- Der Server lädt automatisch das 3D-Modell, skaliert und rotiert es exakt wie in Roblox!

---

## 6) Token-Sicherheit (Passwortschutz)

Damit fremde Personen deinen Server nicht für Renders ausnutzen können:

1. In der **`.env`** auf dem Server eintragen:
   ```env
   BRS_ACCESS_TOKEN=MeinGeheimesPasswort123
   ```
2. Im Roblox-Server-Skript (`RenderServerService.server.lua`) oben eintragen:
   ```lua
   local RENDER_ACCESS_TOKEN = "MeinGeheimesPasswort123"
   ```
3. Server neu starten (`03_stop.bat`, dann `02_start.bat`).

---

## 7) 7-Tage-Aufbewahrung & Warteschlange

- **Unendliche FIFO-Warteschlange:** Alle eingehenden Aufträge werden der Reihe nach nacheinander abgearbeitet.
- **Speicherung:** Jedes gerenderte Bild wird auf dem Server gespeichert und steht 7 Tage lang für den Download bereit.
- **Automatische Bereinigung:** Nach 7 Tagen werden abgelaufene Aufträge und Bilddateien automatisch gelöscht.

---

## 8) Roblox Open-Cloud-API-Key anlegen

Roblox verlangt für den Download des echten 3D-Avatar-Modells einen API-Key:

1. Öffne: https://create.roblox.com/dashboard/credentials
2. Klicke auf **Create API Key**.
3. Wähle unter **Access Permissions**:
   - System: **`thumbnails`**
   - Operation: **`Read`**
4. Kopiere den Key und trage ihn in der `.env` ein:
   ```env
   ROBLOX_API_KEY=dein_kopierter_key_hier
   ```
5. Server neu starten.
