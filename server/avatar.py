"""Laedt den Roblox-Avatar eines Benutzernamens als 3D-Modell herunter.

Ablauf (alles ohne API-Key moeglich, da oeffentliche Roblox-Endpunkte):
  1. Benutzername -> UserId        (users.roblox.com)
  2. UserId -> 3D-Thumbnail-Manifest (thumbnails.roblox.com, Format "avatar-3d")
     Das Manifest ist JSON und enthaelt: OBJ-Hash, MTL-Hash, Textur-Hashes,
     Kameradaten und die Bounding-Box.
  3. OBJ / MTL / Texturen einzeln vom Roblox-CDN (tX.rbxcdn.com) laden
     und in <job>/model/ speichern.
  4. Dem OBJ eine "mtllib avatar.mtl" Zeile voranstellen, damit Blender
     Material + Texturen automatisch verknuepft.

Falls in der .env ein ROBLOX_API_KEY (Open Cloud, "asset-legacy-delivery")
hinterlegt ist, wird dieser zusaetzlich als Ausweichpfad fuer einzelne
Asset-Downloads benutzt.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import requests

from . import config


class AvatarError(RuntimeError):
    """Fehler mit einer fuer Endanwender verstaendlichen Meldung."""


HTTP_TIMEOUT = 30
UA = {"User-Agent": "BlenderRenderServer/1.0 (+github.com/mertastudios/BlenderRenderServer)"}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(UA)
    return s


# ------------------------------------------------------------------------------
#  Open Cloud (optionaler API-Key)
# ------------------------------------------------------------------------------

def legacy_delivery_download(session: requests.Session, asset_id: str | int) -> bytes:
    """Laedt ein Roblox-Asset per Open-Cloud-API-Key herunter (Ausweichpfad).

    Benoetigt ROBLOX_API_KEY mit Lese-Recht auf "asset-legacy-delivery".
    """
    if not config.ROBLOX_API_KEY:
        raise AvatarError("Kein ROBLOX_API_KEY in der .env gesetzt.")
    headers = {"x-api-key": config.ROBLOX_API_KEY, **UA}
    endpoints = (
        f"https://apis.roblox.com/asset-legacy-delivery/v1/assets/{asset_id}",
        f"https://apis.roblox.com/asset-delivery-api/v1/assetId/{asset_id}",
    )
    last_error = ""
    for url in endpoints:
        try:
            resp = session.get(url, headers=headers, allow_redirects=False, timeout=HTTP_TIMEOUT)
            if resp.status_code in (301, 302, 303, 307, 308):
                target = resp.headers.get("Location", "")
                if target:
                    r2 = session.get(target, headers=UA, timeout=HTTP_TIMEOUT)
                    if r2.ok:
                        return r2.content
            if resp.ok:
                # Manche Antworten liefern JSON mit einer Download-URL
                try:
                    body = resp.json()
                    for key in ("downloadUrl", "location", "url"):
                        if isinstance(body, dict) and body.get(key):
                            r3 = session.get(body[key], headers=UA, timeout=HTTP_TIMEOUT)
                            if r3.ok:
                                return r3.content
                except ValueError:
                    pass
                if resp.content[:2] not in (b"{", b"["):
                    return resp.content
            last_error = f"HTTP {resp.status_code} von {url}"
        except requests.RequestException as exc:
            last_error = str(exc)
    raise AvatarError(
        f"Open-Cloud-Download fuer Asset {asset_id} fehlgeschlagen ({last_error}). "
        "Tipp: API-Key und Berechtigung 'asset-legacy-delivery: Read' pruefen."
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
#  Schritt 2: 3D-Manifest holen
# ------------------------------------------------------------------------------

def fetch_3d_manifest(session: requests.Session, user_id: int) -> tuple[dict, str]:
    """Gibt (Manifest-JSON, CDN-Host) zurueck. Pollt bis der Thumbnail fertig ist."""
    url = f"https://thumbnails.roblox.com/v1/users/avatar-3d?userIds={user_id}"
    last_state = ""
    for attempt in range(40):
        try:
            resp = session.get(url, timeout=HTTP_TIMEOUT)
        except requests.RequestException as exc:
            raise AvatarError(f"Keine Verbindung zu thumbnails.roblox.com: {exc}") from exc
        if not resp.ok:
            raise AvatarError(f"Thumbnail-API antwortete mit HTTP {resp.status_code}.")
        entries = (resp.json() or {}).get("data") or []
        if not entries:
            raise AvatarError("Thumbnail-API lieferte keine Daten fuer diesen Benutzer.")
        entry = entries[0]
        state = entry.get("state", "")
        if state == "Completed" and entry.get("imageUrl"):
            image_url = entry["imageUrl"]
            host = re.sub(r"^https?://", "", image_url).split("/")[0]
            # Die imageUrl verweist auf das JSON-Manifest
            manifest_resp = session.get(image_url, timeout=HTTP_TIMEOUT)
            if not manifest_resp.ok:
                raise AvatarError(f"Manifest-Download fehlgeschlagen (HTTP {manifest_resp.status_code}).")
            try:
                manifest = manifest_resp.json()
            except ValueError as exc:
                raise AvatarError("3D-Manifest war kein gueltiges JSON.") from exc
            if not manifest.get("obj"):
                raise AvatarError("3D-Manifest enthaelt kein OBJ (Avatar evtl. nicht als 3D verfuegbar).")
            return manifest, host
        if state == "Blocked":
            raise AvatarError(
                "Roblox hat den 3D-Thumbnail fuer diesen Avatar blockiert. "
                "Versuche einen anderen Benutzernamen."
            )
        if state != last_state:
            last_state = state
        time.sleep(1.0 + attempt * 0.1)
    raise AvatarError("3D-Thumbnail wurde nicht rechtzeitig fertig (Timeout nach ~60 s).")


# ------------------------------------------------------------------------------
#  Schritt 3: Dateien vom CDN laden
# ------------------------------------------------------------------------------

def _download_cdn(session: requests.Session, host: str, name: str) -> bytes:
    """Laedt eine Datei (per Hash-Namen) vom Roblox-CDN."""
    name = name.strip().strip("/")
    candidates = [f"https://{host}/{name}"]
    if "." not in name.rsplit("/", 1)[-1]:
        candidates.append(f"https://{host}/{name}.png")
    last = ""
    for url in candidates:
        try:
            resp = session.get(url, timeout=HTTP_TIMEOUT)
        except requests.RequestException as exc:
            last = str(exc)
            continue
        if resp.ok and resp.content:
            return resp.content
        last = f"HTTP {resp.status_code}"
    raise AvatarError(f"CDN-Download fehlgeschlagen ({name[:40]}... {last}).")


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
                if token.startswith("-"):  # Optionen wie -s 1 1 1 ueberspringen
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


# ------------------------------------------------------------------------------
#  Oeffentliche Hauptfunktion
# ------------------------------------------------------------------------------

def download_avatar_model(username: str, dest_dir: Path) -> dict:
    """Laedt den Avatar als OBJ+MTL+Texturen nach dest_dir. Gibt Infos zurueck."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    session = _session()

    user_id = resolve_user_id(session, username)
    print(f"[Avatar] Benutzer '{username}' hat die UserId {user_id}")

    manifest, host = fetch_3d_manifest(session, user_id)
    print(f"[Avatar] 3D-Manifest erhalten (CDN: {host})")

    textures = list(manifest.get("textures") or [])

    # OBJ laden (ohne mtllib-Zeile -> wir ergaenzen sie)
    obj_data = _download_cdn(session, host, manifest["obj"])
    # MTL laden
    mtl_name = manifest.get("mtl") or ""
    mtl_data = b""
    if mtl_name:
        try:
            mtl_data = _download_cdn(session, host, mtl_name)
        except AvatarError as exc:
            print(f"[Avatar] Warnung: MTL nicht ladbar ({exc})")

    # In MTL referenzierte Texturen mit den Texturen aus dem Manifest vereinen
    refs = _mtl_texture_refs(mtl_data.decode("utf-8", "replace")) if mtl_data else []
    for tex in textures:
        base = str(tex).strip("/").rsplit("/", 1)[-1]
        if base and base.lower() not in {r.lower() for r in refs}:
            refs.append(base)

    # Texturen herunterladen und exakt unter dem Namen speichern, den die MTL nennt
    texture_files: list[str] = []
    for ref in refs:
        base = ref if "." in ref else f"{ref}.png"
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

    # OBJ speichern, inkl. mtllib-Verweis auf avatar.mtl
    obj_text = obj_data.decode("utf-8", "replace")
    if "mtllib" not in obj_text:
        obj_text = "mtllib avatar.mtl\n" + obj_text
    (dest_dir / "avatar.obj").write_text(obj_text, encoding="utf-8")
    if mtl_data:
        (dest_dir / "avatar.mtl").write_bytes(mtl_data)

    return {
        "user_id": user_id,
        "username": username,
        "obj_bytes": len(obj_data),
        "textures": texture_files,
        "camera": manifest.get("camera"),
        "aabb": manifest.get("aabb"),
    }


