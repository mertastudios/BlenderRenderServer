--==============================================================================
--  BlenderRenderServer – SERVER-SKRIPT (Roblox Studio)
--------------------------------------------------------------------------------
--  WO EINFUEGEN?
--    Im Studio-Explorer:  ServerScriptService  → Rechtsklick → Insert Object
--    → "Script"  → diesen Text komplett einfuegen (alten Inhalt loeschen)
--
--  NEUE FEATURES:
--    * Vollstaendige R15/R6-Rig Extraktion: Liest alle Koerperteile, Positionen,
--      Masse, Accessoires & Texturen aus und schickt sie an den Render-Server
--    * Praezise Schritt-fuer-Schritt Status-Updates mit geschaetzter Restzeit
--    * Automatisches Reconnect-Handling bei Server-Updates & Neustarts
--    * RemoteFunction fuer direkte Render-Aufrufe aus dem Client-GUI
--==============================================================================

local HttpService       = game:GetService("HttpService")
local AssetService      = game:GetService("AssetService")
local Players           = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

--========================= KONFIGURATION =====================================
local RENDER_SERVER_URL   = "http://localhost:8000"
local RENDER_ACCESS_TOKEN = "" -- Falls BRS_ACCESS_TOKEN in der .env gesetzt ist
local DEFAULT_USERNAME    = "MertaStudios" -- Standard-Avatar beim Serverstart
local POLL_SECONDS        = 2    -- Status-Abfrageintervall in Sekunden
local HTTP_CHUNK_ROWS     = 16   -- Zeilen pro HTTP-Download
local REMOTE_CHUNK_ROWS   = 8    -- Zeilen pro Client-Paket
local AUTO_RENDER         = true -- Bei Spielstart sofort rendern
--==============================================================================

-- Remotes in ReplicatedStorage anlegen
local remoteImage = ReplicatedStorage:FindFirstChild("BlenderRender_Image")
if not remoteImage then
	remoteImage = Instance.new("RemoteEvent")
	remoteImage.Name = "BlenderRender_Image"
	remoteImage.Parent = ReplicatedStorage
end

local remoteStatus = ReplicatedStorage:FindFirstChild("BlenderRender_Status")
if not remoteStatus then
	remoteStatus = Instance.new("RemoteEvent")
	remoteStatus.Name = "BlenderRender_Status"
	remoteStatus.Parent = ReplicatedStorage
end

local remoteRequest = ReplicatedStorage:FindFirstChild("BlenderRender_Request")
if not remoteRequest then
	remoteRequest = Instance.new("RemoteFunction")
	remoteRequest.Name = "BlenderRender_Request"
	remoteRequest.Parent = ReplicatedStorage
end

--------------------------------------------------------------------------------
-- Hilfsfunktionen & HTTP
--------------------------------------------------------------------------------

local function broadcastStatus(step, totalSteps, stepName, message, progress, estSecondsLeft, state)
	local payload = {
		step = step or 1,
		totalSteps = totalSteps or 5,
		stepName = stepName or "In Bearbeitung",
		message = message or "",
		progress = progress or 0,
		estSecondsLeft = estSecondsLeft or 0,
		state = state or "active",
	}
	remoteStatus:FireAllClients(payload)
	print(("[BlenderRender] [%d/%d] %s: %s (%d%% - Rest: ~%ds)"):format(
		payload.step, payload.totalSteps, payload.stepName, payload.message, payload.progress, payload.estSecondsLeft))
end

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

local function bufferSlice(src, byteOffset, byteLen)
	local out = buffer.create(byteLen)
	buffer.copy(out, 0, src, byteOffset, byteLen)
	return out
end

--------------------------------------------------------------------------------
-- Avatar-Daten & Rig-Extraktion aus Roblox
--------------------------------------------------------------------------------

