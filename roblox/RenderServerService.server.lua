--==============================================================================
--  BlenderRenderServer – SERVER-SKRIPT (Roblox Studio)
--------------------------------------------------------------------------------
--  WO EINFUEGEN?
--    Im Studio-Explorer:  ServerScriptService  → Rechtsklick → Insert Object
--    → "Script"  → diesen kompletten Text hier einfuegen (alten Inhalt loeschen)
--
--  WAS MACHT ES?
--    * Fragt beim Start den Render-Server auf deinem PC ab
--    * Schickt den Auftrag: "Rendere den Avatar von ROBLOX_USERNAME in Glas"
--    * Printet REGELMAESSIG den Status in die Konsole ("Output"-Fenster):
--        SERVER DOWN / AUFTRAG IN DER WARTESCHLANGE / WIRD GERENDERT ...
--    * Holt das fertige Bild STUECK FUER STUECK als Pixel-Rohdaten ab und
--      schreibt es in ein serverseitiges EditableImage
--    * Leitet dieselben Pixel-Pakete per RemoteEvent an den Client weiter
--      (der zeigt das Bild dann in einem GUI an)
--
--  WICHTIG (einmalig pro Projekt einschalten!):
--    Home → Game Settings → Security → "Allow HTTP Requests" = ON
--    (Ohne das darf Roblox nicht mit deinem PC reden.)
--
--  VEROEFFENTLICHEN:
--    localhost geht NUR in Studio auf demselben PC.
--    Fuer den echten Roblox-Client: 08_oeffentliche_adresse.bat
--    und die https-URL unten bei RENDER_SERVER_URL eintragen.
--
--  ZUSAETZLICH MOEGLICH (im Chat, nur zum Testen):
--    !render              → startet den Avatar-Render erneut
--    !render Benutzername → rendert einen anderen Avatar
--==============================================================================

local HttpService    = game:GetService("HttpService")
local AssetService   = game:GetService("AssetService")
local Players        = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService     = game:GetService("RunService")

