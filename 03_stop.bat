@echo off
setlocal EnableExtensions
chcp 65001 >nul
title BRS-Stop
cd /d "%~dp0"

echo Beende den Blender Render Server ...

set "PID="
if exist "logs\pid.txt" set /p PID=<"logs\pid.txt"

if defined PID (
    echo Prozess-Baum (PID %PID%) wird beendet ...
    taskkill /PID %PID% /T /F >nul 2>&1
)

REM Ausweichweg: Konsolenfenster mit Server-Titel schliessen
taskkill /FI "WINDOWTITLE eq Blender Render Server" /IM cmd.exe /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Blender Render Server" /IM python.exe /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Blender Render Server - Oeffentliche Adresse" /F >nul 2>&1
taskkill /IM cloudflared.exe /F >nul 2>&1

if exist "logs\pid.txt" del "logs\pid.txt" >nul 2>&1
if exist "data\public_url.txt" del "data\public_url.txt" >nul 2>&1
if exist "data\tunnel.pid" del "data\tunnel.pid" >nul 2>&1

echo Fertig! Der Server ist jetzt AUS.
echo (Zum Wiederanschalten: 02_start.bat doppelklicken)
echo.
pause
