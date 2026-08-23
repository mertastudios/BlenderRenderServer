@echo off
setlocal EnableExtensions
chcp 65001 >nul
title BRS-Test
cd /d "%~dp0"

set "PORT=8000"
for /f %%P in ('powershell -NoProfile -Command "$p=8000; if (Test-Path .env) { $line = Get-Content .env | Where-Object { $_ -match '^\s*BRS_PORT\s*=' } | Select-Object -First 1; if ($line) { $v = ($line -replace '^\s*BRS_PORT\s*=','').Trim(); if ($v -match '^\d+$') { $p = $v } } }; Write-Output $p"') do set "PORT=%%P"

echo Oeffne http://localhost:%PORT% im Browser ...
echo (Dort siehst du den Live-Status des Render-Servers.)
start "" "http://localhost:%PORT%"
