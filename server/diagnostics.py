"""Verbindungscheck: Roblox 3D-API, API-Key, GitHub, Blender, Tunnel."""
from __future__ import annotations

import sys
from typing import Any

import requests

from . import avatar, blender_runner, config, tunnel, updater

TIMEOUT = 12


def _ok(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def run_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    key_set = bool(config.ROBLOX_API_KEY)
    checks.append(
        _ok(
            "Roblox Open-Cloud-API-Key",
            key_set,
            "gesetzt" if key_set else (
                "FEHLT - seit Maerz 2026 noetig fuer den 3D-Avatar-Download "
                '(Recht "thumbnails: Read"). Siehe ANLEITUNG.md Abschnitt 9.'
            ),
        )
    )

    session = avatar._session()  # noqa: SLF001
    try:
        resp = session.post(
            "https://users.roblox.com/v1/usernames/users",
            json={"usernames": ["Roblox"], "excludeBannedUsers": False},
            timeout=TIMEOUT,
        )
        checks.append(
            _ok(
                "Roblox users-API",
                resp.ok,
                f"HTTP {resp.status_code}" if not resp.ok else "erreichbar (Namensaufloesung funktioniert)",
            )
        )
    except requests.RequestException as exc:
        checks.append(_ok("Roblox users-API", False, f"keine Verbindung: {exc}"))

    try:
        resp = session.get(
            "https://thumbnails.roblox.com/v1/users/avatar-3d?userId=1",
            timeout=TIMEOUT,
        )
        if resp.ok:
            detail = (
                "3D-Avatar-API erreichbar (liefert OBJ/MTL/Texturen, kein Profilbild)"
            )
            ok = True
        elif resp.status_code in (401, 403):
            ok = False
            detail = avatar.auth_error_message(resp.status_code, key_set)
        else:
            ok = False
            detail = f"HTTP {resp.status_code}"
        checks.append(_ok("Roblox 3D-Avatar-API (avatar-3d)", ok, detail))
    except requests.RequestException as exc:
        checks.append(_ok("Roblox 3D-Avatar-API (avatar-3d)", False, f"keine Verbindung: {exc}"))

    sha, err = updater.remote_sha_detailed()
    if sha:
        checks.append(_ok("GitHub (Auto-Update)", True, f"erreichbar, aktueller Stand {sha[:7]}"))
    else:
        checks.append(
            _ok(
                "GitHub (Auto-Update)",
                False,
                f"{err} - Rendern geht trotzdem. "
                "Firewall fuer github.com erlauben oder AUTO_UPDATE=false setzen.",
            )
        )

    blender = blender_runner.blender_available()
    checks.append(
        _ok(
            "Blender",
            blender,
            "gefunden" if blender else "NICHT gefunden - einmal 01_setup.bat ausfuehren",
        )
    )

    pub = tunnel.public_url()
    checks.append(
        _ok(
            "Oeffentliche HTTPS-Adresse",
            bool(pub),
            pub or (
                "keine - fuer Studio reicht localhost. "
                "Fuer ein veroeffentlichtes Spiel: 08_oeffentliche_adresse.bat starten."
            ),
        )
    )

    token = bool(config.BRS_ACCESS_TOKEN)
    checks.append(
        _ok(
            "Zugangstoken (BRS_ACCESS_TOKEN)",
            True,
            "gesetzt (Auftraege sind geschuetzt)" if token else (
                "nicht gesetzt (ok fuer localhost; bei oeffentlicher URL empfohlen)"
            ),
        )
    )
    return checks


def as_text(checks: list[dict[str, Any]] | None = None) -> str:
    checks = checks if checks is not None else run_checks()
    lines = [
        "",
        "=" * 66,
        "  BlenderRenderServer - Verbindungscheck",
        "=" * 66,
    ]
    for item in checks:
        icon = "OK " if item["ok"] else "FEHLER"
        lines.append(f"  [{icon}] {item['name']}")
        lines.append(f"         {item['detail']}")
        lines.append("")
    lines.append("Diese Pruefung kannst du jederzeit mit 09_verbindung_pruefen.bat wiederholen.")
    lines.append("=" * 66)
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    checks = run_checks()
    print(as_text(checks))
    # GitHub-Fehler allein soll den Check nicht "rot" machen
    critical = [c for c in checks if not c["ok"] and "GitHub" not in c["name"]
                and "Oeffentliche" not in c["name"] and "Zugangstoken" not in c["name"]]
    return 1 if critical else 0


if __name__ == "__main__":
    raise SystemExit(main())
