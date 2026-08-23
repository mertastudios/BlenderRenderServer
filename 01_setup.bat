@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Blender Render Server - Setup
cd /d "%~dp0"

echo.
echo  ============================================================
echo    BLENDER RENDER SERVER - SETUP  (nur EINMAL ausfuehren)
echo  ============================================================
echo    Dieses Setup installiert automatisch alles Noetige:
echo      1/4  Python        (falls noch nicht vorhanden, ca. 25 MB)
echo      2/4  Python-Pakete fuer den Server (klein)
echo      3/4  Blender 4.5   (ca. 400 MB - ein paar Minuten Download)
echo      4/4  Konfiguration (.env) anlegen
echo.
echo    Danach ist das System einsatzbereit!
echo  ============================================================
echo.
echo  Wichtig: Internetverbindung noetig. Fenster offen lassen,
echo  bis "SETUP FERTIG" erscheint.
echo.
pause

REM ======================= 1) PYTHON ============================
set "PYEXE="
py -3 --version >nul 2>&1 && set "PYEXE=py -3"
if not defined PYEXE python --version >nul 2>&1 && set "PYEXE=python"

if defined PYEXE (
    echo [1/4] Python ist bereits vorhanden. Gut!
    goto :PYTHON_OK
)

echo [1/4] Python wurde nicht gefunden und wird jetzt installiert ...
echo        (Es oeffnet sich evtl. kurz ein Installer-Fenster)
where curl >nul 2>&1
if %errorlevel%==0 (
    curl -fL -o "%TEMP%\python-install.exe" https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe
) else (
    powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile \"$env:TEMP\python-install.exe\" } catch { exit 1 }"
)
if not exist "%TEMP%\python-install.exe" (
    echo.
    echo  FEHLER: Python konnte nicht heruntergeladen werden.
    echo  Bitte Internetverbindung pruefen und 01_setup.bat erneut starten.
    goto :FAIL
)
echo        Installation laeuft (1-3 Minuten, bitte warten) ...
"%TEMP%\python-install.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
del "%TEMP%\python-install.exe" >nul 2>&1
set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not exist "%PYEXE%" (
    echo.
    echo  FEHLER: Python wurde scheinbar nicht installiert.
    echo  Bitte den PC einmal neu starten und 01_setup.bat erneut ausfuehren.
    goto :FAIL
)

:PYTHON_OK
REM ==================== 2) PYTHON-PAKETE ========================
echo [2/4] Virtuelle Python-Umgebung + Pakete werden eingerichtet ...
if not exist "venv\Scripts\python.exe" %PYEXE% -m venv venv
if not exist "venv\Scripts\python.exe" (
    echo  FEHLER: Umgebung konnte nicht erstellt werden.
    goto :FAIL
)
"venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
"venv\Scripts\python.exe" -m pip install -r "server\requirements.txt"
if errorlevel 1 (
    echo.
    echo  FEHLER: Python-Pakete konnten nicht installiert werden.
    echo  Bitte Internetverbindung pruefen und erneut versuchen.
    goto :FAIL
)

REM ======================= 3) BLENDER ===========================
if exist "tools\blender\blender.exe" (
    echo [3/4] Blender ist bereits vorhanden. Gut!
    goto :BLENDER_OK
)
echo [3/4] Blender 4.5 wird heruntergeladen (ca. 400 MB) ...
echo        Der Fortschrittsbalken gehoert zu curl - bitte warten.
if not exist "tools" mkdir "tools"
set "BZIP=%TEMP%\blender-4.5.9-windows-x64.zip"
curl -fL --progress-bar -o "%BZIP%" "https://download.blender.org/release/Blender4.5/blender-4.5.9-windows-x64.zip"
if errorlevel 1 curl -fL --progress-bar -o "%BZIP%" "https://ftp.nluug.nl/pub/graphics/blender/release/Blender4.5/blender-4.5.9-windows-x64.zip"
if errorlevel 1 powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'https://download.blender.org/release/Blender4.5/blender-4.5.9-windows-x64.zip' -OutFile '%BZIP%' } catch { exit 1 }"
if not exist "%BZIP%" (
    echo.
    echo  FEHLER: Blender konnte nicht geladen werden.
    echo  Alternativ: Blender selbst von blender.org laden, in den Ordner
    echo  "tools\blender" entpacken und dieses Setup erneut ausfuehren.
    goto :FAIL
)
echo        Blender wird entpackt (dauert 1-2 Minuten) ...
where tar >nul 2>&1
if %errorlevel%==0 (
    tar -xf "%BZIP%" -C "%~dp0tools"
) else (
    powershell -NoProfile -Command "Expand-Archive -Path '%BZIP%' -DestinationPath '%~dp0tools' -Force"
)
del "%BZIP%" >nul 2>&1
for /d %%D in ("%~dp0tools\blender-*") do ren "%%D" blender
if not exist "tools\blender\blender.exe" (
    echo  FEHLER: Entpacken fehlgeschlagen. Bitte Ordner "tools" loeschen
    echo  und dieses Setup erneut ausfuehren.
    goto :FAIL
)

:BLENDER_OK
REM ==================== 4) KONFIGURATION =======================
if exist ".env" (
    echo [4/4] Konfiguration (.env) existiert bereits - bleibt unangetastet.
) else (
    copy ".env.example" ".env" >nul
    echo [4/4] Konfigurationsdatei .env wurde erstellt.
)

echo.
echo  ============================================================
echo    SETUP FERTIG!  Was jetzt?
echo  ============================================================
echo    1. Einstellungen pruefen:  06_config_bearbeiten.bat
echo    2. Server starten:         02_start.bat
echo    3. (Empfohlen) Autostart:  04_autostart_installieren.bat
echo    4. Roblox-Teil einrichten: ANLEITUNG.md, Abschnitt Roblox
echo  ============================================================
echo.
pause
exit /b 0

:FAIL
echo.
echo  Setup ABGEBROCHEN. Fehler oben nachlesen und erneut versuchen.
pause
exit /b 1
