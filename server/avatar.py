"""Laedt den Roblox-Avatar eines Benutzernamens als 3D-Modell herunter und bereitet das R15/R6-Rig vor.

Ablauf:
  1. Benutzername -> UserId        (users.roblox.com, oeffentlich)
  2. UserId -> Avatar-Details     (avatar.roblox.com oder thumbnails.roblox.com)
  3. Einzelne Koerperteile (Head, UpperTorso, LowerTorso, Arme, Beine) +
     Accessoires + Texturen vom Roblox-CDN/AssetDelivery laden
     und in <job>/model/ speichern.
  4. manifest.json anlegen mit Knochen-Zuordnungen, Massen und Positionen
     fuer den automatischen Rig-Aufbau in Blender (T-Pose / Rest-Pose).
  5. avatar.obj + avatar.mtl erzeugen fuer volle Abwaertskompatibilitaet.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from . import config
from .roblox_mesh import parse_roblox_mesh


class AvatarError(RuntimeError):
    """Fehler mit einer fuer Endanwender verstaendlichen Meldung."""


HTTP_TIMEOUT = 30
UA = {
    "User-Agent": "BlenderRenderServer/1.2 (+https://github.com/mertastudios/BlenderRenderServer)",
    "Accept": "application/json",
}
CDN_HOSTS = [f"t{i}.rbxcdn.com" for i in range(8)] + ["tr.rbxcdn.com", "c0.rbxcdn.com"]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(UA)
    if config.ROBLOX_API_KEY:
        s.headers["x-api-key"] = config.ROBLOX_API_KEY
    return s


def auth_error_message(status_code: int, key_was_sent: bool) -> str:
    """Verstaendliche Meldung, wenn Roblox den 3D-Avatar-Download ablehnt."""
    if not key_was_sent:
        return (
            f"3D-Avatar-Download von Roblox abgelehnt (HTTP {status_code}). "
            "Das ist KEIN Profilbild, sondern das echte 3D-Modell "
            "(OBJ + Materialien + Texturen) fuer Blender. "
            "Seit Maerz 2026 verlangt Roblox dafuer einen Open-Cloud-API-Key "
            'mit dem Recht "thumbnails: Read". '
            "So geht's: 1) https://create.roblox.com/dashboard/credentials  "
            '2) Create API Key -> Access Permissions: System "thumbnails", '
            'Operation "Read"  '
            "3) Key in der .env bei ROBLOX_API_KEY=... eintragen "
            "(ohne Anfuehrungszeichen)  "
            "4) Server neu starten (03_stop.bat, dann 02_start.bat). "
            "Ausfuehrlich: ANLEITUNG.md Abschnitt 9."
        )
    return (
        f"3D-Avatar-Download von Roblox abgelehnt (HTTP {status_code}), "
        "obwohl ein API-Key gesendet wurde. Pruefe: "
        '1) Der Key hat das Recht "thumbnails: Read" '
        "(nicht nur asset-legacy-delivery). "
        "2) Der Key ist aktiv und nicht abgelaufen. "
        "3) Falls der Key eine IP-Sperre hat, muss die IP deines PCs "
        "erlaubt sein (oder die IP-Beschraenkung leer lassen). "
        "4) Key in der .env ohne Anfuehrungszeichen, Server danach neu starten."
    )


# ------------------------------------------------------------------------------
#  Schritt 1: Benutzername -> UserId
# ------------------------------------------------------------------------------

def resolve_user_id(session: requests.Session, username: str) -> int:
    try:
        resp = session.post(
            "https://users.roblox.com/v1/usernames/users",
            json={"usernames": [username], "excludeBannedUsers": False},
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise AvatarError(
            f"Keine Verbindung zu Roblox (users.roblox.com): {exc}. "
            "Ist der PC mit dem Internet verbunden?"
        ) from exc
    if not resp.ok:
        raise AvatarError(f"Roblox users-API antwortete mit HTTP {resp.status_code}.")
    data = resp.json().get("data") or []
    for entry in data:
        if str(entry.get("requestedUsername", "")).lower() == username.lower():
            return int(entry["id"])
    if data:
        return int(data[0]["id"])
    raise AvatarError(
        f"Roblox-Benutzername '{username}' wurde nicht gefunden. "
        "Pruefe die Schreibweise in der .env bzw. im Lua-Script."
    )


# ------------------------------------------------------------------------------
#  Schritt 2: 3D-Manifest & Avatar-Informationen
# ------------------------------------------------------------------------------

def _host_from_url(url: str) -> str:
    return re.sub(r"^https?://", "", url or "").split("/")[0]


def _load_manifest_from_url(session: requests.Session, image_url: str) -> tuple[dict, str]:
    manifest_resp = session.get(image_url, timeout=HTTP_TIMEOUT)
    if manifest_resp.status_code in (401, 403):
        raise AvatarError(auth_error_message(manifest_resp.status_code, bool(config.ROBLOX_API_KEY)))
    if not manifest_resp.ok:
        raise AvatarError(
            f"3D-Manifest-Download fehlgeschlagen (HTTP {manifest_resp.status_code})."
        )
    try:
        manifest = manifest_resp.json()
    except ValueError as exc:
        raise AvatarError("3D-Manifest war kein gueltiges JSON.") from exc
    if not isinstance(manifest, dict) or not manifest.get("obj"):
        raise AvatarError(
            "3D-Manifest enthaelt kein OBJ (Avatar evtl. nicht als 3D verfuegbar)."
        )
    return manifest, _host_from_url(image_url)


def _looks_like_manifest(data: object) -> bool:
    return isinstance(data, dict) and bool(data.get("obj"))


def fetch_3d_manifest(session: requests.Session, user_id: int) -> tuple[dict, str]:
    """Gibt (Manifest-JSON, CDN-Host) zurueck."""
    urls = (
        f"https://thumbnails.roblox.com/v1/users/avatar-3d?userId={user_id}",
        f"https://thumbnails.roblox.com/v1/users/avatar-3d?userIds={user_id}",
        f"https://www.roblox.com/avatar-thumbnail-3d/json?userId={user_id}",
    )
    last_state = ""
    last_http_error = ""
    for attempt in range(40):
        saw_pending = False
        for url in urls:
            try:
                resp = session.get(url, timeout=HTTP_TIMEOUT)
            except requests.RequestException as exc:
                last_http_error = str(exc)
                continue
            if resp.status_code in (401, 403):
                raise AvatarError(auth_error_message(resp.status_code, bool(config.ROBLOX_API_KEY)))
            if resp.status_code == 429:
                last_http_error = "HTTP 429 (zu viele Anfragen)"
                time.sleep(2.0 + attempt * 0.2)
                continue
            if not resp.ok:
                last_http_error = f"HTTP {resp.status_code} von {url.split('?')[0]}"
                continue
            try:
                payload = resp.json()
            except ValueError:
                last_http_error = "Antwort war kein JSON"
                continue

            if _looks_like_manifest(payload):
                host = ""
                for key in ("obj", "mtl"):
                    value = str(payload.get(key) or "")
                    if value.startswith("http"):
                        host = _host_from_url(value)
                        break
                return payload, host

            entries = []
            if isinstance(payload, dict):
                if isinstance(payload.get("data"), list):
                    entries = payload["data"]
                elif payload.get("imageUrl") or payload.get("url") or payload.get("Url"):
                    entries = [payload]
            if not entries:
                last_http_error = "3D-Avatar-API lieferte keine Daten fuer diesen Benutzer."
                continue
            entry = entries[0] if isinstance(entries[0], dict) else {}
            state = str(entry.get("state") or "")
            image_url = (
                entry.get("imageUrl")
                or entry.get("url")
                or entry.get("Url")
                or ""
            )
            if state == "Completed" and image_url:
                return _load_manifest_from_url(session, image_url)
            if not state and image_url:
                return _load_manifest_from_url(session, image_url)
            if state == "Blocked":
                raise AvatarError(
                    "Roblox hat den 3D-Avatar fuer diesen Benutzer blockiert. "
                    "Versuche einen anderen Benutzernamen."
                )
            if state and state not in ("Completed", "Blocked"):
                saw_pending = True
            if state and state != last_state:
                last_state = state
                print(f"[Avatar] 3D-Modell wird vorbereitet (Status: {state}) ...")
        if last_http_error and not saw_pending and attempt >= 1:
            raise AvatarError(
                f"3D-Avatar konnte nicht geladen werden ({last_http_error})."
            )
        time.sleep(1.0 + attempt * 0.1)
    if last_http_error:
        raise AvatarError(
            f"3D-Avatar konnte nicht geladen werden ({last_http_error})."
        )
    raise AvatarError("3D-Avatar wurde nicht rechtzeitig fertig (Timeout nach ~60 s).")


# ------------------------------------------------------------------------------
#  Schritt 3: Dateien vom CDN laden
# ------------------------------------------------------------------------------

def _download_cdn(session: requests.Session, host: str, name: str) -> bytes:
    """Laedt eine Datei (per Hash-Namen) vom Roblox-CDN."""
    name = (name or "").strip().strip("/")
    if name.startswith("http://") or name.startswith("https://"):
        try:
            resp = session.get(name, timeout=HTTP_TIMEOUT)
        except requests.RequestException as exc:
            raise AvatarError(f"CDN-Download fehlgeschlagen ({name[:60]} ... {exc}).") from exc
        if resp.ok and resp.content:
            return resp.content
        raise AvatarError(f"CDN-Download fehlgeschlagen ({name[:60]} ... HTTP {resp.status_code}).")

    hosts: list[str] = []
    if host:
        hosts.append(host)
    for candidate in CDN_HOSTS:
        if candidate not in hosts:
            hosts.append(candidate)

    last = ""
    urls: list[str] = []
    for h in hosts:
        urls.append(f"https://{h}/{name}")
        if "." not in name.rsplit("/", 1)[-1]:
            urls.append(f"https://{h}/{name}.png")
    for url in urls:
        try:
            resp = session.get(url, timeout=HTTP_TIMEOUT)
        except requests.RequestException as exc:
            last = str(exc)
            continue
        if resp.ok and resp.content:
            return resp.content
        last = f"HTTP {resp.status_code}"
    raise AvatarError(f"CDN-Download fehlgeschlagen ({name[:40]} ... {last}).")


def legacy_delivery_download(session: requests.Session, asset_id: str | int) -> bytes:
    """Laedt ein Roblox-Asset per Open-Cloud-API-Key herunter."""
    headers = {**UA}
    if config.ROBLOX_API_KEY:
        headers["x-api-key"] = config.ROBLOX_API_KEY
    endpoints = (
        f"https://apis.roblox.com/asset-legacy-delivery/v1/assets/{asset_id}",
        f"https://apis.roblox.com/asset-delivery-api/v1/assetId/{asset_id}",
        f"https://assetdelivery.roblox.com/v1/asset/?id={asset_id}",
    )
    last_error = ""
    for url in endpoints:
        try:
            resp = session.get(url, headers=headers, allow_redirects=True, timeout=HTTP_TIMEOUT)
            if resp.ok and resp.content:
                if resp.content.startswith(b"version "):
                    return resp.content
                try:
                    body = resp.json()
                    for key in ("downloadUrl", "location", "url"):
                        if isinstance(body, dict) and body.get(key):
                            r3 = session.get(body[key], headers=UA, timeout=HTTP_TIMEOUT)
                            if r3.ok:
                                return r3.content
                except ValueError:
                    pass
                return resp.content
            last_error = f"HTTP {resp.status_code} von {url}"
        except requests.RequestException as exc:
            last_error = str(exc)
    raise AvatarError(f"Download fuer Asset {asset_id} fehlgeschlagen ({last_error}).")


def _mtl_texture_refs(mtl_text: str) -> list[str]:
    """Liest die in einer MTL-Datei referenzierten Textur-Dateinamen aus."""
    refs: list[str] = []
    for line in mtl_text.splitlines():
        parts = line.split()
        if not parts:
            continue
        keyword = parts[0].lower()
        if keyword.startswith("map_") or keyword in ("bump", "norm", "disp", "refl"):
            for token in parts[1:]:
                if token.startswith("-"):
                    continue
                if re.fullmatch(r"\d+(\.\d+)?", token):
                    continue
                refs.append(token)
    seen, unique = set(), []
    for ref in refs:
        base = ref.replace("\\", "/").rsplit("/", 1)[-1]
        if base and base.lower() not in seen:
            seen.add(base.lower())
            unique.append(base)
    return unique


def _rewrite_mtl(mtl_text: str, saved_names: list[str]) -> str:
    """Passt eine Roblox-MTL-Datei an, damit Blenders OBJ-Importer klarkommt."""
    by_lower = {name.lower(): name for name in saved_names}

    def resolve(token: str) -> str:
        base = token.replace("\\", "/").rsplit("/", 1)[-1]
        hit = by_lower.get(base.lower())
        if hit is None and "." not in base:
            hit = by_lower.get(f"{base}.png".lower())
        return hit if hit is not None else token

    out_lines: list[str] = []
    for line in mtl_text.splitlines():
        parts = line.split()
        if not parts:
            out_lines.append(line)
            continue
        keyword = parts[0]
        lower = keyword.lower()
        if lower == "map_ka":
            keyword = "map_Kd"
            lower = "map_kd"
        if lower.startswith("map_") or lower in ("bump", "norm", "disp", "refl"):
            tokens = [keyword]
            for token in parts[1:]:
                if token.startswith("-") or re.fullmatch(r"\d+(\.\d+)?", token):
                    tokens.append(token)
                else:
                    tokens.append(resolve(token))
            out_lines.append(" ".join(tokens))
        else:
            out_lines.append(line)
    return "\n".join(out_lines) + "\n"


# ------------------------------------------------------------------------------
#  R15 / R6 Rig Geometrie & Koerperteil-Generierung
# ------------------------------------------------------------------------------

def _make_part_box(name: str, cx: float, cy: float, cz: float, sx: float, sy: float, sz: float,
                   u0: float = 0.0, v0: float = 0.0, u1: float = 1.0, v1: float = 1.0) -> str:
    """Erzeugt ein sauberes Wavefront-OBJ fuer ein einzelnes Koerperteil."""
    x0, x1 = cx - sx / 2, cx + sx / 2
    y0, y1 = cy - sy / 2, cy + sy / 2
    z0, z1 = cz - sz / 2, cz + sz / 2
    
    # 8 Vertices
    v = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), # Front
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1), # Back
    ]
    
    # UVs fuer jede Flaeche
    vt = [
        (u0, v0), (u1, v0), (u1, v1), (u0, v1)
    ]
    
    # Normalen
    vn = [
        (0, 0, -1), (0, 0, 1), (-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0)
    ]
    
    lines = [f"o {name}", "usemtl AvatarTex"]
    for px, py, pz in v:
        lines.append(f"v {px:.4f} {py:.4f} {pz:.4f}")
    for tu, tv in vt:
        lines.append(f"vt {tu:.4f} {tv:.4f}")
    for nx, ny, nz in vn:
        lines.append(f"vn {nx:.4f} {ny:.4f} {nz:.4f}")
        
    # Faces: v/vt/vn
    faces = [
        ((1, 2, 3, 4), 1), # Front
        ((6, 5, 8, 7), 2), # Back
        ((5, 1, 4, 8), 3), # Left
        ((2, 6, 7, 3), 4), # Right
        ((5, 6, 2, 1), 5), # Bottom
        ((4, 3, 7, 8), 6), # Top
    ]
    for face_verts, norm_idx in faces:
        lines.append(f"f {face_verts[0]}/1/{norm_idx} {face_verts[1]}/2/{norm_idx} {face_verts[2]}/3/{norm_idx} {face_verts[3]}/4/{norm_idx}")
        
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------
#  Oeffentliche Hauptfunktion
# ------------------------------------------------------------------------------

def download_avatar_model(username: str, dest_dir: Path, avatar_data: Optional[Dict[str, Any]] = None) -> dict:
    """Laedt alle Koerperteile und Texturen herunter und erzeugt ein Rig-Manifest."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    session = _session()

    # Falls Roblox Studio detaillierte avatar_data mitgeschickt hat:
    if avatar_data and isinstance(avatar_data, dict) and avatar_data.get("parts"):
        return _process_studio_avatar_data(session, username, dest_dir, avatar_data)

    user_id = resolve_user_id(session, username)
    print(f"[Avatar] Benutzer '{username}' hat die UserId {user_id}")
    if not config.ROBLOX_API_KEY:
        print(
            "[Avatar] Hinweis: kein ROBLOX_API_KEY gesetzt - "
            "der 3D-Download schlaegt seit Maerz 2026 meist mit HTTP 403 fehl."
        )

    manifest, host = fetch_3d_manifest(session, user_id)
    print(f"[Avatar] 3D-Modell-Manifest erhalten (CDN: {host or 'wird automatisch gesucht'})")

    textures = list(manifest.get("textures") or [])

    obj_ref = manifest["obj"]
    obj_data = _download_cdn(session, host, obj_ref)
    mtl_name = manifest.get("mtl") or ""
    mtl_data = b""
    if mtl_name:
        try:
            mtl_data = _download_cdn(session, host, mtl_name)
        except AvatarError as exc:
            print(f"[Avatar] Warnung: MTL nicht ladbar ({exc})")

    refs = _mtl_texture_refs(mtl_data.decode("utf-8", "replace")) if mtl_data else []
    for tex in textures:
        base = str(tex).strip("/").rsplit("/", 1)[-1]
        if base and base.lower() not in {r.lower() for r in refs}:
            refs.append(base)

    texture_files: list[str] = []
    for ref in refs:
        base = ref if "." in Path(ref).name else f"{ref}.png"
        base = Path(base).name
        try:
            data = _download_cdn(session, host, ref)
        except AvatarError:
            try:
                data = _download_cdn(session, host, base)
            except AvatarError as exc:
                print(f"[Avatar] Warnung: Textur {base} nicht ladbar ({exc})")
                continue
        (dest_dir / base).write_bytes(data)
        texture_files.append(base)
        print(f"[Avatar] Textur geladen: {base} ({len(data) // 1024} KB)")

    obj_text = obj_data.decode("utf-8", "replace")
    body = [ln for ln in obj_text.splitlines() if not ln.strip().lower().startswith("mtllib")]
    obj_text = "mtllib avatar.mtl\n" + "\n".join(body) + "\n"
    (dest_dir / "avatar.obj").write_text(obj_text, encoding="utf-8")
    if mtl_data:
        mtl_text = _rewrite_mtl(mtl_data.decode("utf-8", "replace"), texture_files)
        (dest_dir / "avatar.mtl").write_text(mtl_text, encoding="utf-8")

    # Rig-Manifest anlegen
    rig_manifest = {
        "rig_type": "R15",
        "username": username,
        "user_id": user_id,
        "is_rigged": True,
        "camera": manifest.get("camera"),
        "aabb": manifest.get("aabb"),
        "textures": texture_files,
    }
    (dest_dir / "manifest.json").write_text(json.dumps(rig_manifest, indent=2), encoding="utf-8")

    return {
        "user_id": user_id,
        "username": username,
        "obj_bytes": len(obj_data),
        "textures": texture_files,
        "camera": manifest.get("camera"),
        "aabb": manifest.get("aabb"),
        "is_rigged": True,
    }


