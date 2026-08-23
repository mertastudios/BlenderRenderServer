--==============================================================================
--  BlenderRenderServer – CLIENT-SKRIPT (Roblox Studio)
--------------------------------------------------------------------------------
--  WO EINFUEGEN?
--    Im Studio-Explorer:  StarterPlayer → StarterPlayerScripts → Rechtsklick
--    → Insert Object → "LocalScript"  → diesen Text komplett einfuegen
--
--  NEUE FEATURES:
--    * Detaillierte Schritt-fuer-Schritt-Anzeige (Schritt 1 bis 5)
--    * Dynamische geschaetzte Restzeit & animierter Ladebalken mit Prozent
--    * Live-Bildempfang in ein hochaufloesendes EditableImage
--    * Interaktive Steuerung: Avatar-Auswahl per Eingabefeld & Rendern-Button
--==============================================================================

local Players           = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local AssetService      = game:GetService("AssetService")
local TweenService      = game:GetService("TweenService")

local player = Players.LocalPlayer
local remoteImage  = ReplicatedStorage:WaitForChild("BlenderRender_Image", 30)
local remoteStatus = ReplicatedStorage:WaitForChild("BlenderRender_Status", 30)
local remoteReq    = ReplicatedStorage:WaitForChild("BlenderRender_Request", 30)

--------------------------------------------------------------------------------
-- GUI AUFBAU (Modernes Dark-UI mit Animationen)
--------------------------------------------------------------------------------

local gui = Instance.new("ScreenGui")
gui.Name = "BlenderRenderGUI"
gui.ResetOnSpawn = false
gui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling

local mainFrame = Instance.new("Frame")
mainFrame.Name = "MainFrame"
mainFrame.AnchorPoint = Vector2.new(0.5, 0.5)
mainFrame.Position = UDim2.fromScale(0.5, 0.5)
mainFrame.Size = UDim2.fromOffset(480, 680)
mainFrame.BackgroundColor3 = Color3.fromRGB(20, 22, 28)
mainFrame.BorderSizePixel = 0
mainFrame.Active = true
mainFrame.Draggable = true
mainFrame.Parent = gui

local mainCorner = Instance.new("UICorner")
mainCorner.CornerRadius = UDim.new(0, 16)
mainCorner.Parent = mainFrame

local mainStroke = Instance.new("UIStroke")
mainStroke.Color = Color3.fromRGB(45, 52, 68)
mainStroke.Thickness = 1.5
mainStroke.Parent = mainFrame

-- Kopfzeile -------------------------------------------------------------------
local topBar = Instance.new("Frame")
topBar.Name = "TopBar"
topBar.Size = UDim2.new(1, 0, 0, 48)
topBar.BackgroundTransparency = 1
topBar.Parent = mainFrame

local titleLabel = Instance.new("TextLabel")
titleLabel.Name = "Titel"
titleLabel.Size = UDim2.new(1, -90, 1, 0)
titleLabel.Position = UDim2.fromOffset(16, 0)
titleLabel.BackgroundTransparency = 1
titleLabel.Text = "🧊 Blender Render Studio"
titleLabel.TextColor3 = Color3.fromRGB(240, 245, 255)
titleLabel.Font = Enum.Font.GothamBold
titleLabel.TextSize = 17
titleLabel.TextXAlignment = Enum.TextXAlignment.Left
titleLabel.Parent = topBar

local closeBtn = Instance.new("TextButton")
closeBtn.Name = "CloseBtn"
closeBtn.Size = UDim2.fromOffset(32, 32)
closeBtn.Position = UDim2.new(1, -40, 0, 8)
closeBtn.BackgroundColor3 = Color3.fromRGB(38, 42, 54)
closeBtn.Text = "✕"
closeBtn.TextColor3 = Color3.fromRGB(200, 205, 215)
closeBtn.Font = Enum.Font.GothamBold
closeBtn.TextSize = 14
closeBtn.Parent = topBar

local closeCorner = Instance.new("UICorner")
closeCorner.CornerRadius = UDim.new(0, 8)
closeCorner.Parent = closeBtn

closeBtn.MouseButton1Click:Connect(function()
	gui:Destroy()
end)

-- Steuerungs-Leiste (Benutzername & Rendern-Button) ----------------------------
local controlBar = Instance.new("Frame")
controlBar.Name = "ControlBar"
controlBar.Size = UDim2.new(1, -32, 0, 36)
controlBar.Position = UDim2.fromOffset(16, 52)
controlBar.BackgroundTransparency = 1
controlBar.Parent = mainFrame

