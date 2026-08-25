--==============================================================================
--  BlenderRenderServer – SERVER-SKRIPT (Roblox Studio)
--------------------------------------------------------------------------------
--  WO EINFUEGEN?
--    Im Studio-Explorer: ServerScriptService -> Rechtsklick -> Insert Object
--    -> "Script" -> diesen Text einfuegen.
--
--  FUNKTIONSWEISE:
--    * Startet NICHT mehr automatisch beim Serverstart.
--    * Erstellt eine BindableFunction namens "manage_render" in ServerStorage.
--    * Aufruf aus beliebigen Server-Skripten ueber:
--
--        local ServerStorage = game:GetService("ServerStorage")
--        local manage_render = ServerStorage:WaitForChild("manage_render")
--
--    * AKTIONEN:
--        1) "Create", FolderImWorkspace
--           -> Rueckgabe: success (bool), jobId_oder_Fehler (string)
--
--        2) "Status", jobId
--           -> Rueckgabe: success (bool), statusTable_oder_Fehler (table/string)
--              statusTable: { state = "queued"|"active"|"done"|"not_found",
--                             queue_position = number,
--                             est_seconds_left = number,
--                             progress = number, message = string }
--
--        3) "Download", jobId
--           -> Rueckgabe: success (bool), imageData_oder_Fehler (table/string)
--              imageData: { width = 1024, height = 1024, size = Vector2, buffer = Buffer }
--==============================================================================

local HttpService    = game:GetService("HttpService")
local ServerStorage  = game:GetService("ServerStorage")

--========================= KONFIGURATION =====================================
local RENDER_SERVER_URL   = "http://localhost:8000" -- Adresse deines Render-Servers
local RENDER_ACCESS_TOKEN = ""                      -- Sicherheits-Passwort (wie BRS_ACCESS_TOKEN in der .env)
local HTTP_CHUNK_ROWS     = 16                      -- Bildzeilen pro HTTP-Paket beim Download
--==============================================================================

--------------------------------------------------------------------------------
-- BindableFunction in ServerStorage anlegen
--------------------------------------------------------------------------------
local manageRender = ServerStorage:FindFirstChild("manage_render")
if not manageRender then
	manageRender = Instance.new("BindableFunction")
	manageRender.Name = "manage_render"
	manageRender.Parent = ServerStorage
end

--------------------------------------------------------------------------------
-- HTTP-Hilfsfunktionen
--------------------------------------------------------------------------------

local function httpRequest(method, path, bodyTable)
	local ok, result = pcall(function()
		local headers = {}
		if RENDER_ACCESS_TOKEN and #RENDER_ACCESS_TOKEN > 0 then
			headers["X-BRS-Token"] = RENDER_ACCESS_TOKEN
		end
		local options = {
			Url = RENDER_SERVER_URL .. path,
			Method = method,
			Headers = headers,
		}
		if bodyTable ~= nil then
			options.Headers["Content-Type"] = "application/json"
			options.Body = HttpService:JSONEncode(bodyTable)
		end
		return HttpService:RequestAsync(options)
	end)
	if not ok then
		return false, 0, tostring(result)
	end
	return result.Success, result.StatusCode, result.Body
end

local function asTable(body)
	if typeof(body) == "table" then return body end
	if typeof(body) ~= "string" then return nil end
	local ok, data = pcall(function()
		return HttpService:JSONDecode(body)
	end)
	if ok then return data end
	return nil
end

local function colorToRgbTable(c)
	if typeof(c) == "Color3" then
		return { math.floor(c.R * 255), math.floor(c.G * 255), math.floor(c.B * 255) }
	end
	return { 245, 205, 170 }
end

--------------------------------------------------------------------------------
-- 1. AKTION: "Create"
--------------------------------------------------------------------------------

