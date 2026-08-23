@echo off
setlocal EnableExtensions
chcp 65001 >nul
title BRS-Verbindungscheck
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Fehler: Das Setup wurde noch nicht ausgefuehrt!
    echo Bitte zuerst einen Doppelklick auf 01_setup.bat machen.
    pause
    exit /b 1
)

"venv\Scripts\python.exe" -m server.diagnostics
echo.
pause