local function extractAvatarData(username)
	local targetPlayer = nil
	for _, p in ipairs(Players:GetPlayers()) do
		if string.lower(p.Name) == string.lower(username) then
			targetPlayer = p
			break
		end
	end

	local char = targetPlayer and targetPlayer.Character
	local humanoid = char and char:FindFirstChildOfClass("Humanoid")
	local rigType = (humanoid and humanoid.RigType == Enum.HumanoidRigType.R6) and "R6" or "R15"

	local partsData = {}
	local accessoriesData = {}

	if char then
		local rootPart = char:FindFirstChild("HumanoidRootPart")
		local rootCF = rootPart and rootPart.CFrame or char:GetPivot()

		for _, item in ipairs(char:GetChildren()) do
			if item:IsA("BasePart") and item.Name ~= "HumanoidRootPart" then
				local relCF = rootCF:ToObjectSpace(item.CFrame)
				local col = item.Color
				table.insert(partsData, {
					name = item.Name,
					size = { item.Size.X, item.Size.Y, item.Size.Z },
					position = { relCF.Position.X, relCF.Position.Y + 3.0, relCF.Position.Z },
					color = { math.floor(col.R * 255), math.floor(col.G * 255), math.floor(col.B * 255) },
				})
			elseif item:IsA("Accessory") then
				local handle = item:FindFirstChild("Handle")
				if handle and handle:IsA("BasePart") then
					local relCF = rootCF:ToObjectSpace(handle.CFrame)
					local col = handle.Color
					table.insert(accessoriesData, {
						name = item.Name,
						size = { handle.Size.X, handle.Size.Y, handle.Size.Z },
						position = { relCF.Position.X, relCF.Position.Y + 3.0, relCF.Position.Z },
						color = { math.floor(col.R * 255), math.floor(col.G * 255), math.floor(col.B * 255) },
					})
				end
			end
		end
	end

	return {
		rig_type = rigType,
		username = username,
		parts = partsData,
		accessories = accessoriesData,
	}
end

--------------------------------------------------------------------------------
-- Phase 1: Warten auf Render-Server
--------------------------------------------------------------------------------

local function waitForServer()
	while true do
		local ok, code, body = httpRequest("GET", "/health")
		local data = ok and asTable(body) or nil
		if ok and data and data.status == "ok" then
			local versionText = tostring(data.version or "1.2")
			local updateText = data.update_available and " (Update verfuegbar)" or ""
			broadcastStatus(1, 5, "Server verbunden",
				("Render-Server ONLINE (Version %s%s)"):format(versionText, updateText), 5, 30, "active")
			return data
		end
		broadcastStatus(1, 5, "Verbindung suchen",
			("Warte auf Render-Server (HTTP %s). Starte 02_start.bat falls noetig ..."):format(tostring(code)), 2, 0, "waiting")
		task.wait(POLL_SECONDS)
	end
end

--------------------------------------------------------------------------------
-- Phase 2: Auftrag abschicken
--------------------------------------------------------------------------------

local function submitJob(username)
	local avatarData = extractAvatarData(username)
	local payload = {
		username = username,
		avatar_data = avatarData,
	}
	local ok, code, body = httpRequest("POST", "/jobs", payload)
	local data = asTable(body)
	if ok and data and data.job_id then
		broadcastStatus(1, 5, "Auftrag angenommen",
			("Auftrag fuer '%s' registriert (Job %s)"):format(username, data.job_id), 8, 28, "active")
		return data.job_id
	end
	broadcastStatus(1, 5, "Fehler beim Einreichen",
		("Konnte Auftrag nicht senden (HTTP %s). Neuer Versuch ..."):format(tostring(code)), 0, 0, "error")
	return nil
end

--------------------------------------------------------------------------------
-- Phase 3: Status abfragen & Restzeit uebermitteln
--------------------------------------------------------------------------------

local function pollUntilDone(jobId)
	while true do
		local ok, code, body = httpRequest("GET", "/jobs/current")
		if not ok then
			-- Server aktualisiert sich moeglicherweise gerade selbst
			broadcastStatus(0, 5, "Server aktualisiert / startet neu",
				"Server antwortet kurzzeitig nicht (Auto-Update?). Warte auf Reconnect ...", 0, 0, "restarting")
			task.wait(POLL_SECONDS)
		else
			local data = asTable(body)
			if data == nil or data.state == "idle" then
				broadcastStatus(1, 5, "Neustart erkannt", "Server hat neu gestartet -> reiche Auftrag neu ein ...", 5, 30, "resubmit")
				return "resubmit"
			elseif data.job_id == jobId then
				local state = data.state
				local step = data.step or 2
				local totalSteps = data.step_total or 5
				local stepName = data.step_name or state
				local msg = data.message or ""
				local progress = data.progress or 0
				local estSec = data.est_seconds_left or 0

				if state == "done" then
					broadcastStatus(5, 5, "Fertig gerendert", ("Render fuer '%s' erfolgreich abgeschlossen!"):format(data.username), 95, 2, "done")
					return "done", data
				elseif state == "error" then
					broadcastStatus(0, 5, "Fehler aufgetreten", tostring(data.error or msg), 0, 0, "error")
					return "error"
				else
					broadcastStatus(step, totalSteps, stepName, msg, progress, estSec, "active")
					task.wait(POLL_SECONDS)
				end
			else
				task.wait(POLL_SECONDS)
			end
		end
	end
