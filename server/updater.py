"""Auto-Update: haelt die lokale Installation auf dem Stand des GitHub-Haupt-Branchs.

Funktionsweise:
  - Commit-Hash von GITHUB_REPO@GITHUB_BRANCH abfragen (API, Atom-Feed oder Git).
  - Ist der Commit neuer als der zuletzt installierte, wird der Quellcode als
    ZIP von GitHub geladen und ueber die lokale Kopie kopiert.
    Geschuetzte Ordner/Dateien (venv, tools, data, logs, .env, .update) bleiben
    unberuehrt.
  - Danach veranlasst der Server einen sauberen Selbst-Neustart.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import requests

from . import config

STATE_DIR = config.ROOT / ".update"
STATE_FILE = STATE_DIR / "state.json"

PROTECTED = {
    ".env", ".git", ".update", "venv", "tools", "data", "logs",
    "__pycache__", ".arena", ".idea", ".vscode",
}

UA = {
    "User-Agent": "BlenderRenderServer/1.2 (+https://github.com/mertastudios/BlenderRenderServer)",
    "Accept": "application/vnd.github+json",
}

_last_check_info = {
    "timestamp": 0.0,
    "current_sha": "",
    "remote_sha": "",
    "update_available": False,
    "message": "",
}


def _read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(sha: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"sha": sha, "updated_at": datetime.now().isoformat(timespec="seconds")}, indent=2),
        encoding="utf-8",
    )


def _short_exc(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return re.sub(r"\s+", " ", text)[:180]


def _sha_from_api() -> tuple[str | None, str | None]:
    url = f"https://api.github.com/repos/{config.GITHUB_REPO}/commits/{config.GITHUB_BRANCH}"
    try:
        resp = requests.get(url, timeout=15, headers=UA)
    except requests.RequestException as exc:
        return None, f"api.github.com nicht erreichbar ({_short_exc(exc)})"
    if resp.ok:
        sha = (resp.json() or {}).get("sha")
        if sha:
            return str(sha), None
        return None, "api.github.com lieferte keinen Commit-Hash."
    hint = ""
    if resp.status_code == 403:
        hint = " (oft Rate-Limit oder Firewall)"
    elif resp.status_code == 404:
        hint = f" (Repo {config.GITHUB_REPO} / Branch {config.GITHUB_BRANCH} nicht gefunden?)"
    return None, f"api.github.com HTTP {resp.status_code}{hint}"


def _sha_from_atom() -> tuple[str | None, str | None]:
    url = f"https://github.com/{config.GITHUB_REPO}/commits/{config.GITHUB_BRANCH}.atom"
    headers = {**UA, "Accept": "application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8"}
    try:
        resp = requests.get(url, timeout=15, headers=headers)
    except requests.RequestException as exc:
        return None, f"github.com Atom-Feed nicht erreichbar ({_short_exc(exc)})"
    if not resp.ok:
        return None, f"github.com Atom-Feed HTTP {resp.status_code}"
    match = re.search(
        r"commit/([0-9a-f]{40})|Grit::Commit/([0-9a-f]{40})",
        resp.text,
        re.IGNORECASE,
    )
    if not match:
        return None, "github.com Atom-Feed enthielt keinen Commit-Hash."
    return match.group(1) or match.group(2), None


def _sha_from_git() -> tuple[str | None, str | None]:
    git = shutil.which("git")
    if not git:
        return None, "git ist nicht installiert (Ausweichweg nicht verfuegbar)."
    remote = f"https://github.com/{config.GITHUB_REPO}.git"
    try:
        proc = subprocess.run(
            [git, "ls-remote", remote, f"refs/heads/{config.GITHUB_BRANCH}"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"git ls-remote fehlgeschlagen ({_short_exc(exc)})"
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = err[-1] if err else f"Exit {proc.returncode}"
        return None, f"git ls-remote: {detail[:160]}"
    line = (proc.stdout or "").strip().splitlines()
    if not line:
        return None, "git ls-remote lieferte keinen Hash."
    sha = line[0].split()[0].strip()
    if re.fullmatch(r"[0-9a-f]{7,40}", sha):
        return sha, None
    return None, "git ls-remote lieferte keinen gueltigen Hash."


def remote_sha() -> str | None:
    sha, _err = remote_sha_detailed()
    return sha


def remote_sha_detailed() -> tuple[str | None, str]:
    """Liefert (sha, statusmeldung). sha ist None, wenn nichts ging."""
    errors: list[str] = []
    for probe in (_sha_from_api, _sha_from_atom, _sha_from_git):
        sha, err = probe()
        if sha:
            return sha, ""
        if err:
            errors.append(err)
    if not errors:
        return None, "GitHub nicht erreichbar."
    return None, "GitHub nicht erreichbar: " + " | ".join(errors)


def last_error_advice(detail: str) -> str:
    """Kurzer Tipp, der an die Update-Meldung gehaengt werden kann."""
    lower = detail.lower()
    if "nicht erreichbar" in lower or "timed out" in lower or "timeout" in lower:
        return (
            "Rendern funktioniert trotzdem. Falls die Meldung bleibt: "
            "Firewall/Antivirus fuer python.exe + github.com erlauben "
            "oder AUTO_UPDATE=false in der .env setzen."
        )
    return "Rendern funktioniert trotzdem. Details: 09_verbindung_pruefen.bat"


def get_status() -> dict:
    """Liefert aktuellen Versions- und Update-Status."""
    state = _read_state()
    current_sha = state.get("sha", "")
    return {
        "current_version": current_sha[:7] if current_sha else config.version(),
        "current_sha": current_sha,
        "remote_version": _last_check_info["remote_sha"][:7] if _last_check_info["remote_sha"] else "unbekannt",
        "remote_sha": _last_check_info["remote_sha"],
        "update_available": _last_check_info["update_available"],
        "last_check": _last_check_info["timestamp"],
        "message": _last_check_info["message"],
    }


def check_and_apply(force: bool = False) -> tuple[bool, str]:
    """Prueft auf neue Version; installiert sie bei Bedarf.

    Rueckgabe: (wurde_update_installiert, meldung)
    """
    sha, err = remote_sha_detailed()
    state = _read_state()
    current_sha = state.get("sha", "")

    _last_check_info["timestamp"] = time.time()
    _last_check_info["current_sha"] = current_sha
    _last_check_info["remote_sha"] = sha or ""

    if not sha:
        msg = f"{err} (Update uebersprungen). {last_error_advice(err)}"
        _last_check_info["update_available"] = False
        _last_check_info["message"] = msg
        return False, msg

    if current_sha == sha and not force:
        _last_check_info["update_available"] = False
        _last_check_info["message"] = f"Version aktuell ({sha[:7]})."
        return False, f"Version aktuell ({sha[:7]})."

    if not current_sha and not force:
        _write_state(sha)
        _last_check_info["current_sha"] = sha
        _last_check_info["update_available"] = False
        _last_check_info["message"] = f"Initial-Version registriert: {sha[:7]}."
        return False, f"Initial-Version registriert: {sha[:7]}."

    _last_check_info["update_available"] = True
    print(f"[Update] Neue Version auf GitHub gefunden ({sha[:7]}) - wird heruntergeladen ...")
    zip_url = f"https://codeload.github.com/{config.GITHUB_REPO}/zip/refs/heads/{config.GITHUB_BRANCH}"
    try:
        resp = requests.get(zip_url, timeout=120, headers=UA)
        resp.raise_for_status()
    except requests.RequestException as exc:
        msg = f"Download fehlgeschlagen ({_short_exc(exc)}). Naechster Versuch spaeter."
        _last_check_info["message"] = msg
        return False, msg

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
    _last_check_info["current_sha"] = sha
    _last_check_info["update_available"] = False
    _last_check_info["message"] = f"Update auf {sha[:7]} erfolgreich installiert."
    print(f"[Update] {changed} Objekte aktualisiert -> Version {sha[:7]} ({time.strftime('%H:%M:%S')})")
    return True, f"Update auf {sha[:7]} installiert. Server startet jetzt neu."
