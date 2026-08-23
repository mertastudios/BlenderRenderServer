--==============================================================================
--  BlenderRenderServer – CLIENT-SKRIPT (Roblox Studio)
--------------------------------------------------------------------------------
--  WO EINFUEGEN?
--    Im Studio-Explorer:  StarterPlayer → StarterPlayerScripts → Rechtsklick
--    → Insert Object → "LocalScript"  → diesen Text komplett einfuegen
--
--  WAS MACHT ES?
--    * Baut ein GUI-Fenster (Titel, Bild-Flaeche, Statuszeile, X-Button)
--    * Hoert auf das RemoteEvent "BlenderRender_Image"
--    * Schreibt die ankommenden Pixel-Pakete stueckweise in ein clientseitiges
--      EditableImage und zeigt es in der GUI an
--
--  VORAUSSETZUNG: Das Server-Skript (RenderServerService) muss ebenfalls
--  im ServerScriptService liegen - das verschickt die Daten hierher.
--==============================================================================

local Players           = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local AssetService      = game:GetService("AssetService")

local player = Players.LocalPlayer
local remote = ReplicatedStorage:WaitForChild("BlenderRender_Image", 30)

if not remote then
	warn("[BlenderRender-Client] RemoteEvent nicht gefunden - liegt das Server-Skript im ServerScriptService?")
	return
end

--------------------------------------------------------------------------------
-- GUI aufbauen
--------------------------------------------------------------------------------

local gui = Instance.new("ScreenGui")
gui.Name = "BlenderRenderGUI"
gui.ResetOnSpawn = false
gui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling

local frame = Instance.new("Frame")
frame.Name = "MainFrame"
frame.AnchorPoint = Vector2.new(0.5, 0.5)
frame.Position = UDim2.fromScale(0.5, 0.5)
frame.Size = UDim2.fromOffset(460, 580)
frame.BackgroundColor3 = Color3.fromRGB(24, 26, 32)
frame.BorderSizePixel = 0
frame.Active = true
frame.Parent = gui

local corner = Instance.new("UICorner")
corner.CornerRadius = UDim.new(0, 14)
corner.Parent = frame

local title = Instance.new("TextLabel")
title.Name = "Titel"
title.Size = UDim2.new(1, -60, 0, 46)
title.Position = UDim2.fromOffset(16, 8)
title.BackgroundTransparency = 1
title.Text = "🧊 Avatar-Render (Blender Cycles)"
title.TextColor3 = Color3.fromRGB(235, 240, 250)
title.Font = Enum.Font.GothamBold
title.TextSize = 18
title.TextXAlignment = Enum.TextXAlignment.Left
title.Parent = frame

local closeButton = Instance.new("TextButton")
closeButton.Name = "Close"
closeButton.Size = UDim2.fromOffset(36, 36)
closeButton.Position = UDim2.new(1, -44, 0, 12)
closeButton.BackgroundColor3 = Color3.fromRGB(45, 48, 58)
closeButton.Text = "✕"
closeButton.TextColor3 = Color3.fromRGB(230, 230, 235)
closeButton.Font = Enum.Font.GothamBold
closeButton.TextSize = 16
closeButton.Parent = frame

local closeCorner = Instance.new("UICorner")
closeCorner.CornerRadius = UDim.new(0, 10)
closeCorner.Parent = closeButton

closeButton.MouseButton1Click:Connect(function()
	gui:Destroy()
end)

local imageLabel = Instance.new("ImageLabel")
imageLabel.Name = "Bild"
imageLabel.Position = UDim2.fromOffset(20, 60)
imageLabel.Size = UDim2.new(1, -40, 1, -140)
imageLabel.BackgroundColor3 = Color3.fromRGB(32, 35, 43)
imageLabel.BorderSizePixel = 0
imageLabel.ScaleType = Enum.ScaleType.Fit
imageLabel.Image = ""
imageLabel.Parent = frame

local imageCorner = Instance.new("UICorner")
imageCorner.CornerRadius = UDim.new(0, 10)
imageCorner.Parent = imageLabel

local aspect = Instance.new("UIAspectRatioConstraint")
aspect.AspectRatio = 1
aspect.Parent = imageLabel

local status = Instance.new("TextLabel")
status.Name = "Status"
status.Position = UDim2.new(0, 20, 1, -70)
status.Size = UDim2.new(1, -40, 0, 54)
status.BackgroundTransparency = 1
status.Text = "Warte auf den Render-Server ..."
status.TextColor3 = Color3.fromRGB(150, 160, 180)
status.Font = Enum.Font.Gotham
status.TextSize = 14
status.TextWrapped = true
status.Parent = frame

gui.Parent = player:WaitForChild("PlayerGui")

--------------------------------------------------------------------------------
-- EditableImage + Datenempfang
--------------------------------------------------------------------------------

local editableImage = nil
local currentJobId = nil
local receivedRows = 0
local totalRows = 0

local function destroyImage()
	if editableImage then
		editableImage:Destroy()
		editableImage = nil
	end
end

local function ensureImage(width, height)
	if editableImage then
		return editableImage
	end
	local ok, result = pcall(function()
		return AssetService:CreateEditableImage({ Size = Vector2.new(width, height) })
	end)
	if ok and result then
		editableImage = result
		-- WICHTIG: EditableImage ist KEINE Instance, .Name gibt es nicht!
		-- Anzeige erfolgt ueber Content.fromObject (siehe naechste Zeile).
		imageLabel.ImageContent = Content.fromObject(editableImage)
		imageLabel.BackgroundColor3 = Color3.fromRGB(20, 22, 27)
		return editableImage
	end
	status.Text = "❌ EditableImage konnte nicht erstellt werden: " .. tostring(result)
	status.TextColor3 = Color3.fromRGB(240, 100, 100)
	return nil
end

remote.OnClientEvent:Connect(function(kind, jobId, a, b, c, d, buf)
	if kind == "status" then
		-- (jobId ist hier der Statustext)
		status.TextColor3 = Color3.fromRGB(150, 160, 180)
		status.Text = tostring(jobId)
		return
	end

	if kind == "chunk" then
		-- Reihenfolge: (jobId, y, rows, width, height, buffer)
		local y, rows, width, height = a, b, c, d
		if jobId ~= currentJobId then
			-- Ein neuer Auftrag beginnt -> altes Bild verwerfen
			destroyImage()
			currentJobId = jobId
			receivedRows = 0
			totalRows = height
		end
		local image = ensureImage(width, height)
		if image then
			local okWrite = pcall(function()
				image:WritePixelsBuffer(Vector2.new(0, y), Vector2.new(width, rows), buf)
			end)
			if not okWrite then
				status.Text = ("⚠️ Pixelpaket bei Zeile %d fehlgeschlagen"):format(y)
			end
			receivedRows = receivedRows + rows
			status.TextColor3 = Color3.fromRGB(120, 190, 255)
			status.Text = ("📡 Empfangen: %d / %d Zeilen"):format(
				math.min(receivedRows, totalRows), totalRows)
		end

	elseif kind == "done" then
		-- Reihenfolge: (jobId, width, height)
		status.TextColor3 = Color3.fromRGB(120, 230, 140)
		status.Text = ("✅ Fertig! Avatar-Render (%d×%d Pixel)"):format(a, b)
		print(("[BlenderRender-Client] Bild komplett: %dx%d"):format(a, b))
	end
end)

print("[BlenderRender-Client] bereit - wartet auf Bild-Daten vom Server ...")