local function serializeFolder(folder)
	if not (typeof(folder) == "Instance") then
		return nil, "Uebergebenes Objekt ist keine gueltige Roblox-Instanz (Folder/Model erwartet)."
	end

	local avatars = {}
	local objects = {}

	for _, item in ipairs(folder:GetChildren()) do
		-- Pruefen, ob das Element ein Avatar-Rig ist
		local isRig = item:GetAttribute("IsRig")
		local username = item:GetAttribute("Username")
		local hasHumanoid = item:FindFirstChildOfClass("Humanoid") or item:FindFirstChild("HumanoidRootPart")

		if isRig == true or username or hasHumanoid then
			local finalUsername = username or item.Name
			local matMode = item:GetAttribute("MaterialMode") or "GLAS"
			local glassStrength = item:GetAttribute("GlassStrength") or 0.85
			local heartHands = item:GetAttribute("HeartHands") or item:GetAttribute("SpecialHands") or false
			
			local skinCol = item:GetAttribute("SkinColor")
			if not skinCol then
				local head = item:FindFirstChild("Head") or item:FindFirstChild("LeftHand")
				if head and head:IsA("BasePart") then
					skinCol = colorToRgbTable(head.Color)
				else
					skinCol = { 245, 205, 170 }
				end
			elseif typeof(skinCol) == "Color3" then
				skinCol = colorToRgbTable(skinCol)
			end

			-- Einzelne Koerperteile (R15 / R6) mit CFrames erfassen
			local parts = {}
			for _, part in ipairs(item:GetChildren()) do
				if part:IsA("BasePart") then
					local cf = part.CFrame
					local col = part.Color
					parts[part.Name] = {
						cframe = { cf:GetComponents() },
						position = { cf.Position.X, cf.Position.Y, cf.Position.Z },
						size = { part.Size.X, part.Size.Y, part.Size.Z },
						color = colorToRgbTable(col),
					}
				end
			end

			table.insert(avatars, {
				username = finalUsername,
				material_mode = tostring(matMode):upper(),
				glass_strength = tonumber(glassStrength) or 0.85,
				heart_hands = (heartHands == true),
				skin_color = skinCol,
				parts = parts,
			})

		elseif item:IsA("BasePart") or item:IsA("Model") then
			-- Benutzerdefiniertes 3D-Modell / Part
			local modelName = item:GetAttribute("ModelName") or item:GetAttribute("CustomModel") or item.Name
			local matMode = item:GetAttribute("MaterialMode") or "MATT"
			local glassStrength = item:GetAttribute("GlassStrength") or 0.85
			
			local cf = item:IsA("BasePart") and item.CFrame or (item.PrimaryPart and item.PrimaryPart.CFrame or CFrame.new())
			local size = item:IsA("BasePart") and item.Size or (item:GetExtentsSize())
			local color = item:IsA("BasePart") and colorToRgbTable(item.Color) or { 200, 200, 200 }

			table.insert(objects, {
				model_name = tostring(modelName),
				name = item.Name,
				material_mode = tostring(matMode):upper(),
				glass_strength = tonumber(glassStrength) or 0.85,
				cframe = { cf:GetComponents() },
				size = { size.X, size.Y, size.Z },
				color = color,
			})
		end
	end

	local sceneData = {
		avatars = avatars,
		objects = objects,
		camera = {
			position = { 0, 0, 0 },
			target = { 0, 0, -10 },
			fov = 32.0,
		},
	}

	return sceneData, nil
end

local function handleCreate(folder)
	local sceneData, err = serializeFolder(folder)
	if not sceneData then
		return false, tostring(err)
	end

	if #sceneData.avatars == 0 and #sceneData.objects == 0 then
		return false, "Der Ordner enthaelt weder Avatare noch 3D-Modelle."
	end

	local ok, code, body = httpRequest("POST", "/jobs", sceneData)
	if not ok then
		return false, ("Verbindung zum Render-Server fehlgeschlagen (HTTP %s): %s"):format(tostring(code), tostring(body))
	end

	local data = asTable(body)
	if data and data.job_id then
		return true, data.job_id
	end

	return false, ("Server antwortete ohne gueltige Job-ID (HTTP %s): %s"):format(tostring(code), tostring(body))
end

--------------------------------------------------------------------------------
-- 2. AKTION: "Status"
--------------------------------------------------------------------------------