--========================= KONFIGURATION =====================================
-- STUDIO auf demselben PC wie der Render-Server:
--   local RENDER_SERVER_URL = "http://localhost:8000"
--
-- VEROEFFENTLICHTES Spiel (Roblox-Client, nicht Studio):
--   localhost funktioniert NICHT! Die Anfrage kommt von Roblox-Cloud-Servern.
--   1. Auf dem PC 02_start.bat UND 08_oeffentliche_adresse.bat starten
--   2. Die https://....trycloudflare.com Adresse HIER eintragen
--   3. Im Live-Spiel braucht Roblox HTTPS (nicht http://)
--   4. Dein PC muss an sein, solange jemand spielt
local RENDER_SERVER_URL = "http://localhost:8000"

-- Nur noetig, wenn in der .env BRS_ACCESS_TOKEN gesetzt ist (empfohlen
-- sobald die Adresse oeffentlich ist). Muss EXAKT derselbe Wert sein.
local RENDER_ACCESS_TOKEN = ""

-- Der Roblox-Benutzername, dessen Avatar beim Serverstart gerendert wird:
local ROBLOX_USERNAME = "Builderman" -- <<< HIER DEINEN NAMEN EINTRAGEN!

local POLL_SECONDS      = 3   -- Status alle 3 Sekunden abfragen
local HTTP_CHUNK_ROWS   = 16  -- Zeilen pro Download vom Render-Server
local REMOTE_CHUNK_ROWS = 8   -- Zeilen pro Paket an den Client (klein = stabil)
local AUTO_RENDER       = true -- Bei Serverstart automatisch loslegen
--==============================================================================

-- RemoteEvent fuer die Client-Kommunikation bereitstellen
local remote = ReplicatedStorage:FindFirstChild("BlenderRender_Image")
if not remote then
	remote = Instance.new("RemoteEvent")
	remote.Name = "BlenderRender_Image"
	remote.Parent = ReplicatedStorage
end

--------------------------------------------------------------------------------
-- Hilfsfunktionen
--------------------------------------------------------------------------------

local lastStatusText = nil
local function statusPrint(icon, text, immerAusgeben)
	-- Printet nur bei Aenderung (oder wenn zwangsweise gefordert),
	-- damit die Konsole nicht mit 1000 identischen Zeilen zumuellt wird.
	if immerAusgeben or text ~= lastStatusText then
		lastStatusText = text
		print(("[BlenderRender] %s %s"):format(icon, text))
	end
	remote:FireAllClients("status", text) -- Status auch im Client-GUI zeigen
end

-- HTTP-Anfrage an den Render-Server. Liefert: erfolg, statuscode, body
local function httpRequest(method, path, bodyTable)
	local ok, result = pcall(function()
		local options = {
			Url = RENDER_SERVER_URL .. path,
			Method = method,
			Headers = {},
		}
		if RENDER_ACCESS_TOKEN ~= "" then
			options.Headers["X-BRS-Token"] = RENDER_ACCESS_TOKEN
		end
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

-- JSON-Antwort in eine Lua-Tabelle umwandeln (RequestAsync decodiert JSON
-- teilweise schon selbst - beides wird hier abgedeckt)
local function asTable(body)
	if typeof(body) == "table" then return body end
	if typeof(body) ~= "string" then return nil end
	local ok, data = pcall(function()
		return HttpService:JSONDecode(body)
	end)
	if ok then return data end
	return nil
end

-- Teilpuffer aus einem groesseren Puffer ausschneiden
local function bufferSlice(src, byteOffset, byteLen)
	local out = buffer.create(byteLen)
	buffer.copy(out, 0, src, byteOffset, byteLen)
	return out
end

--------------------------------------------------------------------------------
-- Phase 1: Warten, bis der Render-Server erreichbar ist
--------------------------------------------------------------------------------

local function waitForServer()
	while true do
		local ok, code, body = httpRequest("GET", "/health")
		local data = ok and asTable(body) or nil
		if ok and data and data.status == "ok" then
			statusPrint("🟢", ("Render-Server ONLINE (Version %s, Blender: %s)")
				:format(tostring(data.version), data.blender and "bereit" or "FEHLT"), true)
			return data
		end
		statusPrint("🔴", ("SERVER DOWN - keine Verbindung zu %s (HTTP %s). "
			.. "Ist 02_start.bat gestartet? Neuer Versuch in %d s ...")
			:format(RENDER_SERVER_URL, tostring(code), POLL_SECONDS), true)
		task.wait(POLL_SECONDS)
	end
end

--------------------------------------------------------------------------------
-- Phase 2: Auftrag an den Render-Server schicken
--------------------------------------------------------------------------------

local function submitJob(username)
	local ok, code, body = httpRequest("POST", "/jobs", { username = username })
	local data = asTable(body)
	if ok and data and data.job_id then
		if data.state == "queued" then
			statusPrint("🟡", ("AUFTRAG IN DER WARTESCHLANGE (job %s) - es wird immer "
				.. "nur EIN Auftrag gleichzeitig gearbeitet!"):format(data.job_id), true)
		else
			statusPrint("📤", ("Auftrag angenommen: Avatar von '%s' (job %s)")
				:format(username, data.job_id), true)
		end
		return data.job_id
	end
	if tonumber(code) == 401 then
		statusPrint("🟠", "Zugangstoken abgelehnt (HTTP 401). RENDER_ACCESS_TOKEN im Skript muss "
			.. "genau BRS_ACCESS_TOKEN aus der .env sein.", true)
	else
		statusPrint("🟠", ("Auftrag konnte nicht gesendet werden (HTTP %s) - neuer Versuch in %d s ...")
			:format(tostring(code), POLL_SECONDS), true)
	end
	return nil
end

--------------------------------------------------------------------------------
-- Phase 3: Status abfragen, bis der Auftrag fertig (oder fehlerhaft) ist
--------------------------------------------------------------------------------

local STATE_TEXTS = {
	queued      = "Auftrag in der WARTESCHLANGE (nur einer gleichzeitig)",
	downloading = "Avatar wird von Roblox heruntergeladen (3D-Modell inkl. Texturen) ...",
	loading     = "3D-Modell wird in Blender geladen, Glas-Material wird erstellt ...",
	rendering   = "Blender Cycles RENDERT den Avatar",
	encoding    = "Bild wird fuer die Uebertragung vorbereitet ...",
}

local function pollUntilDone(jobId)
	while true do
		local ok, code, body = httpRequest("GET", "/jobs/current")
		if not ok then
			statusPrint("🔴", ("SERVER DOWN - Verbindung verloren (HTTP %s). "
				.. "Neuer Versuch in %d s ..."):format(tostring(code), POLL_SECONDS), true)
			task.wait(POLL_SECONDS)
		else
			local data = asTable(body)
			if data == nil then
				statusPrint("🟠", "Antwort des Servers nicht lesbar - versuche weiter ...")
				task.wait(POLL_SECONDS)
			elseif data.state == "idle" then
				statusPrint("🟠", "Auftrag ist auf dem Server verschwunden (Neustart?) - "
					.. "reiche einen neuen Auftrag ein ...", true)
				return "resubmit"
			elseif data.job_id == jobId then
				local state = data.state
				if state == "done" then
					statusPrint("✅", ("Render abgeschlossen! ('%s')"):format(tostring(data.username)), true)
					return "done", data
				elseif state == "error" then
					statusPrint("❌", ("FEHLER beim Rendern: %s")
						:format(tostring(data.error or data.message)), true)
					return "error"
				else
					local text = STATE_TEXTS[state] or ("Status: " .. tostring(state))
					if state == "rendering" then
						text = ("%s ... %d %%"):format(text, tonumber(data.progress) or 0)
					end
					statusPrint("⏳", text)
					task.wait(POLL_SECONDS)
				end
			else
				-- Gerade laeuft ein ANDERER Auftrag
				local meQueued = false
				for _, q in ipairs(data.queued or {}) do
					if q.job_id == jobId then meQueued = true end
				end
				if meQueued then
					statusPrint("🟡", ("AUFTRAG IN DER WARTESCHLANGE - aktuell wird noch '%s' "
						.. "bearbeitet (%s). Nur ein Auftrag gleichzeitig!")
						:format(tostring(data.username), tostring(data.state)), true)
				else
					statusPrint("👀", ("Anderer Auftrag aktiv: '%s' (%s)")
						:format(tostring(data.username), tostring(data.state)))
				end
				task.wait(POLL_SECONDS)
			end
		end
	end
end

--------------------------------------------------------------------------------
-- Phase 4: Fertiges Bild stueckweise holen, in ein EditableImage schreiben
--          und an den Client weiterleiten
--------------------------------------------------------------------------------

local function transferImage(jobId)
	local ok, code, body = httpRequest("GET", ("/jobs/%s/image/info"):format(jobId))
	local info = ok and asTable(body) or nil
	if not (info and info.width and info.height) then
		statusPrint("❌", ("Bild-Infos konnten nicht geladen werden (HTTP %s)"):format(tostring(code)), true)
		return
	end
	local width, height = info.width, info.height
	statusPrint("📦", ("Bild ist fertig: %dx%d Pixel - uebertrage es stueckweise ...")
		:format(width, height), true)

	-- Serverseitiges EditableImage ("Editable Image Daten" hier in Roblox)
	local serverImage
	local okCreate, errCreate = pcall(function()
		serverImage = AssetService:CreateEditableImage({ Size = Vector2.new(width, height) })
	end)
	if okCreate and serverImage then
		-- WICHTIG: EditableImage ist KEINE Instance - .Name/.Parent existieren
		-- dort nicht und wuerden die Uebertragung mit einem Fehler abbrechen!
		statusPrint("🖼️", ("Server-EditableImage erstellt (%dx%d)"):format(width, height), true)
	else
		statusPrint("🟠", "Hinweis: Server-EditableImage nicht moeglich (" .. tostring(errCreate)
			.. ") - Uebertragung zum Client laeuft trotzdem.", true)
	end

	-- Der (einzige) Spieler bekommt die Pakete
	local target = Players:GetPlayers()[1]
	if not target then
		statusPrint("🟠", "Kein Spieler im Server - Bild wird nur serverseitig gespeichert.", true)
	end

	local totalChunks = math.ceil(height / HTTP_CHUNK_ROWS)
	local chunkIndex, y = 0, 0
	while y < height do
		local okRow, codeRow, bodyRow = httpRequest("GET",
			("/jobs/%s/image/rows?y=%d&rows=%d"):format(jobId, y, HTTP_CHUNK_ROWS))
		if not (okRow and codeRow == 200) then
			statusPrint("🔴", ("Bild-Daten (Zeile %d) fehlgeschlagen - HTTP %s"):format(y, tostring(codeRow)), true)
			return
		end
		local buf = buffer.fromstring(bodyRow)
		local rowsInBuf = math.floor(buffer.len(buf) / (width * 4))
		if rowsInBuf <= 0 then
			statusPrint("🔴", "Bild-Paket war leer - Abbruch.", true)
			return
		end
		-- 1) In das serverseitige EditableImage schreiben
		if serverImage then
			pcall(function()
				serverImage:WritePixelsBuffer(Vector2.new(0, y), Vector2.new(width, rowsInBuf), buf)
			end)
		end
		-- 2) An den Client in kleineren Paketen weiterleiten
		if target then
			local y2 = y
			while y2 < y + rowsInBuf do
				local rows2 = math.min(REMOTE_CHUNK_ROWS, y + rowsInBuf - y2)
				local offset = (y2 - y) * width * 4
				local piece = bufferSlice(buf, offset, rows2 * width * 4)
				remote:FireClient(target, "chunk", jobId, y2, rows2, width, height, piece)
							y2 = y2 + rows2
				task.wait() -- kleines Tempo, damit nichts verlorengeht
			end
		end
			chunkIndex = chunkIndex + 1
			y = y + rowsInBuf
		if chunkIndex % 8 == 0 or y >= height then
			statusPrint("📡", ("Bild-Uebertragung: %d / %d Pakete (%d %% der Zeilen)")
				:format(chunkIndex, totalChunks, math.floor(y / height * 100)))
		end
	end

	if target then
		remote:FireClient(target, "done", jobId, width, height)
	end
	statusPrint("🎉", ("FERTIG! Bild (%dx%d) komplett - es sollte im Client-GUI sichtbar sein.")
		:format(width, height), true)
