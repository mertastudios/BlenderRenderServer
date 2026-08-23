"""Auto-Update: haelt die lokale Installation auf dem Stand des GitHub-Haupt-Branchs.

Funktionsweise:
  - Alle N Sekunden den neuesten Commit von GITHUB_REPO@GITHUB_BRANCH abfragen
    (GitHub-API, oeffentlich, kein Token noetig).
  - Ist der Commit neuer als der zuletzt installierte, wird der Quellcode als
    ZIP von GitHub geladen und ueber die lokale Kopie kopiert.
    Geschuetzte Ordner/Dateien (venv, tools, data, logs, .env, .update) bleiben
    unberuehrt.
  - Danach startet der Watchdog (run.py) den Server automatisch neu.
"""
from __future__ import annotations

import shutil
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

import requests

from . import config

STATE_DIR = config.ROOT / ".update"
STATE_FILE = STATE_DIR / "state.json"

# Diese Dinge werden beim Update NIE angefasst (lokale Installation & Daten)
PROTECTED = {
    ".env", ".git", ".update", "venv", "tools", "data", "logs",
    "__pycache__", ".arena", ".idea", ".vscode",
}


def _read_state() -> dict:
    try:
        import json

        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(sha: str) -> None:
    import json

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"sha": sha, "updated_at": datetime.now().isoformat(timespec="seconds")}, indent=2),
        encoding="utf-8",
    )


def remote_sha() -> str | None:
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/commits/{config.GITHUB_BRANCH}"
    try:
        resp = requests.get(url, timeout=15, headers={"Accept": "application/vnd.github+json"})
        if resp.ok:
            return resp.json().get("sha")
    except requests.RequestException:
        pass
    return None


def check_and_apply(force: bool = False) -> tuple[bool, str]:
    """Prueft auf neue Version; installiert sie bei Bedarf.

    Rueckgabe: (wurde_update_installiert, meldung)
    """
    sha = remote_sha()
    if not sha:
        return False, "GitHub nicht erreichbar (Update uebersprungen)."

    state = _read_state()
    if state.get("sha") == sha and not force:
        return False, f"Version aktuell ({sha[:7]})."

    if not state.get("sha") and not force:
        # Erster Start: Version nur registrieren, nichts herunterladen
        _write_state(sha)
        return False, f"Initial-Version registriert: {sha[:7]}."

    print(f"[Update] Neue Version auf GitHub gefunden ({sha[:7]}) - wird geladen ...")
    zip_url = (
        f"https://codeload.github.com/{config.GITHUB_REPO}/zip/refs/heads/{config.GITHUB_BRANCH}"
    )
    try:
        resp = requests.get(zip_url, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as exc:
        return False, f"Download fehlgeschlagen ({exc}). Naechster Versuch spaeter."

    with tempfile.TemporaryDirectory(prefix="brs_update_") as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "update.zip"
        zip_path.write_bytes(resp.content)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp_path)
        roots = [p for p in tmp_path.iterdir() if p.is_dir() and p.name != "__MACOSX"]
        if not roots:
            return False, "Update-ZIP enthielt keinen Projektordner."
        src = roots[0]

        changed = 0
        for item in sorted(src.iterdir()):
            if item.name in PROTECTED or item.name.startswith(".git"):
                continue
            dest = config.ROOT / item.name
            try:
                if dest.is_dir():
                    shutil.rmtree(dest)
                elif dest.exists() or dest.is_symlink():
                    dest.unlink()
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)
                changed += 1
            except Exception as exc:
                print(f"[Update] Warnung: {item.name} konnte nicht aktualisiert werden: {exc}")

    _write_state(sha)
    print(f"[Update] {changed} Objekte aktualisiert -> Version {sha[:7]} ({time.strftime('%H:%M:%S')})")
    return True, f"Update auf {sha[:7]} installiert. Server startet neu."
