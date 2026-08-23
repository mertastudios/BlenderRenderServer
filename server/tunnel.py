"""Oeffentliche HTTPS-Adresse per Cloudflare-Tunnel (fuer veroeffentlichte Roblox-Spiele).

Roblox-Studio auf demselben PC kann http://localhost:8000 nutzen.
Sobald das Spiel im Roblox-Client (nicht Studio) laeuft, kommt die Anfrage
von Roblox-Cloud-Servern - localhost zeigt dann NICHT auf deinen PC.

Loesung: Ein kostenloser Cloudflare-Quick-Tunnel erzeugt eine https://...-URL,
die von ueberall erreichbar ist. Roblox HttpService braucht im Live-Spiel HTTPS.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from . import config

URL_RE = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
URL_FILE = config.ROOT / "data" / "public_url.txt"
PID_FILE = config.ROOT / "data" / "tunnel.pid"

WINDOWS_URL = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-windows-amd64.exe"
)
LINUX_URL = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-linux-amd64"
)


def public_url() -> str:
    """Aktuelle oeffentliche URL (Tunnel-Datei hat Vorrang vor .env)."""
    try:
        text = URL_FILE.read_text(encoding="utf-8").strip()
        if text.startswith("http"):
            return text.split()[0]
    except OSError:
        pass
    return (config.PUBLIC_URL or "").strip()


def write_public_url(url: str) -> None:
    config.ensure_dirs()
    URL_FILE.write_text(url.strip() + "\n", encoding="utf-8")


def clear_public_url() -> None:
    try:
        URL_FILE.unlink()
    except OSError:
        pass


def _cloudflared_path() -> Path:
    name = "cloudflared.exe" if os.name == "nt" else "cloudflared"
    return config.ROOT / "tools" / "cloudflared" / name


def ensure_cloudflared() -> Path:
    dest = _cloudflared_path()
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = WINDOWS_URL if os.name == "nt" else LINUX_URL
    print(f"[Tunnel] cloudflared wird heruntergeladen ({url}) ...")
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(dest)
    except Exception as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise RuntimeError(
            "cloudflared konnte nicht geladen werden "
            f"({exc}). Lade die Datei manuell von\n"
            "  https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/\n"
            f"und lege sie hier ab:\n  {dest}"
        ) from exc
    if os.name != "nt":
        dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
    print(f"[Tunnel] cloudflared gespeichert: {dest}")
    return dest


def _print_url_box(url: str, token: str) -> None:
    print()
    print("=" * 66)
    print("  DEINE OEFFENTLICHE ADRESSE  (in Roblox eintragen):")
    print()
    print(f"     {url}")
    print()
    print("  Im Server-Skript (ServerScriptService) diese Zeilen setzen:")
    print(f'     local RENDER_SERVER_URL   = "{url}"')
    if token:
        print(f'     local RENDER_ACCESS_TOKEN = "{token}"')
    print()
    print("  Wichtig:")
    print("   - Dieses Fenster OFFEN lassen, solange jemand spielt.")
    print("   - Dein PC muss an sein, 02_start.bat muss laufen.")
    print("   - Quick-Tunnel: die Adresse aendert sich nach jedem Neustart.")
    print("   - Im veroeffentlichten Spiel braucht Roblox HTTPS (nicht http://).")
    print("=" * 66)
    print()


def run_tunnel(port: int | None = None) -> int:
    """Startet den Tunnel und blockiert, bis er beendet wird."""
    port = int(port or config.PORT)
    token = config.BRS_ACCESS_TOKEN
    try:
        exe = ensure_cloudflared()
    except RuntimeError as exc:
        print(f"[Tunnel] FEHLER: {exc}")
        return 1

    target = f"http://127.0.0.1:{port}"
    cmd = [str(exe), "tunnel", "--no-autoupdate", "--url", target]
    print(f"[Tunnel] Starte Cloudflare-Tunnel -> {target}")
    print("[Tunnel] Warte auf die oeffentliche https://... Adresse ...")

    config.ensure_dirs()
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(config.ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        print(f"[Tunnel] FEHLER: cloudflared konnte nicht starten ({exc})")
        return 1

    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    found = ""
    assert proc.stdout is not None
    try:
        for raw in proc.stdout:
            line = raw.rstrip()
            if line:
                # cloudflared ist gesprächig - nur Wichtiges durchreichen
                low = line.lower()
                if "err" in low or "fail" in low or "http/" in low:
                    print(f"  {line}")
            match = URL_RE.search(line)
            if match and not found:
                found = match.group(0)
                write_public_url(found)
                _print_url_box(found, token)
        code = proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        code = 0
        print("\n[Tunnel] Beendet.")
    finally:
        clear_public_url()
        try:
            PID_FILE.unlink()
        except OSError:
            pass
    if not found and code != 0:
        print(
            "[Tunnel] Es kam keine oeffentliche URL. "
            "Internet pruefen oder cloudflared manuell testen."
        )
    return int(code or 0)


def start_in_background(port: int | None = None) -> subprocess.Popen:
    """Startet den Tunnel als Kindprozess (fuer BRS_PUBLIC_TUNNEL=true)."""
    port = int(port or config.PORT)
    exe = ensure_cloudflared()
    target = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [str(exe), "tunnel", "--no-autoupdate", "--url", target],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(config.ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    config.ensure_dirs()
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")

    def _reader() -> None:
        found = ""
        assert proc.stdout is not None
        for raw in proc.stdout:
            match = URL_RE.search(raw)
            if match and not found:
                found = match.group(0)
                write_public_url(found)
                print(f"[Tunnel] Oeffentliche Adresse: {found}", flush=True)
                print(
                    "[Tunnel] Diese URL im Roblox-Skript bei RENDER_SERVER_URL eintragen.",
                    flush=True,
                )
        clear_public_url()

    threading.Thread(target=_reader, daemon=True, name="brs-tunnel").start()
    # kurz warten, damit ein schneller Fehler sichtbar wird
    time.sleep(0.4)
    if proc.poll() is not None:
        raise RuntimeError("cloudflared wurde sofort wieder beendet.")
    return proc


def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    print()
    print("=" * 66)
    print("  Oeffentliche HTTPS-Adresse fuer veroeffentlichte Roblox-Spiele")
    print("=" * 66)
    print("  Studio auf diesem PC: weiter http://localhost:8000 nutzen.")
    print("  Veroeffentlichtes Spiel: DIESE Adresse im Lua-Skript eintragen.")
    print("=" * 66)
    print()
    if not config.BRS_ACCESS_TOKEN:
        print(
            "[Tunnel] Tipp: Setze BRS_ACCESS_TOKEN in der .env, damit nicht"
        )
        print("         jeder mit der URL Render-Auftraege schicken kann.")
        print()
    return run_tunnel()


if __name__ == "__main__":
    raise SystemExit(main())
