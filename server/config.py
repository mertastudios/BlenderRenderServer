"""Zentrale Konfiguration.

Laedt die Datei .env aus dem Projekt-Root (wenn vorhanden) und stellt alle
Einstellungen als einfachen Zugriff bereit. Echte Umgebungsvariablen haben
immer Vorrang vor der .env-Datei.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Projekt-Root = Ordner, in dem run.py liegt ( Elternordner von server/ )
ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def _parse_env_file(path: Path) -> dict:
    data = {}
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return data
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.split(" #")[0].strip().strip('"').strip("'")
        if key:
            data[key] = value
    return data


def load_env() -> dict:
    """.env in die Prozess-Umgebung laden (vorhandene Variablen bleiben)."""
    for key, value in _parse_env_file(ENV_FILE).items():
        os.environ.setdefault(key, value)
    return dict(os.environ)


load_env()


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def get_bool(key: str, default: bool = False) -> bool:
    return get(key, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on", "ja")


def get_int(key: str, default: int) -> int:
    try:
        return int(get(key, str(default)))
    except ValueError:
        return default


# ------------------------------------------------------------------------------
#  Server
# ------------------------------------------------------------------------------
HOST = get("BRS_HOST", "0.0.0.0")
PORT = get_int("BRS_PORT", 8000)

# ------------------------------------------------------------------------------
#  Roblox
# ------------------------------------------------------------------------------
# Open-Cloud-API-Key. Seit 23. Maerz 2026 PFLICHT fuer den 3D-Avatar-Download
# (Recht "thumbnails: Read"). Ohne Key antwortet Roblox mit HTTP 401/403.
# Optional zusaetzlich: "asset-legacy-delivery: Read" als Ausweichweg.
ROBLOX_API_KEY = get("ROBLOX_API_KEY", "").strip()

# ------------------------------------------------------------------------------
#  Veroeffentlichte Spiele / Sicherheit
# ------------------------------------------------------------------------------
# Feste oeffentliche Basis-URL (https://...), falls du selbst hostest.
# Ein laufender Cloudflare-Tunnel (08_oeffentliche_adresse.bat) hat Vorrang.
PUBLIC_URL = get("PUBLIC_URL", "").strip().rstrip("/")
# true = beim Serverstart automatisch einen Cloudflare-Quick-Tunnel oeffnen
PUBLIC_TUNNEL = get_bool("BRS_PUBLIC_TUNNEL", False)
# Gemeinsames Geheimnis. Wenn gesetzt, muessen /jobs-Anfragen den Header
# X-BRS-Token mitschicken (im Lua-Skript: RENDER_ACCESS_TOKEN).
BRS_ACCESS_TOKEN = get("BRS_ACCESS_TOKEN", "").strip()

# ------------------------------------------------------------------------------
#  Blender / Rendering
# ------------------------------------------------------------------------------
RENDER_WIDTH = min(get_int("RENDER_WIDTH", 1024), 1024)
RENDER_HEIGHT = min(get_int("RENDER_HEIGHT", 1024), 1024)
RENDER_SAMPLES = max(get_int("RENDER_SAMPLES", 96), 16)
RENDER_MATERIAL = get("RENDER_MATERIAL", "glass").strip().lower()  # glass | matt | transparent_glass | original
RENDER_DEVICE = get("RENDER_DEVICE", "CPU").strip().upper()        # CPU | GPU | AUTO
# false = schoener Himmelshintergrund (empfohlen fuer Glas)
# true  = transparenter Hintergrund (PNG mit Alpha)
RENDER_TRANSPARENT_BG = get_bool("RENDER_TRANSPARENT_BG", False)

# Leer = automatisch suchen (tools/blender/... oder im PATH oder pip-Modul bpy)
BLENDER_PATH = get("BLENDER_PATH", "").strip()
# auto | subprocess | bpy   (bpy = Blender als Python-Pip-Modul, in-process)
BLENDER_MODE = get("BLENDER_MODE", "auto").strip().lower()

# ------------------------------------------------------------------------------
#  Assets & Custom 3D Models
# ------------------------------------------------------------------------------
ASSETS_DIR = ROOT / "assets"
MODELS_DIR = ASSETS_DIR / "models"
HANDS_DIR = ASSETS_DIR / "hands"

# ------------------------------------------------------------------------------
#  Job Retention / Bereinigung (in Tagen, Standard: 7 Tage)
# ------------------------------------------------------------------------------
JOB_RETENTION_DAYS = max(get_int("JOB_RETENTION_DAYS", 7), 1)
JOB_RETENTION_SECONDS = JOB_RETENTION_DAYS * 86400

# ------------------------------------------------------------------------------
#  Auto-Update
# ------------------------------------------------------------------------------
AUTO_UPDATE = get_bool("AUTO_UPDATE", True)
AUTO_UPDATE_CHECK_SECONDS = max(get_int("AUTO_UPDATE_CHECK_SECONDS", 300), 30)
GITHUB_REPO = get("GITHUB_REPO", "mertastudios/BlenderRenderServer").strip("/")
GITHUB_BRANCH = get("GITHUB_BRANCH", "main").strip()

# ------------------------------------------------------------------------------
#  Test / Debug
# ------------------------------------------------------------------------------
# BRS_TEST_MODE=true  -> statt eines echten Avatars wird lokal ein Test-Figur
# gerendert (funktioniert ganz ohne Roblox-Server, gut zur Fehlersuche)
TEST_MODE = get_bool("BRS_TEST_MODE", False)


def version() -> str:
    """Kurzform des installierten Git-Stands (aus .update/state.json)."""
    try:
        state = json.loads((ROOT / ".update" / "state.json").read_text(encoding="utf-8"))
        sha = state.get("sha", "")
        return sha[:7] if sha else "unbekannt"
    except Exception:
        return "unbekannt"


def ensure_dirs() -> None:
    for p in (
        ROOT / "data",
        ROOT / "data" / "jobs",
        ROOT / "logs",
        ROOT / ".update",
        ASSETS_DIR,
        MODELS_DIR,
        HANDS_DIR,
    ):
        p.mkdir(parents=True, exist_ok=True)


def summary() -> dict:
    return {
        "port": PORT,
        "host": HOST,
        "render": f"{RENDER_WIDTH}x{RENDER_HEIGHT} @ {RENDER_SAMPLES} Samples ({RENDER_MATERIAL})",
        "api_key_set": bool(ROBLOX_API_KEY),
        "auto_update": AUTO_UPDATE,
        "test_mode": TEST_MODE,
        "public_url": PUBLIC_URL,
        "access_token_set": bool(BRS_ACCESS_TOKEN),
        "retention_days": JOB_RETENTION_DAYS,
    }
