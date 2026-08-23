@echo off
setlocal EnableExtensions
chcp 65001 >nul
title BRS-Autostart-Entfernen
cd /d "%~dp0"

schtasks /Delete /TN "BlenderRenderServer" /F >nul 2>&1

if errorlevel 1 (
    echo Es gab keine Autostart-Aufgabe - nichts zu entfernen.
) else (
    echo Autostart entfernt. Der Server startet beim naechsten
    echo PC-Neustart NICHT mehr automatisch.
    echo Manuell starten kannst du ihn weiterhin mit 02_start.bat
)
echo.
pause