# ------------------------------------------------------------------------------
#  Test-Figur (fuer BRS_TEST_MODE / Fehlersuche ohne Roblox-Server)
# ------------------------------------------------------------------------------

def _box(name: str, cx: float, cy: float, cz: float, sx: float, sy: float, sz: float,
         vertex_offset: int = 0) -> str:
    """Erzeugt einen OBJ-Quader (Y-hoch, wie Roblox-Koordinaten).

    vertex_offset: Index des ersten Vertex (OBJ-Indizes sind dateiweit!).
    """
    x0, x1 = cx - sx / 2, cx + sx / 2
    y0, y1 = cy - sy / 2, cy + sy / 2
    z0, z1 = cz - sz / 2, cz + sz / 2
    v = [
        (x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1),
        (x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1),
    ]
    faces = [
        (1, 2, 3, 4), (5, 8, 7, 6), (1, 5, 6, 2),
        (2, 6, 7, 3), (3, 7, 8, 4), (4, 8, 5, 1),
    ]
    lines = [f"o {name}"]
    lines += [f"v {x:.4f} {y:.4f} {z:.4f}" for x, y, z in v]
    lines += ["vt 0 0", "vt 1 0", "vt 1 1", "vt 0 1"]
    lines += [f"f {' '.join(str(i + vertex_offset) for i in f_)}" for f_ in faces]
    return "\n".join(lines) + "\n"


