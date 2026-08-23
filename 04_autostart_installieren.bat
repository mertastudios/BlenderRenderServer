@echo off
setlocal EnableExtensions
chcp 65001 >nul
title BRS-Autostart
cd /d "%~dp0"

echo Richte Windows-Aufgabenplanung ein: Server startet automatisch
echo bei jeder Anmeldung (also auch nach jedem PC-Neustart).
echo.

schtasks /Create /F /TN "BlenderRenderServer" /TR "\"%~dp002_start.bat\"" /SC ONLOGON /DELAY 0000:20 >nul 2>&1

if errorlevel 1 (
    echo FEHLER: Die Aufgabe konnte nicht angelegt werden.
    echo Versuche es mit einem Rechtsklick auf diese Datei und
    echo "Als Administrator ausfuehren".
    pause
    exit /b 1
)

echo ============================================================
echo  ERFOLGREICH! Ab jetzt passiert Folgendes:
echo   - Beim Windows-Start (Anmeldung) startet der Server
echo     automatisch, ca. 20 Sekunden nach der Anmeldung.
echo   - Du siehst dann ein schwarzes Konsolenfenster - das ist
echo     der Server. Einfach minimieren und fertig.
echo   - AUSSCHALTEN kannst du ihn jederzeit mit 03_stop.bat
echo     (nach dem naechsten Neustart ist er wieder an).
echo   - Dauerhaft entfernen: 05_autostart_entfernen.bat
echo ============================================================
echo.
pause
