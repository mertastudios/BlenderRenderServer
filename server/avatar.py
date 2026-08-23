"""Laedt den Roblox-Avatar eines Benutzernamens als 3D-Modell herunter.

Ablauf:
  1. Benutzername -> UserId        (users.roblox.com, oeffentlich)
  2. UserId -> 3D-Avatar-Manifest  (thumbnails.roblox.com /v1/users/avatar-3d)
     WICHTIG: Das ist KEIN Profilbild. Die "avatar-3d"-API liefert ein JSON
     mit OBJ-Hash, MTL-Hash, Textur-Hashes, Kamera und Bounding-Box.
     Seit 23. Maerz 2026 verlangt Roblox hierfuer einen Open-Cloud-API-Key
     mit Recht "thumbnails: Read" (sonst HTTP 401/403).
  3. OBJ / MTL / Texturen einzeln vom Roblox-CDN laden
     und in <job>/model/ speichern.
  4. Dem OBJ eine "mtllib avatar.mtl" Zeile voranstellen, damit Blender
     Material + Texturen automatisch verknuepft.
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
UA = {
    "User-Agent": "BlenderRenderServer/1.1 (+https://github.com/mertastudios/BlenderRenderServer)",
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
#  Open Cloud (optionaler Zusatzweg fuer einzelne Assets)
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
    """Gibt (Manifest-JSON, CDN-Host) zurueck. Pollt bis der 3D-Avatar fertig ist.

    Nutzt die offizielle avatar-3d-API (liefert OBJ/MTL/Texturen, kein Profilbild).
    """
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
    """Passt eine Roblox-MTL-Datei an, damit Blenders OBJ-Importer klarkommt.

    Zwei Probleme aus der Praxis (siehe Server-Log):
      * Roblox referenziert Texturen ohne Dateiendung ("map_Kd 30DAY-abc"),
        die Datei liegt aber als "30DAY-abc.png" im Modell-Ordner ->
        Blender meldet "Cannot load image file: ...30DAY-abc".
        Hier werden Referenzen auf die tatsaechlich gespeicherten Dateinamen
        gemappt (case-insensitive, auch ohne/mit Endung und mit Pfad davor).
      * "map_Ka" (ambient) unterstuetzt Blender nicht ->
        "MTL texture map type not supported". map_Ka wird deshalb zu map_Kd
        konvertiert, damit die Textur wenigstens geladen wird.
    Optionen (-s 1 1 1 usw.), Zahlen und Kommentarzeilen bleiben unangetastet.
    """
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
#  Oeffentliche Hauptfunktion
# ------------------------------------------------------------------------------

def download_avatar_model(username: str, dest_dir: Path) -> dict:
    """Laedt den Avatar als OBJ+MTL+Texturen nach dest_dir. Gibt Infos zurueck."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    session = _session()

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
    # GENAU EINE mtllib-Zeile auf avatar.mtl setzen. (Roblox-OBJs enthalten
    # teilweise "mtllib <hash>", diese Datei existiert im Ordner aber nicht.)
    body = [ln for ln in obj_text.splitlines() if not ln.strip().lower().startswith("mtllib")]
    obj_text = "mtllib avatar.mtl\n" + "\n".join(body) + "\n"
    (dest_dir / "avatar.obj").write_text(obj_text, encoding="utf-8")
    if mtl_data:
        # MTL erst anpassen (Endungen + map_Ka), damit Blender die Texturen
        # findet und keine Warnungen mehr produziert - siehe _rewrite_mtl.
        mtl_text = _rewrite_mtl(mtl_data.decode("utf-8", "replace"), texture_files)
        (dest_dir / "avatar.mtl").write_text(mtl_text, encoding="utf-8")

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