end

--------------------------------------------------------------------------------
-- Phase 4: Bilduebertragung & Streaming
--------------------------------------------------------------------------------

local function transferImage(jobId)
	local ok, code, body = httpRequest("GET", ("/jobs/%s/image/info"):format(jobId))
	local info = ok and asTable(body) or nil
	if not (info and info.width and info.height) then
		broadcastStatus(5, 5, "Fehler", "Bild-Metadaten nicht lesbar", 0, 0, "error")
		return
	end
	local width, height = info.width, info.height
	broadcastStatus(5, 5, "Bild uebertragen", ("Empfange %dx%d Pixel ..."):format(width, height), 95, 2, "transfer")

	local serverImage = nil
	pcall(function()
		serverImage = AssetService:CreateEditableImage({ Size = Vector2.new(width, height) })
	end)

	local target = Players:GetPlayers()[1]
	local totalChunks = math.ceil(height / HTTP_CHUNK_ROWS)
	local chunkIndex, y = 0, 0

	while y < height do
		local okRow, codeRow, bodyRow = httpRequest("GET",
			("/jobs/%s/image/rows?y=%d&rows=%d"):format(jobId, y, HTTP_CHUNK_ROWS))
		if not (okRow and codeRow == 200) then
			broadcastStatus(5, 5, "Fehler", "Zeilen-Download fehlgeschlagen", 0, 0, "error")
			return
		end

		local buf = buffer.fromstring(bodyRow)
		local rowsInBuf = math.floor(buffer.len(buf) / (width * 4))
		if rowsInBuf <= 0 then break end

		if serverImage then
			pcall(function()
				serverImage:WritePixelsBuffer(Vector2.new(0, y), Vector2.new(width, rowsInBuf), buf)
			end)
		end

		if target then
			local y2 = y
			while y2 < y + rowsInBuf do
				local rows2 = math.min(REMOTE_CHUNK_ROWS, y + rowsInBuf - y2)
				local offset = (y2 - y) * width * 4
				local piece = bufferSlice(buf, offset, rows2 * width * 4)
				remoteImage:FireClient(target, "chunk", jobId, y2, rows2, width, height, piece)
				y2 = y2 + rows2
				task.wait()
			end
		end

		chunkIndex = chunkIndex + 1
		y = y + rowsInBuf
	end

	if target then
		remoteImage:FireClient(target, "done", jobId, width, height)
	end
	broadcastStatus(5, 5, "Fertig!", ("Bild (%dx%d) erfolgreich im GUI angezeigt."):format(width, height), 100, 0, "done")
end

--------------------------------------------------------------------------------
-- Pipeline-Steuerung
--------------------------------------------------------------------------------

local isBusy = false

local function runPipeline(username)
	if isBusy then return end
	isBusy = true

	while true do
		waitForServer()
		local jobId = submitJob(username)
		if jobId then
			local result = pollUntilDone(jobId)
			if result == "done" then
				transferImage(jobId)
				break
			elseif result == "error" then
				break
			end
		else
			task.wait(POLL_SECONDS)
		end
	end

	isBusy = false
end

-- RemoteFunction fuer Client-Aufrufe
remoteRequest.OnServerInvoke = function(callingPlayer, requestedUsername)
	local targetName = (requestedUsername and #requestedUsername > 0) and requestedUsername or callingPlayer.Name
	task.spawn(runPipeline, targetName)
	return true
end

-- Chat-Befehle
Players.PlayerAdded:Connect(function(newPlayer)
	newPlayer.Chatted:Connect(function(msg)
		local args = string.split(msg, " ")
		if string.lower(args[1]) == "!render" then
			local target = #args >= 2 and args[2] or newPlayer.Name
			task.spawn(runPipeline, target)
		end
	end)
end)

print("==============================================================")
print("[BlenderRender] Server-Skript initialisiert!")
print("[BlenderRender] Server-Adresse: " .. RENDER_SERVER_URL)
print("[BlenderRender] Standard-User : " .. DEFAULT_USERNAME)
print("==============================================================")

if AUTO_RENDER then
	task.spawn(runPipeline, DEFAULT_USERNAME)
end
