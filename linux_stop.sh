#!/usr/bin/env bash
# Beendet den laufenden Server (Linux/macOS)
cd "$(dirname "$0")"
if [ -f logs/pid.txt ]; then
    PID=$(cat logs/pid.txt)
    kill -- -"$PID" 2>/dev/null || kill "$PID" 2>/dev/null
    rm -f logs/pid.txt
    echo "Server beendet."
else
    echo "Keine PID-Datei gefunden (Server laeuft nicht?)."
fi