local function handleStatus(jobId)
	if not jobId or type(jobId) ~= "string" or #jobId == 0 then
		return false, "Ungueltige Auftrag-ID uebergeben."
	end

	local ok, code, body = httpRequest("GET", "/jobs/" .. tostring(jobId))
	if not ok then
		if code == 404 then
			return true, {
				exists = false,
				state = "not_found",
				queue_position = 0,
				est_seconds_left = 0,
				message = "Auftrag existiert nicht (oder ist abgelaufen)",
			}
		end
		return false, ("Verbindung zum Render-Server fehlgeschlagen (HTTP %s)"):format(tostring(code))
	end

	local data = asTable(body)
	if not data then
		return false, "Server-Antwort war kein gueltiges JSON."
	end

	local state = data.state or "unknown"
	local result = {
		exists = (data.exists ~= false),
		job_id = data.job_id or jobId,
		state = state,
		queue_position = tonumber(data.queue_position) or 0,
		est_seconds_left = tonumber(data.est_seconds_left) or 0,
		progress = tonumber(data.progress) or 0,
		message = data.message or state,
		error = data.error,
		width = data.width,
		height = data.height,
	}

	return true, result
end

--------------------------------------------------------------------------------
-- 3. AKTION: "Download"
--------------------------------------------------------------------------------

local function handleDownload(jobId)
	if not jobId or type(jobId) ~= "string" or #jobId == 0 then
		return false, "Ungueltige Auftrag-ID uebergeben."
	end

	-- 1. Bild-Dimensionen abfragen
	local okInfo, codeInfo, bodyInfo = httpRequest("GET", ("/jobs/%s/image/info"):format(jobId))
	if not okInfo then
		return false, ("Bildinformationen nicht abrufbar (HTTP %s)"):format(tostring(codeInfo))
	end

	local info = asTable(bodyInfo)
	if not (info and info.width and info.height) then
		return false, "Bild ist noch nicht fertig gerendert oder nicht vorhanden."
	end

	local width = tonumber(info.width) or 1024
	local height = tonumber(info.height) or 1024
	local totalBytes = width * height * 4
	local fullBuffer = buffer.create(totalBytes)

	-- 2. Pixelzeilen paketweise herunterladen (sicher gegen HTTP-Grenzen)
	local y = 0
	while y < height do
		local rowsToFetch = math.min(HTTP_CHUNK_ROWS, height - y)
		local okRow, codeRow, bodyRow = httpRequest("GET",
			("/jobs/%s/image/rows?y=%d&rows=%d"):format(jobId, y, rowsToFetch))

		if not (okRow and codeRow == 200) then
			return false, ("Fehler beim Herunterladen von Zeile %d (HTTP %s)"):format(y, tostring(codeRow))
		end

		local chunkBuf = buffer.fromstring(bodyRow)
		local chunkLen = buffer.len(chunkBuf)
		if chunkLen <= 0 then break end

		local offset = y * width * 4
		local copyBytes = math.min(chunkLen, totalBytes - offset)
		buffer.copy(fullBuffer, offset, chunkBuf, 0, copyBytes)

		local rowsReceived = math.floor(chunkLen / (width * 4))
		if rowsReceived <= 0 then rowsReceived = rowsToFetch end
		y = y + rowsReceived
	end

	return true, {
		width = width,
		height = height,
		size = Vector2.new(width, height),
		buffer = fullBuffer,
	}
end

--------------------------------------------------------------------------------
-- BindableFunction Handler
--------------------------------------------------------------------------------

manageRender.OnInvoke = function(action, ...)
	local actionStr = tostring(action or ""):lower()

	if actionStr == "create" then
		local folder = ...
		return handleCreate(folder)

	elseif actionStr == "status" then
		local jobId = ...
		return handleStatus(jobId)

	elseif actionStr == "download" then
		local jobId = ...
		return handleDownload(jobId)

	else
		return false, ("Unbekannte Aktion '%s'. Gueltig: 'Create', 'Status', 'Download'"):format(tostring(action))
	end
end

print("==============================================================")
print("[BlenderRender] manage_render BindableFunction in ServerStorage bereit!")
print("[BlenderRender] Server-Adresse: " .. RENDER_SERVER_URL)
if #RENDER_ACCESS_TOKEN > 0 then
	print("[BlenderRender] Authentifizierung: TOKEN AKTIV")
else
	print("[BlenderRender] Authentifizierung: Kein Token (offen)")
end
print("==============================================================")