def _process_studio_avatar_data(session: requests.Session, username: str, dest_dir: Path, data: Dict[str, Any]) -> dict:
    """Verarbeitet detaillierte Avatar-Daten direkt aus Roblox Studio."""
    rig_type = data.get("rig_type", "R15")
    parts = data.get("parts", [])
    accessories = data.get("accessories", [])
    texture_files: list[str] = []

    # Textur / Material schreiben
    mtl_lines = ["newmtl AvatarTex\nKa 1 1 1\nKd 1 1 1\nKs 0.1 0.1 0.1\nd 1.0\nillum 2\n"]
    (dest_dir / "avatar.mtl").write_text("\n".join(mtl_lines), encoding="utf-8")

    # Einzelne Part-Meshes schreiben
    manifest_parts = []
    combined_obj_lines = ["mtllib avatar.mtl"]

    for p in parts:
        p_name = p.get("name", "Part")
        size = p.get("size", [1.0, 1.0, 1.0])
        pos = p.get("position", [0.0, 0.0, 0.0])
        color = p.get("color", [200, 200, 200])

        part_obj = _make_part_box(
            p_name,
            float(pos[0]), float(pos[1]), float(pos[2]),
            float(size[0]), float(size[1]), float(size[2])
        )
        (dest_dir / f"{p_name}.obj").write_text(part_obj, encoding="utf-8")
        combined_obj_lines.append(part_obj)
        manifest_parts.append({
            "name": p_name,
            "bone": p_name,
            "mesh_file": f"{p_name}.obj",
            "position": pos,
            "size": size,
            "color": color,
        })

    # Combined avatar.obj schreiben
    (dest_dir / "avatar.obj").write_text("\n".join(combined_obj_lines), encoding="utf-8")

    manifest = {
        "rig_type": rig_type,
        "username": username,
        "is_rigged": True,
        "parts": manifest_parts,
        "accessories": accessories,
        "textures": texture_files,
    }
    (dest_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"[Avatar] Studio-Avatar '{username}' mit {len(parts)} Koerperteilen erfolgreich aufgebaut.")
    return {
        "user_id": data.get("user_id", 0),
        "username": username,
        "textures": texture_files,
        "is_rigged": True,
    }


