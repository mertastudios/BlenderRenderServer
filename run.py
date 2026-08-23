#!/usr/bin/env python3
"""Watchdog & Starter fuer den BlenderRenderServer.

Aufgaben:
  - Beim Start pruefen, ob der Server schon laeuft (dann nur melden)
  - Auto-Update vom GitHub-Haupt-Branch einspielen (wenn aktiviert)
  - Den eigentlichen Web-Server (uvicorn/FastAPI) starten
  - Nach einem Update oder Absturz automatisch neu starten

Manuell beenden: 03_stop.bat ausfuehren (oder das Fenster schliessen).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from server import config, updater  # noqa: E402


def _banner() -> None:
    print()
    print("=" * 62)
    print("       _     _                                       _            ")
    print("      | |   | |              _                       (_)           ")
    print(r"      | |__ | | __ _ _   _  | |_ _ __ __ _ _ __  ___ _ _ __   __ _ ")
    print(r"      | '_ \| |/ _` | | | | | __| '__/ _` | '_ \/ __| | '_ \ / _` |")
    print(r"      | |_) | | (_| | |_| | | |_| | | (_| | | | \__ \ | | | | (_| |")
    print(r"      |_.__/|_|\__,_|\__, |  \__|_|  \__,_|_| |_|___/_|_| |_|\__, |")
    print("                      __/ |                                   __/ |")
    print("     |___/                  Blender Render Server            |___/ ")
    print("=" * 62)
    print(f"  Projektordner : {ROOT}")
    print(f"  Studio-Adresse: http://localhost:{config.PORT}")
    print(f"  Modus         : {'TEST-MODUS (offline Testfigur)' if config.TEST_MODE else 'Normal'}")
    print(f"  API-Key       : {'gesetzt' if config.ROBLOX_API_KEY else 'FEHLT (3D-Avatare: ANLEITUNG.md §9)'}")
    print("  Beenden       : 03_stop.bat ausfuehren oder dieses Fenster schliessen")
    print("=" * 62)
    print()


def _already_running() -> bool:
    try:
        import requests

        resp = requests.get(f"http://127.0.0.1:{config.PORT}/health", timeout=2)
        return resp.ok
    except Exception:
        return False


def _write_pid() -> None:
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "pid.txt").write_text(str(os.getpid()), encoding="utf-8")


def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)  # Live-Ausgaben in der Konsole
    except Exception:
        pass
    _banner()
    config.ensure_dirs()

    if _already_running():
        print(f"[Start] Der Server laeuft bereits auf Port {config.PORT}.")
        print("[Start] Nichts zu tun. (Zum Neustarten zuerst 03_stop.bat ausfuehren.)")
        time.sleep(5)
        return 0
    _write_pid()

    if config.AUTO_UPDATE:
        try:
            updated, msg = updater.check_and_apply()
            print(f"[Update] {msg}")
        except Exception as exc:  # noqa: BLE001
            print(f"[Update] Fehler beim Update-Check (Server startet trotzdem): {exc}")

    cmd = [
        sys.executable, "-m", "uvicorn", "server.app:app",
        "--host", config.HOST, "--port", str(config.PORT),
        "--log-level", "warning",
    ]

    restarts = 0
    while True:
        print(f"[Start] Web-Server wird gestartet (http://localhost:{config.PORT}) ...")
        try:
            proc = subprocess.run(cmd, cwd=str(ROOT))
            code = proc.returncode
        except KeyboardInterrupt:
            print("\n[Start] Beendet (Strg+C). Bis zum naechsten Start!")
            return 0
        if code == 0:
            print("[Start] Server sauber beendet.")
            return 0
        if code == 77:
            print("[Start] Update wurde installiert -> Server startet neu ...")
            continue
        restarts += 1
        print(f"[Start] Server wurde unerwartet beendet (Code {code}).")
        print(f"[Start] Automatischer Neustart in 5 s ... (Neustart Nr. {restarts})")
        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
