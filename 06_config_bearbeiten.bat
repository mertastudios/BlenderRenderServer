@echo off
setlocal EnableExtensions
chcp 65001 >nul
title BRS-Konfiguration
cd /d "%~dp0"

if not exist ".env" copy ".env.example" ".env" >nul

echo Oeffne die Konfigurationsdatei .env im Editor ...
echo Nach Aenderungen: Server mit 03_stop.bat stoppen und mit
echo 02_start.bat neu starten, damit die Aenderungen wirksam werden.
echo.
start "" notepad.exe "%~dp0.env"