def make_test_model(dest_dir: Path) -> dict:
    """Blocky-Testavatar (R6-aehnlich) inklusive Textur, ganz offline."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    offset = 0
    for args in [
        ("Head", 0, 5.5, 0, 1.2, 1.2, 1.2),
        ("Torso", 0, 4.0, 0, 2.0, 2.0, 1.0),
        ("ArmL", -1.35, 4.0, 0, 0.7, 2.0, 0.7),
        ("ArmR", 1.35, 4.0, 0, 0.7, 2.0, 0.7),
        ("LegL", -0.55, 2.0, 0, 0.85, 2.0, 0.85),
        ("LegR", 0.55, 2.0, 0, 0.85, 2.0, 0.85),
    ]:
        parts.append(_box(*args, vertex_offset=offset))
        offset += 8
    obj = "mtllib avatar.mtl\n" + "\n".join(parts)
    (dest_dir / "avatar.obj").write_text(obj, encoding="utf-8")
    (dest_dir / "avatar.mtl").write_text(
        "newmtl AvatarTex\n"
        "Ka 1 1 1\nKd 1 1 1\nKs 0.1 0.1 0.1\n"
        "d 1.0\nillum 2\nmap_Kd texture.png\n",
        encoding="utf-8",
    )
    try:
        from PIL import Image

        img = Image.new("RGBA", (256, 256))
        for y in range(256):
            for x in range(256):
                img.putpixel(
                    (x, y),
                    (
                        int(60 + 150 * x / 255),
                        int(120 + 90 * y / 255),
                        240,
                        255,
                    ),
                )
        img.save(dest_dir / "texture.png")
    except ImportError:
        pass
    print("[Avatar] Test-Modell (offline) erstellt")
    return {"user_id": 0, "username": "TEST-MODE", "textures": ["texture.png"]}