local userBox = Instance.new("TextBox")
userBox.Name = "UserBox"
userBox.Size = UDim2.new(1, -110, 1, 0)
userBox.BackgroundColor3 = Color3.fromRGB(28, 32, 42)
userBox.Text = player.Name
userBox.PlaceholderText = "Roblox Benutzername"
userBox.TextColor3 = Color3.fromRGB(230, 235, 245)
userBox.PlaceholderColor3 = Color3.fromRGB(120, 130, 150)
userBox.Font = Enum.Font.GothamMedium
userBox.TextSize = 13
userBox.ClearTextOnFocus = false
userBox.Parent = controlBar

local userCorner = Instance.new("UICorner")
userCorner.CornerRadius = UDim.new(0, 8)
userCorner.Parent = userBox

local userPadding = Instance.new("UIPadding")
userPadding.PaddingLeft = UDim.new(0, 10)
userPadding.Parent = userBox

local renderBtn = Instance.new("TextButton")
renderBtn.Name = "RenderBtn"
renderBtn.Size = UDim2.fromOffset(100, 36)
renderBtn.Position = UDim2.new(1, -100, 0, 0)
renderBtn.BackgroundColor3 = Color3.fromRGB(37, 99, 235)
renderBtn.Text = "🚀 Rendern"
renderBtn.TextColor3 = Color3.fromRGB(255, 255, 255)
renderBtn.Font = Enum.Font.GothamBold
renderBtn.TextSize = 13
renderBtn.Parent = controlBar

local renderCorner = Instance.new("UICorner")
renderCorner.CornerRadius = UDim.new(0, 8)
renderCorner.Parent = renderBtn

-- Bild-Bereich ----------------------------------------------------------------
local imageContainer = Instance.new("Frame")
imageContainer.Name = "ImageContainer"
imageContainer.Position = UDim2.fromOffset(16, 98)
imageContainer.Size = UDim2.new(1, -32, 0, 420)
imageContainer.BackgroundColor3 = Color3.fromRGB(15, 17, 22)
imageContainer.BorderSizePixel = 0
imageContainer.Parent = mainFrame

local imageCorner = Instance.new("UICorner")
imageCorner.CornerRadius = UDim.new(0, 12)
imageCorner.Parent = imageContainer

local imageStroke = Instance.new("UIStroke")
imageStroke.Color = Color3.fromRGB(35, 40, 52)
imageStroke.Thickness = 1
imageStroke.Parent = imageContainer

local imageLabel = Instance.new("ImageLabel")
imageLabel.Name = "RenderImage"
imageLabel.Size = UDim2.fromScale(1, 1)
imageLabel.BackgroundTransparency = 1
imageLabel.ScaleType = Enum.ScaleType.Fit
imageLabel.Image = ""
imageLabel.Parent = imageContainer

local placeholderLabel = Instance.new("TextLabel")
placeholderLabel.Name = "Placeholder"
placeholderLabel.Size = UDim2.fromScale(1, 1)
placeholderLabel.BackgroundTransparency = 1
placeholderLabel.Text = "Warte auf Render-Start ...\n(Klicke oben auf 'Rendern')"
placeholderLabel.TextColor3 = Color3.fromRGB(90, 100, 120)
placeholderLabel.Font = Enum.Font.GothamMedium
placeholderLabel.TextSize = 14
placeholderLabel.Parent = imageContainer

-- Schritt- & Fortschritts-Anzeige ----------------------------------------------
local progressCard = Instance.new("Frame")
progressCard.Name = "ProgressCard"
progressCard.Position = UDim2.fromOffset(16, 528)
progressCard.Size = UDim2.new(1, -32, 0, 136)
progressCard.BackgroundColor3 = Color3.fromRGB(26, 30, 40)
progressCard.BorderSizePixel = 0
progressCard.Parent = mainFrame

local cardCorner = Instance.new("UICorner")
cardCorner.CornerRadius = UDim.new(0, 12)
cardCorner.Parent = progressCard

-- Schritt-Badge + Restzeit
local stepBadge = Instance.new("TextLabel")
stepBadge.Name = "StepBadge"
stepBadge.Position = UDim2.fromOffset(12, 10)
stepBadge.Size = UDim2.fromOffset(120, 22)
stepBadge.BackgroundColor3 = Color3.fromRGB(37, 99, 235)
stepBadge.Text = "Schritt 1 von 5"
stepBadge.TextColor3 = Color3.fromRGB(255, 255, 255)
stepBadge.Font = Enum.Font.GothamBold
stepBadge.TextSize = 11
stepBadge.Parent = progressCard

