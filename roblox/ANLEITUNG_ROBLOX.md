# 🎮 Anleitung: Roblox-Studio-Einrichtung (`manage_render`)

Diese Anleitung erklärt, wie du den BlenderRenderServer über die **`manage_render` BindableFunction** in Roblox Studio steuerst.

---

## Schritt 1: HTTP-Anfragen in Roblox Studio erlauben

1. In Roblox Studio oben im Menü: **Home** → **Game Settings** (Spieleinstellungen).
2. Links: **Security** (Sicherheit).
3. **„Allow HTTP Requests“** auf **ON** schalten und mit **Save** speichern.

---

## Schritt 2: Server-Skript einfügen

1. Öffne den **Explorer** in Roblox Studio.
2. Gehe zu **ServerScriptService** → Rechtsklick → **Insert Object** → **Script**.
3. Ersetze den Inhalt durch den Code aus `roblox/RenderServerService.server.lua`.
4. Passe oben im Skript deine Einstellungen an:
   ```lua
   local RENDER_SERVER_URL   = "http://localhost:8000" -- Adresse des Render-Servers
   local RENDER_ACCESS_TOKEN = ""                      -- Passwort (falls BRS_ACCESS_TOKEN in .env)
   ```

---

## Schritt 3: Render-Aufträge ausführen (`manage_render`)

Das Skript legt beim Start automatisch eine `BindableFunction` in `ServerStorage` namens **`manage_render`** an. Du kannst sie aus jedem beliebigen Server-Skript aufrufen:

### 🚀 Beispiel-Skript:
Erstelle ein neues Script im `ServerScriptService` (z. B. `RenderController`):

```lua
local ServerStorage = game:GetService("ServerStorage")
local AssetService = game:GetService("AssetService")
local manage_render = ServerStorage:WaitForChild("manage_render")

-- 1. AUFTRAG ERSTELLEN
-- Erstelle einen Ordner "RenderScene" im Workspace und lege dein R15-Rig oder 3D-Parts hinein
local folder = workspace:FindFirstChild("RenderScene") or workspace
local success, result = manage_render:Invoke("Create", folder)

if not success then
    warn("Fehler beim Erstellen des Auftrags:", result)
    return
end

local jobId = result
print("✅ Auftrag erstellt! Job-ID:", jobId)

-- 2. STATUS ABFRAGEN (in einer Schleife warten)
while true do
    task.wait(2)
    local ok, status = manage_render:Invoke("Status", jobId)
    if ok then
        print(("[Status] %s | Restzeit: ~%d s | Position: %d"):format(
            status.message, status.est_seconds_left, status.queue_position))
        
        if status.state == "done" then
            print("🎉 Render ist fertig!")
            break
        elseif status.state == "error" or status.state == "not_found" then
            warn("Render fehlgeschlagen:", status.error or status.message)
            return
        end
    end
end

-- 3. BILD HERUNTERLADEN
local dlOk, imgData = manage_render:Invoke("Download", jobId)
if dlOk then
    print("✅ Bild empfangen:", imgData.width, "x", imgData.height)
    
    -- In ein EditableImage schreiben:
    local editableImage = AssetService:CreateEditableImage({ Size = imgData.size })
    editableImage:WritePixelsBuffer(Vector2.zero, imgData.size, imgData.buffer)
    print("🖼️ Bild erfolgreich in EditableImage geladen!")
else
    warn("Download-Fehler:", imgData)
end
```

---

## 🏷️ Attribute-Übersicht für deine Modelle

### R15 / R6 Rig-Attribute (auf dem Model):
- **`Username`** (`string`): Roblox-Name des Avatars (z. B. `"MertaStudios"`).
- **`IsRig`** (`boolean`): `true`.
- **`MaterialMode`** (`string`): `"MATT"`, `"GLAS"` oder `"DURCHSICHTIGES_GLAS"`.
- **`GlassStrength`** (`number`): `0.0` bis `1.0` (z. B. `0.85`).
- **`HeartHands`** (`boolean`): `true` (ersetzt Hände durch das Herzform-3D-Modell).
- **`SkinColor`** (`Color3`): Hautfarbe für Herz-Hände.

### Custom 3D-Modelle / Parts (auf dem Part/MeshPart):
- **`ModelName`** (`string`): Name der OBJ-Datei in `assets/models/` (z. B. `"Sword"` für `Sword.obj`).
- **`MaterialMode`** (`string`): `"MATT"`, `"GLAS"` oder `"DURCHSICHTIGES_GLAS"`.
- **`GlassStrength`** (`number`): `0.0` bis `1.0`.