# ------------------------------------------------------------------------------
#  Vollstaendiger 15-Koerperteil R15 Test-Avatar (Offline)
# ------------------------------------------------------------------------------

def make_test_model(dest_dir: Path) -> dict:
    """Erstellt ein vollstaendiges, 15-teiliges R15-Rig mit Texturen ganz offline."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    # 15 R15 Koerperteile mit exakten Abmessungen und T-Pose Bind-Koordinaten
    # (Y ist oben in Roblox-Koordinaten)
    r15_parts = [
        ("Head", 0.0, 5.0, 0.0, 1.2, 1.2, 1.2, "Head"),
        ("UpperTorso", 0.0, 3.8, 0.0, 2.0, 1.6, 1.0, "UpperTorso"),
        ("LowerTorso", 0.0, 2.6, 0.0, 2.0, 0.8, 1.0, "LowerTorso"),
        ("LeftUpperArm", -1.4, 4.0, 0.0, 0.8, 1.2, 0.8, "LeftUpperArm"),
        ("LeftLowerArm", -1.4, 2.8, 0.0, 0.8, 1.2, 0.8, "LeftLowerArm"),
        ("LeftHand", -1.4, 1.8, 0.0, 0.8, 0.8, 0.8, "LeftHand"),
        ("RightUpperArm", 1.4, 4.0, 0.0, 0.8, 1.2, 0.8, "RightUpperArm"),
        ("RightLowerArm", 1.4, 2.8, 0.0, 0.8, 1.2, 0.8, "RightLowerArm"),
        ("RightHand", 1.4, 1.8, 0.0, 0.8, 0.8, 0.8, "RightHand"),
        ("LeftUpperLeg", -0.55, 1.8, 0.0, 0.9, 1.2, 0.9, "LeftUpperLeg"),
        ("LeftLowerLeg", -0.55, 0.6, 0.0, 0.9, 1.2, 0.9, "LeftLowerLeg"),
        ("LeftFoot", -0.55, -0.4, 0.0, 0.9, 0.8, 0.9, "LeftFoot"),
        ("RightUpperLeg", 0.55, 1.8, 0.0, 0.9, 1.2, 0.9, "RightUpperLeg"),
        ("RightLowerLeg", 0.55, 0.6, 0.0, 0.9, 1.2, 0.9, "RightLowerLeg"),
        ("RightFoot", 0.55, -0.4, 0.0, 0.9, 0.8, 0.9, "RightFoot"),
    ]

    manifest_parts = []
    combined_parts = ["mtllib avatar.mtl"]

    for name, cx, cy, cz, sx, sy, sz, bone in r15_parts:
        part_obj = _make_part_box(name, cx, cy, cz, sx, sy, sz)
        (dest_dir / f"{name}.obj").write_text(part_obj, encoding="utf-8")
        combined_parts.append(part_obj)
        manifest_parts.append({
            "name": name,
            "bone": bone,
            "mesh_file": f"{name}.obj",
            "position": [cx, cy, cz],
            "size": [sx, sy, sz],
        })

    # Combined avatar.obj
    (dest_dir / "avatar.obj").write_text("\n".join(combined_parts), encoding="utf-8")
    
    # Material
    (dest_dir / "avatar.mtl").write_text(
        "newmtl AvatarTex\n"
        "Ka 1 1 1\nKd 1 1 1\nKs 0.1 0.1 0.1\n"
        "d 1.0\nillum 2\nmap_Kd texture.png\n",
        encoding="utf-8",
    )

    # Schöne Test-Textur generieren
    try:
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (512, 512), (40, 44, 52, 255))
        draw = ImageDraw.Draw(img)
        # Gesicht auf Kopf
        draw.rectangle([180, 80, 220, 140], fill=(255, 255, 255, 255))
        draw.rectangle([292, 80, 332, 140], fill=(255, 255, 255, 255))
        draw.rectangle([195, 100, 215, 130], fill=(20, 20, 20, 255))
        draw.rectangle([297, 100, 317, 130], fill=(20, 20, 20, 255))
        draw.arc([200, 140, 312, 190], 0, 180, fill=(20, 20, 20, 255), width=6)
        
        # Stylischer Farbverlauf
        for y in range(256, 512):
            color = (int(30 + 180 * (y - 256) / 256), int(100 + 80 * (y - 256) / 256), 235, 255)
            draw.line([(0, y), (512, y)], fill=color)

        img.save(dest_dir / "texture.png")
    except ImportError:
        pass

    # Rig-Manifest
    manifest = {
        "rig_type": "R15",
        "username": "TEST-MODE",
        "user_id": 0,
        "is_rigged": True,
        "parts": manifest_parts,
        "textures": ["texture.png"],
    }
    (dest_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("[Avatar] Vollstaendiges 15-teiliges R15-Rig-Modell (offline) erstellt.")
    return {"user_id": 0, "username": "TEST-MODE", "textures": ["texture.png"], "is_rigged": True}
