--==============================================================================
--  BlenderRenderServer – SERVER-SKRIPT (Roblox Studio)
--------------------------------------------------------------------------------
--  WO EINFUEGEN?
--    Im Studio-Explorer:  ServerScriptService  -> Rechtsklick -> Insert Object
--    -> "Script"  -> diesen Text komplett einfuegen (alten Inhalt loeschen)
--
--  VERHALTEN:
--    * Reiner Hintergrund-Dienst: startet den Render beim Spielstart automatisch
--    * Keine Benutzereingaben mehr (kein Button, keine Chat-Befehle)
--    * Schickt Status-Updates an alle Clients und streamt das fertige Bild
--    * Automatisches Reconnect-Handling bei Server-Updates & Neustarts
--==============================================================================

local HttpService       = game:GetService("HttpService")
local AssetService      = game:GetService("AssetService")
local Players           = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

--========================= KONFIGURATION =====================================
local RENDER_SERVER_URL   = "http://localhost:8000"
local RENDER_ACCESS_TOKEN = "" -- Falls BRS_ACCESS_TOKEN in der .env gesetzt ist
local DEFAULT_USERNAME    = "MertaStudios" -- Avatar, der beim Serverstart gerendert wird
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
	local payload = {
		username = username,
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

	-- Bild an alle aktuell verbundenen Clients streamen
	local function getTargets()
		return Players:GetPlayers()
	end

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

		local targets = getTargets()
		if #targets > 0 then
			local y2 = y
			while y2 < y + rowsInBuf do
				local rows2 = math.min(REMOTE_CHUNK_ROWS, y + rowsInBuf - y2)
				local offset = (y2 - y) * width * 4
				local piece = bufferSlice(buf, offset, rows2 * width * 4)
				for _, target in ipairs(targets) do
					remoteImage:FireClient(target, "chunk", jobId, y2, rows2, width, height, piece)
				end
				y2 = y2 + rows2
				task.wait()
			end
		end

		chunkIndex = chunkIndex + 1
		y = y + rowsInBuf
	end

	for _, target in ipairs(getTargets()) do
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

print("==============================================================")
print("[BlenderRender] Server-Skript initialisiert (automatischer Render)!")
print("[BlenderRender] Server-Adresse: " .. RENDER_SERVER_URL)
print("[BlenderRender] Standard-User : " .. DEFAULT_USERNAME)
print("==============================================================")

if AUTO_RENDER then
	task.spawn(runPipeline, DEFAULT_USERNAME)
end
