#!/usr/bin/env bash
# Optionales Start-Skript fuer Linux/macOS (Windows-Nutzer: 02_start.bat nutzen!)
cd "$(dirname "$0")"
mkdir -p logs
if [ ! -d "venv" ]; then
    python3 -m venv venv
    venv/bin/pip install --upgrade pip -q
    venv/bin/pip install -r server/requirements.txt
fi
echo "PID $$" > logs/pid.txt
# Blender automatisch laden, falls nicht vorhanden (Linux/macOS: bpy-Pip-Modul)
if ! command -v blender >/dev/null 2>&1 && ! [ -x "tools/blender/blender" ]; then
    venv/bin/pip install -q bpy 2>/dev/null || true
fi
exec venv/bin/python run.py
