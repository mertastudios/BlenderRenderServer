@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Blender Render Server - Oeffentliche Adresse
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Fehler: Das Setup wurde noch nicht ausgefuehrt!
    echo Bitte zuerst einen Doppelklick auf 01_setup.bat machen.
    pause
    exit /b 1
)

echo.
echo  ============================================================
echo    OEFFENTLICHE HTTPS-ADRESSE  (fuer veroeffentlichte Spiele)
echo  ============================================================
echo    Studio auf DIESEM PC: weiter http://localhost:8000 nutzen.
echo    Im echten Roblox-Client kommt die Anfrage von Roblox-
echo    Servern - localhost zeigt dann NICHT auf deinen PC.
echo.
echo    Dieses Programm erzeugt eine kostenlose https://... URL.
echo    Die URL im Lua-Skript bei RENDER_SERVER_URL eintragen.
echo    Fenster OFFEN lassen, solange jemand spielt.
echo  ============================================================
echo.

"venv\Scripts\python.exe" -m server.tunnel
echo.
echo Tunnel beendet. Fenster kann geschlossen werden.
pause