local badgeCorner = Instance.new("UICorner")
badgeCorner.CornerRadius = UDim.new(0, 6)
badgeCorner.Parent = stepBadge

local timeBadge = Instance.new("TextLabel")
timeBadge.Name = "TimeBadge"
timeBadge.Position = UDim2.new(1, -150, 0, 10)
timeBadge.Size = UDim2.fromOffset(138, 22)
timeBadge.BackgroundTransparency = 1
timeBadge.Text = "⏱️ Restzeit: ~0 s"
timeBadge.TextColor3 = Color3.fromRGB(150, 165, 190)
timeBadge.Font = Enum.Font.GothamMedium
timeBadge.TextSize = 12
timeBadge.TextXAlignment = Enum.TextXAlignment.Right
timeBadge.Parent = progressCard

-- Schritt-Name & Detail-Text
local stepTitle = Instance.new("TextLabel")
stepTitle.Name = "StepTitle"
stepTitle.Position = UDim2.fromOffset(12, 36)
stepTitle.Size = UDim2.new(1, -24, 0, 20)
stepTitle.BackgroundTransparency = 1
stepTitle.Text = "Bereit"
stepTitle.TextColor3 = Color3.fromRGB(230, 240, 255)
stepTitle.Font = Enum.Font.GothamBold
stepTitle.TextSize = 14
stepTitle.TextXAlignment = Enum.TextXAlignment.Left
stepTitle.Parent = progressCard

local detailLabel = Instance.new("TextLabel")
detailLabel.Name = "Detail"
detailLabel.Position = UDim2.fromOffset(12, 58)
detailLabel.Size = UDim2.new(1, -24, 0, 32)
detailLabel.BackgroundTransparency = 1
detailLabel.Text = "Klicke auf 'Rendern' um deinen Avatar in Cycles zu erstellen."
detailLabel.TextColor3 = Color3.fromRGB(140, 150, 170)
detailLabel.Font = Enum.Font.Gotham
detailLabel.TextSize = 12
detailLabel.TextWrapped = true
detailLabel.TextXAlignment = Enum.TextXAlignment.Left
detailLabel.TextYAlignment = Enum.TextYAlignment.Top
detailLabel.Parent = progressCard

-- Ladebalken
local barBackground = Instance.new("Frame")
barBackground.Name = "BarBackground"
barBackground.Position = UDim2.fromOffset(12, 98)
barBackground.Size = UDim2.new(1, -64, 0, 10)
barBackground.BackgroundColor3 = Color3.fromRGB(18, 20, 26)
barBackground.BorderSizePixel = 0
barBackground.Parent = progressCard

local barBgCorner = Instance.new("UICorner")
barBgCorner.CornerRadius = UDim.new(0, 5)
barBgCorner.Parent = barBackground

local barFill = Instance.new("Frame")
barFill.Name = "BarFill"
barFill.Size = UDim2.fromScale(0, 1)
barFill.BackgroundColor3 = Color3.fromRGB(59, 130, 246)
barFill.BorderSizePixel = 0
barFill.Parent = barBackground

local fillCorner = Instance.new("UICorner")
fillCorner.CornerRadius = UDim.new(0, 5)
fillCorner.Parent = barFill

local fillGrad = Instance.new("UIGradient")
fillGrad.Color = ColorSequence.new({
	ColorSequenceKeypoint.new(0.0, Color3.fromRGB(59, 130, 246)),
	ColorSequenceKeypoint.new(1.0, Color3.fromRGB(16, 185, 129)),
})
fillGrad.Parent = barFill

local percentLabel = Instance.new("TextLabel")
percentLabel.Name = "Percent"
percentLabel.Position = UDim2.new(1, -48, 0, 93)
percentLabel.Size = UDim2.fromOffset(40, 18)
percentLabel.BackgroundTransparency = 1
percentLabel.Text = "0%"
percentLabel.TextColor3 = Color3.fromRGB(200, 210, 230)
percentLabel.Font = Enum.Font.GothamBold
percentLabel.TextSize = 12
percentLabel.TextXAlignment = Enum.TextXAlignment.Right
percentLabel.Parent = progressCard

gui.Parent = player:WaitForChild("PlayerGui")

--------------------------------------------------------------------------------
-- EditableImage & Live-Stream Handling
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
		imageLabel.ImageContent = Content.fromObject(editableImage)
		placeholderLabel.Visible = false
		return editableImage
	end
	detailLabel.Text = "❌ EditableImage konnte nicht erstellt werden: " .. tostring(result)
	return nil