end

--------------------------------------------------------------------------------
-- Die Gesamt-Pipeline
--------------------------------------------------------------------------------

local pipelineRunning = false

local function runPipeline(username)
	if pipelineRunning then
		statusPrint("🟠", "Es laeuft bereits eine Render-Pipeline - bitte warten.", true)
		return
	end
	pipelineRunning = true

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
			-- "resubmit": Server hatte neu gestartet -> Schleife laeuft weiter
		else
			task.wait(POLL_SECONDS)
		end
	end
	pipelineRunning = false

	-- Danach: Server dauerhaft beobachten und weiter in die Konsole printen
	while true do
		local ok, code, body = httpRequest("GET", "/jobs/current")
		if not ok then
			statusPrint("🔴", ("SERVER DOWN - keine Verbindung (HTTP %s). "
				.. "Pruefe, ob 02_start.bat laeuft."):format(tostring(code)), true)
		else
			local data = asTable(body) or {}
			if data.state == "idle" then
				statusPrint("🟢", "Server online - gerade passiert nichts (idle).")
			elseif data.state == "done" then
				statusPrint("🟢", ("Server online - letzter Auftrag fertig ('%s').")
					:format(tostring(data.username)))
			elseif data.state == "error" then
				statusPrint("🟠", ("Server online - letzter Auftrag hatte einen Fehler: %s")
					:format(tostring(data.error or data.message)))
			else
				local text = STATE_TEXTS[data.state] or tostring(data.state)
				statusPrint("👀", ("Server arbeitet gerade: '%s' - %s")
					:format(tostring(data.username), text))
			end
		end
		task.wait(POLL_SECONDS)
	end