end

local function setProgress(pct)
	pct = math.clamp(pct / 100, 0, 1)
	TweenService:Create(barFill, TweenInfo.new(0.3, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), {
		Size = UDim2.fromScale(pct, 1)
	}):Play()
	percentLabel.Text = ("%d%%"):format(math.floor(pct * 100))
end

-- Status-Event verarbeiten ----------------------------------------------------
if remoteStatus then
	remoteStatus.OnClientEvent:Connect(function(data)
		if typeof(data) ~= "table" then return end

		local step = data.step or 1
		local totalSteps = data.totalSteps or 5
		local stepName = data.stepName or "In Bearbeitung"
		local message = data.message or ""
		local progress = data.progress or 0
		local estSeconds = data.estSecondsLeft or 0

		stepBadge.Text = ("Schritt %d von %d"):format(step, totalSteps)
		stepTitle.Text = stepName
		detailLabel.Text = message
		setProgress(progress)

		if estSeconds > 0 then
			timeBadge.Text = ("⏱️ Restzeit: ~%d s"):format(estSeconds)
			timeBadge.TextColor3 = Color3.fromRGB(120, 200, 255)
		else
			timeBadge.Text = "⏱️ Bereit"
			timeBadge.TextColor3 = Color3.fromRGB(150, 165, 190)
		end

		if data.state == "done" then
			stepBadge.BackgroundColor3 = Color3.fromRGB(16, 185, 129)
			stepBadge.Text = "Fertig"
			timeBadge.Text = "✅ Abgeschlossen"
			timeBadge.TextColor3 = Color3.fromRGB(120, 230, 140)
		elseif data.state == "error" then
			stepBadge.BackgroundColor3 = Color3.fromRGB(239, 68, 68)
			stepBadge.Text = "Fehler"
			detailLabel.TextColor3 = Color3.fromRGB(248, 113, 113)
		else
			stepBadge.BackgroundColor3 = Color3.fromRGB(37, 99, 235)
			detailLabel.TextColor3 = Color3.fromRGB(140, 150, 170)
		end
	end)
end

-- Bild-Daten-Event verarbeiten ------------------------------------------------
if remoteImage then
	remoteImage.OnClientEvent:Connect(function(kind, jobId, a, b, c, d, buf)
		if kind == "status" then
			detailLabel.Text = tostring(jobId)
			return
		end

		if kind == "chunk" then
			local y, rows, width, height = a, b, c, d
			if jobId ~= currentJobId then
				destroyImage()
				currentJobId = jobId
				receivedRows = 0
				totalRows = height
			end
			local img = ensureImage(width, height)
			if img then
				pcall(function()
					img:WritePixelsBuffer(Vector2.new(0, y), Vector2.new(width, rows), buf)
				end)
				receivedRows = receivedRows + rows
				stepBadge.Text = "Schritt 5 von 5"
				stepTitle.Text = "Bild wird uebertragen"
				detailLabel.Text = ("📡 Empfange Pixelzeilen: %d / %d (%d%%)"):format(
					receivedRows, totalRows, math.floor(receivedRows / totalRows * 100))
				setProgress(95 + (receivedRows / totalRows) * 5)
			end

		elseif kind == "done" then
			stepBadge.BackgroundColor3 = Color3.fromRGB(16, 185, 129)
			stepBadge.Text = "Fertig"
			stepTitle.Text = "Avatar erfolgreich gerendert!"
			detailLabel.Text = ("✅ Bild komplett (%d×%d Pixel) gerendert & uebertragen."):format(a, b)
			setProgress(100)
		end
	end)
end

-- Rendern-Button Klick --------------------------------------------------------
renderBtn.MouseButton1Click:Connect(function()
	local targetUser = userBox.Text:match("^%s*(.-)%s*$")
	if #targetUser == 0 then
		targetUser = player.Name
	end
	placeholderLabel.Visible = true
	placeholderLabel.Text = "Auftrag wird an den Server gesendet ..."
	destroyImage()
	setProgress(5)
	stepBadge.Text = "Schritt 1 von 5"
	stepTitle.Text = "Verbindung herstellen"
	detailLabel.Text = ("Auftrag fuer '%s' wird eingereicht ..."):format(targetUser)

	if remoteReq then
		task.spawn(function()
			remoteReq:InvokeServer(targetUser)
		end)
	end
end)

print("[BlenderRender-Client] GUI erfolgreich geladen.")