end

--------------------------------------------------------------------------------
-- Start + optionale Chat-Befehle
--------------------------------------------------------------------------------

print("==============================================================")
print("[BlenderRender] Server-Skript geladen!")
print("[BlenderRender] Render-Server : " .. RENDER_SERVER_URL)
print("[BlenderRender] Avatar-User   : " .. ROBLOX_USERNAME)
print("[BlenderRender] Tipp: Allow HTTP Requests muss in den")
print("[BlenderRender] Game Settings aktiviert sein (Security).")
print("[BlenderRender] Im Chat geht: !render  oder  !render AndererName")
print("==============================================================")

do
	local url = string.lower(RENDER_SERVER_URL)
	local isLocal = string.find(url, "localhost", 1, true) or string.find(url, "127.0.0.1", 1, true)
	if not RunService:IsStudio() and isLocal then
		warn("[BlenderRender] FEHLER: localhost funktioniert NICHT im veroeffentlichten Spiel!")
		warn("[BlenderRender] Die Anfrage kommt von Roblox-Servern, nicht von deinem PC.")
		warn("[BlenderRender] Loesung: 08_oeffentliche_adresse.bat starten und die https://... URL hier bei RENDER_SERVER_URL eintragen.")
	elseif not RunService:IsStudio() and string.sub(url, 1, 8) ~= "https://" then
		warn("[BlenderRender] Hinweis: Im veroeffentlichten Spiel braucht Roblox HTTPS (nicht http://).")
	end
end

if ROBLOX_USERNAME == "Builderman" and AUTO_RENDER then
	warn("[BlenderRender] Hinweis: Trage oben bei ROBLOX_USERNAME deinen eigenen Roblox-Namen ein!")
end

Players.PlayerAdded:Connect(function(player)
	print(("[BlenderRender] Spieler im Server: %s (bekommt das Bild ins GUI)"):format(player.Name))
	player.Chatted:Connect(function(message)
		local args = string.split(message, " ")
		if string.lower(args[1]) == "!render" then
			local name = #args >= 2 and table.concat(args, " ", 2) or ROBLOX_USERNAME
			statusPrint("🔁", ("Neuer Render-Auftrag per Chat: '%s'"):format(name), true)
			task.spawn(runPipeline, name)
		end
	end)
end)

if AUTO_RENDER then
	task.spawn(runPipeline, ROBLOX_USERNAME)
end
