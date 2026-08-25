"""Der Render-Server (FastAPI).

Endpunkte (alle aus Roblox per HttpService und BindableFunction nutzbar):
  GET  /                          -> Status-Webseite mit Live-Vorschau & Warteschlange
  GET  /health                    -> {"status":"ok", "version": ..., "queue_length": ...}
  POST /jobs                      -> Neuen Auftrag anlegen (Einzel-Avatar oder ganze Szene)
  POST /jobs/create               -> Alias fuer /jobs
  GET  /jobs                      -> Uebersicht aller aktiven & wartenden Auftraege
  GET  /jobs/current              -> Status des aktuellen Auftrags
  GET  /jobs/{id}                 -> Detaillierter Status (not_found, queued, active, done, error)
  GET  /jobs/{id}/image/info      -> {width, height, bytes}
  GET  /jobs/{id}/image/rows?y=.. -> RGBA-Pixelzeilen (application/octet-stream)
  GET  /jobs/{id}/image/rgba      -> Vollstaendiger RGBA-Pixelpuffer
  GET  /jobs/{id}/image.png       -> Fertiges Bild als PNG (Browser/Vorschau)
  GET  /update/status             -> Update-Status
  POST /update                    -> Prueft auf Updates, installiert sie und startet neu
  POST /update/restart            -> Veranlasst einen sauberen Server-Neustart
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from PIL import Image
from pydantic import BaseModel, Field

from . import avatar, blender_runner, config, diagnostics, tunnel, updater

# Pfade, die ohne Token erreichbar bleiben
_OPEN_PATHS = {"/", "/health", "/diagnostics", "/favicon.ico", "/update/status", "/update"}


def _request_token(request: Request) -> str:
    header = (request.headers.get("x-brs-token") or "").strip()
    if header:
        return header
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.query_params.get("token") or "").strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    print("=" * 62, flush=True)
    print(f"  BlenderRenderServer ist ONLINE  (Version {config.version()})", flush=True)
    print(f"  Studio-Adresse : http://localhost:{config.PORT}", flush=True)
    pub = tunnel.public_url()
    if pub:
        print(f"  Oeffentliche URL: {pub}", flush=True)
    else:
        print("  Oeffentliche URL: (keine - fuer Live-Spiele 08_oeffentliche_adresse.bat)", flush=True)
    print(f"  Blender: {'gefunden' if blender_runner.blender_available() else 'NICHT gefunden!'}"
          "   |   Modus: " + ("TEST-MODUS" if config.TEST_MODE else "normal"), flush=True)
    print(f"  API-Key: {'gesetzt' if config.ROBLOX_API_KEY else 'FEHLT (3D-Avatare brauchen ihn!)'}", flush=True)
    print(f"  Sicherheit: {'Zugangstoken AKTIV' if config.BRS_ACCESS_TOKEN else 'Kein Token (offen)'}", flush=True)
    print(f"  Auftragsspeicher: Bilder werden {config.JOB_RETENTION_DAYS} Tage aufbewahrt", flush=True)
    print("=" * 62, flush=True)
    if not config.TEST_MODE and not config.ROBLOX_API_KEY:
        print("!" * 62, flush=True)
        print("  KEIN ROBLOX_API_KEY in der .env!", flush=True)
        print("  Seit Maerz 2026 blockiert Roblox den 3D-Avatar-Download", flush=True)
        print("  ohne Open-Cloud-Key (Recht: thumbnails -> Read).", flush=True)
        print("  Ohne Key kommt HTTP 401/403. Anleitung: ANLEITUNG.md §9", flush=True)
        print("!" * 62, flush=True)
    if config.PUBLIC_TUNNEL:
        try:
            tunnel.start_in_background()
            print("[Tunnel] Cloudflare-Tunnel wird im Hintergrund gestartet ...", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[Tunnel] Konnte nicht starten: {exc}", flush=True)
    if config.AUTO_UPDATE:
        threading.Thread(target=_update_loop, daemon=True, name="brs-updater").start()
    yield


app = FastAPI(title="BlenderRenderServer", version="1.3", lifespan=lifespan)


@app.middleware("http")
async def _protect_jobs(request: Request, call_next):
    expected = config.BRS_ACCESS_TOKEN
    if not expected:
        return await call_next(request)
    path = request.url.path
    if path in _OPEN_PATHS or path.startswith("/docs") or path.startswith("/openapi"):
        return await call_next(request)
    if _request_token(request) != expected:
        return JSONResponse(
            {
                "detail": (
                    "Ungueltiger oder fehlender Zugangstoken. "
                    "Im Lua-Skript RENDER_ACCESS_TOKEN auf denselben Wert "
                    "setzen wie BRS_ACCESS_TOKEN in der .env."
                )
            },
            status_code=401,
        )
    return await call_next(request)


class SceneAvatarSpec(BaseModel):
    username: str
    material_mode: Optional[str] = "GLAS"
    glass_strength: Optional[float] = 0.85
    heart_hands: Optional[bool] = False
    skin_color: Optional[List[int]] = None
    cframe: Optional[List[float]] = None
    parts: Optional[Dict[str, Any]] = None


class SceneObjectSpec(BaseModel):
    model_name: Optional[str] = "Part"
    name: Optional[str] = None
    material_mode: Optional[str] = "MATT"
    glass_strength: Optional[float] = 0.85
    size: Optional[List[float]] = None
    color: Optional[List[int]] = None
    cframe: Optional[List[float]] = None


class JobCreateRequest(BaseModel):
    username: Optional[str] = None
    avatars: Optional[List[Dict[str, Any]]] = None
    objects: Optional[List[Dict[str, Any]]] = None
    camera: Optional[Dict[str, Any]] = None
    material_mode: Optional[str] = "GLAS"
    glass_strength: Optional[float] = 0.85
    avatar_data: Optional[Dict[str, Any]] = None


def trigger_restart() -> None:
    """Startet den Server-Prozess sauber neu."""
    print("[Server] Neustart wird ausgeloest ...", flush=True)
    time.sleep(0.5)
    os._exit(77)


class JobManager:
    """Verwaltet eine unendliche FIFO-Warteschlange von Render-Auftraegen."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.jobs: dict[str, dict] = {}
        self.queue: list[str] = []
        self.current_id: str | None = None
        self._worker_thread: threading.Thread | None = None

    @staticmethod
    def _job_dir(job_id: str) -> Path:
        return config.ROOT / "data" / "jobs" / job_id

    def _cleanup_expired(self) -> None:
        """Loescht Auftraege und Bilder automatisch nach 7 Tagen (JOB_RETENTION_SECONDS)."""
        now = time.time()
        retention = config.JOB_RETENTION_SECONDS

        # 1. Im Speicher pruefen
        expired_ids = []
        for j_id, job in list(self.jobs.items()):
            if job.get("state") in ("done", "error") and (now - job.get("created_at", now)) > retention:
                expired_ids.append(j_id)

        for j_id in expired_ids:
            job = self.jobs.pop(j_id, None)
            if job and "dir" in job:
                shutil.rmtree(job["dir"], ignore_errors=True)
            print(f"[Cleanup] Auftrag {j_id} (aelter als {config.JOB_RETENTION_DAYS} Tage) geloescht.", flush=True)

        # 2. Auf Festplatte pruefen (fuer aeltere Ordner)
        jobs_dir = config.ROOT / "data" / "jobs"
        if jobs_dir.is_dir():
            for p in jobs_dir.iterdir():
                if p.is_dir() and p.name != "model":
                    try:
                        mtime = p.stat().st_mtime
                        if (now - mtime) > retention and p.name not in self.jobs:
                            shutil.rmtree(p, ignore_errors=True)
                            print(f"[Cleanup] Altes Job-Verzeichnis {p.name} geloescht.", flush=True)
                    except Exception:
                        pass

    def submit(self, payload: JobCreateRequest) -> dict:
        """Fuegt einen neuen Render-Auftrag zur unendlichen FIFO-Warteschlange hinzu."""
        with self.lock:
            self._cleanup_expired()
            job_id = uuid.uuid4().hex[:12]
            job_dir = self._job_dir(job_id)
            job_dir.mkdir(parents=True, exist_ok=True)

            # Szene vorbereiten
            avatars_list = []
            if payload.avatars:
                avatars_list = payload.avatars
            elif payload.username:
                avatars_list = [{
                    "username": payload.username.strip(),
                    "material_mode": payload.material_mode or "GLAS",
                    "glass_strength": payload.glass_strength or 0.85,
                    "heart_hands": False,
                }]

            objects_list = payload.objects or []
            camera_data = payload.camera or {
                "position": [0, 0, 0],
                "target": [0, 0, -10],
                "fov": 32.0,
            }

            main_username = avatars_list[0].get("username", "Szene") if avatars_list else (payload.username or "Szene")

            job = {
                "id": job_id,
                "username": main_username,
                "avatars": avatars_list,
                "objects": objects_list,
                "camera": camera_data,
                "avatar_data": payload.avatar_data,
                "state": "queued",
                "message": "Auftrag in Warteschlange",
                "progress": 0,
                "est_seconds_left": max(30, (len(self.queue) + 1) * 25),
                "error": None,
                "created_at": time.time(),
                "updated_at": time.time(),
                "dir": str(job_dir),
                "width": None,
                "height": None,
                "rgba_path": None,
            }

            self.jobs[job_id] = job
            self.queue.append(job_id)
            queue_pos = len(self.queue)
            
            print(f"[Queue] Neuer Auftrag {job_id} fuer '{main_username}' registriert. Position: {queue_pos}", flush=True)
            self._ensure_worker()

            return {
                "job_id": job_id,
                "state": "queued",
                "queue_position": queue_pos,
                "est_seconds_left": job["est_seconds_left"],
                "message": f"Auftrag eingereiht (Position {queue_pos})",
            }

    def _ensure_worker(self) -> None:
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="brs-worker")
            self._worker_thread.start()

    def _worker_loop(self) -> None:
        while True:
            job_to_run = None
            with self.lock:
                if not self.queue:
                    self.current_id = None
                    return
                next_id = self.queue.pop(0)
                job_to_run = self.jobs.get(next_id)
                self.current_id = next_id

            if job_to_run:
                self._run_job(job_to_run)

    def _run_job(self, job: dict) -> None:
        job_id = job["id"]
        job_dir = Path(job["dir"])
        render_start_time = 0.0

        try:
            print(f"[Job {job_id}] Start der Bearbeitung ...", flush=True)
            job["state"] = "active"
            job["message"] = "Render aktiv: 3D-Modelle werden vorbereitet ..."
            job["progress"] = 10
            job["est_seconds_left"] = 28
            job["updated_at"] = time.time()

            # 1. Avatare herunterladen ------------------------------------------
            avatars_spec = job.get("avatars") or []
            prepared_avatars = []

            for idx, av_spec in enumerate(avatars_spec):
                uname = av_spec.get("username", "").strip()
                if not uname:
                    continue
                av_dir = job_dir / f"avatar_{idx}_{uname}"
                av_dir.mkdir(parents=True, exist_ok=True)

                if config.TEST_MODE or uname.upper() == "TEST-MODE":
                    info = avatar.make_test_model(av_dir)
                else:
                    info = avatar.download_avatar_model(uname, av_dir, avatar_data=job.get("avatar_data"))

                spec_copy = dict(av_spec)
                spec_copy["model_dir"] = str(av_dir)
                prepared_avatars.append(spec_copy)

            # Szene-JSON fuer Blender schreiben
            scene_manifest = {
                "avatars": prepared_avatars,
                "objects": job.get("objects") or [],
                "camera": job.get("camera") or {},
            }
            (job_dir / "scene.json").write_text(json.dumps(scene_manifest, indent=2), encoding="utf-8")

            # 2. Blender Rendern ------------------------------------------------
            job["message"] = "Render aktiv: Blender Cycles berechnet Bild ..."
            job["progress"] = 25
            job["est_seconds_left"] = 20
            render_start_time = time.time()

            def progress_callback(stage: str, frac: float | None):
                f = max(0.0, min(1.0, frac if frac is not None else 0.0))
                if stage == "loading":
                    job["progress"] = min(28, int(15 + 13 * f))
                elif stage == "rendering":
                    job["progress"] = min(94, int(28 + 66 * f))
                    elapsed = time.time() - render_start_time
                    if f > 0.05:
                        total_est = elapsed / f
                        remaining = max(1, int(total_est - elapsed))
                        job["est_seconds_left"] = remaining + 2
                    else:
                        job["est_seconds_left"] = 18
                    job["message"] = f"Render aktiv: Cycles rendert {job['progress']}% (ca. {job['est_seconds_left']} s)"
                elif stage == "encoding":
                    job["progress"] = 96
                    job["est_seconds_left"] = 2
                job["updated_at"] = time.time()

            png_path = job_dir / "render.png"
            blender_runner.render(job_dir, png_path, progress=progress_callback)

            # 3. RGBA-Pixel vorbereiten (fuer EditableImage) ---------------------
            job["message"] = "Render aktiv: Bilddaten werden kodiert ..."
            job["progress"] = 96
            job["est_seconds_left"] = 2

            img = Image.open(png_path).convert("RGBA")
            if img.width > 1024 or img.height > 1024:
                img = img.resize((1024, 1024), Image.LANCZOS)

            rgba_path = job_dir / "render.rgba"
            rgba_path.write_bytes(img.tobytes())

            job["width"] = img.width
            job["height"] = img.height
            job["rgba_path"] = str(rgba_path)
            job["state"] = "done"
            job["message"] = f"Fertig gerendert ({img.width}x{img.height} Pixel)"
            job["progress"] = 100
            job["est_seconds_left"] = 0
            job["updated_at"] = time.time()
            print(f"[Job {job_id}] Erfolgreich abgeschlossen!", flush=True)

        except Exception as exc:  # noqa: BLE001
            print(f"[Job {job_id}] Fehler: {exc}", flush=True)
            job["state"] = "error"
            job["error"] = str(exc)
            job["message"] = f"Fehler: {exc}"
            job["est_seconds_left"] = 0
            job["updated_at"] = time.time()

    def get_status(self, job_id: str) -> dict:
        """Gibt den standardisierten Status fuer die Status-Abfrage zurueck."""
        self._cleanup_expired()
        job = self.jobs.get(job_id)
        if not job:
            return {
                "exists": False,
                "job_id": job_id,
                "state": "not_found",
                "queue_position": 0,
                "est_seconds_left": 0,
                "message": "Auftrag existiert nicht (oder ist abgelaufen)",
            }

        state = job.get("state", "queued")
        queue_pos = 0
        est_sec = job.get("est_seconds_left", 0)

        if state == "queued":
            try:
                queue_pos = self.queue.index(job_id) + 1
            except ValueError:
                queue_pos = 1
            # Schaetzung: Position * 25s
            est_sec = max(5, queue_pos * 25)

        elif state == "active":
            queue_pos = 0

        elif state == "done":
            queue_pos = 0
            est_sec = 0

        return {
            "exists": True,
            "job_id": job_id,
            "username": job.get("username", ""),
            "state": state,
            "queue_position": queue_pos,
            "est_seconds_left": est_sec,
            "progress": job.get("progress", 0),
            "message": job.get("message", state),
            "error": job.get("error"),
            "width": job.get("width"),
            "height": job.get("height"),
        }


MANAGER = JobManager()


# ------------------------------------------------------------------------------
#  Hintergrund-Update-Thread
# ------------------------------------------------------------------------------

def _update_loop() -> None:
    while True:
        time.sleep(config.AUTO_UPDATE_CHECK_SECONDS)
        if not config.AUTO_UPDATE:
            continue
        with MANAGER.lock:
            if MANAGER.current_id is not None or bool(MANAGER.queue):
                continue
        try:
            updated, msg = updater.check_and_apply()
            print(f"[Update] {msg}", flush=True)
            if updated:
                print("[Update] Neustart des Servers wird eingeleitet ...", flush=True)
                trigger_restart()
        except Exception as exc:  # noqa: BLE001
            print(f"[Update] Fehler beim Update-Check: {exc}", flush=True)


# ------------------------------------------------------------------------------
#  Endpunkte
# ------------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    pub = tunnel.public_url()
    up_status = updater.get_status()
    return {
        "status": "ok",
        "version": config.version(),
        "update_available": up_status.get("update_available", False),
        "remote_version": up_status.get("remote_version", "unbekannt"),
        "blender": blender_runner.blender_available(),
        "test_mode": config.TEST_MODE,
        "api_key_set": bool(config.ROBLOX_API_KEY),
        "access_token_set": bool(config.BRS_ACCESS_TOKEN),
        "studio_url": f"http://localhost:{config.PORT}",
        "public_url": pub or None,
        "queue_length": len(MANAGER.queue),
        "active_job": MANAGER.current_id,
    }


@app.get("/update/status")
def update_status() -> dict:
    return updater.get_status()


@app.post("/update")
def perform_update(background_tasks: BackgroundTasks) -> dict:
    updated, msg = updater.check_and_apply(force=False)
    if updated:
        background_tasks.add_task(trigger_restart)
    return {
        "updated": updated,
        "message": msg,
        "restarting": updated,
    }


@app.post("/update/restart")
def restart_endpoint(background_tasks: BackgroundTasks) -> dict:
    background_tasks.add_task(trigger_restart)
    return {"status": "ok", "message": "Server wird neu gestartet ..."}


@app.get("/diagnostics")
def diagnostics_endpoint() -> dict:
    checks = diagnostics.run_checks()
    return {
        "status": "ok" if all(
            c["ok"] or "GitHub" in c["name"] or "Oeffentliche" in c["name"]
            for c in checks
        ) else "problems",
        "checks": checks,
        "text": diagnostics.as_text(checks),
    }


@app.post("/jobs")
@app.post("/jobs/create")
def create_job(body: JobCreateRequest) -> dict:
    """Nimmt einen neuen Render-Auftrag an und fuegt ihn in die Warteschlange ein."""
    # Plausibilitaetscheck
    if body.username:
        u = body.username.strip()
        if not (3 <= len(u) <= 20) or not all(c.isalnum() or c in "_-" for c in u):
            raise HTTPException(400, "Ungueltiger Roblox-Benutzername (3-20 Zeichen, A-Z, 0-9, _).")

    res = MANAGER.submit(body)
    return res


@app.get("/jobs")
def list_jobs() -> dict:
    """Liefert den Status aller aktuellen und wartenden Auftraege."""
    with MANAGER.lock:
        current = MANAGER.get_status(MANAGER.current_id) if MANAGER.current_id else None
        queued = [MANAGER.get_status(jid) for jid in MANAGER.queue]
        history = [
            {"job_id": j["id"], "username": j.get("username", ""), "state": j.get("state", "")}
            for j in list(MANAGER.jobs.values())[-15:]
        ]
    return {
        "current": current,
        "queued": queued,
        "history": history,
    }


@app.get("/jobs/current")
def current_job() -> dict:
    if MANAGER.current_id:
        return MANAGER.get_status(MANAGER.current_id)
    if MANAGER.queue:
        return MANAGER.get_status(MANAGER.queue[0])
    return {
        "exists": False,
        "state": "idle",
        "message": "Server ist bereit - kein Auftrag aktiv.",
        "queue_position": 0,
        "est_seconds_left": 0,
    }


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    status = MANAGER.get_status(job_id)
    if not status["exists"]:
        raise HTTPException(404, "Auftrag existiert nicht oder ist abgelaufen.")
    return status


@app.get("/jobs/{job_id}/image/info")
def image_info(job_id: str) -> dict:
    job = MANAGER.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Auftrag nicht gefunden.")
    if job.get("state") != "done" or not job.get("rgba_path"):
        raise HTTPException(409, f"Bild noch nicht fertig (Status: {job.get('state')}).")
    p = Path(job["rgba_path"])
    return {
        "width": job["width"],
        "height": job["height"],
        "bytes": p.stat().st_size if p.is_file() else (job["width"] * job["height"] * 4),
    }


@app.get("/jobs/{job_id}/image/rows")
def image_rows(job_id: str, y: int = 0, rows: int = 16) -> Response:
    job = MANAGER.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Auftrag nicht gefunden.")
    if job.get("state") != "done" or not job.get("rgba_path"):
        raise HTTPException(409, f"Bild noch nicht fertig (Status: {job.get('state')}).")
    width = int(job["width"])
    height = int(job["height"])
    y = max(0, min(y, height - 1))
    rows = max(1, min(rows, 64, height - y))
    try:
        data = Path(job["rgba_path"]).read_bytes()
    except OSError as exc:
        raise HTTPException(500, f"Bilddaten nicht lesbar: {exc}") from exc
    start = y * width * 4
    end = (y + rows) * width * 4
    chunk = data[start:end]
    if not chunk:
        raise HTTPException(400, "Ungueltiger Zeilenbereich.")
    return Response(content=chunk, media_type="application/octet-stream")


@app.get("/jobs/{job_id}/image/rgba")
def image_rgba(job_id: str) -> Response:
    job = MANAGER.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Auftrag nicht gefunden.")
    if job.get("state") != "done" or not job.get("rgba_path"):
        raise HTTPException(409, f"Bild noch nicht fertig (Status: {job.get('state')}).")
    try:
        data = Path(job["rgba_path"]).read_bytes()
    except OSError as exc:
        raise HTTPException(500, f"Bilddaten nicht lesbar: {exc}") from exc
    return Response(content=data, media_type="application/octet-stream")


@app.get("/jobs/{job_id}/image.png")
def image_png(job_id: str) -> FileResponse:
    job = MANAGER.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Auftrag nicht gefunden.")
    png = Path(job["dir"]) / "render.png"
    if not png.exists():
        raise HTTPException(409, f"Bild noch nicht fertig (Status: {job.get('state')}).")
    return FileResponse(png, media_type="image/png")


@app.get("/roblox/asset/{asset_id}")
def roblox_asset(asset_id: str) -> Response:
    """Debug-Endpunkt: laedt ein Roblox-Asset per API-Key."""
    session = avatar._session()  # noqa: SLF001
    try:
        data = avatar.legacy_delivery_download(session, asset_id)
    except avatar.AvatarError as exc:
        raise HTTPException(502, str(exc)) from exc
    return Response(content=data, media_type="application/octet-stream")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    with MANAGER.lock:
        curr_status = MANAGER.get_status(MANAGER.current_id) if MANAGER.current_id else None
        queue_len = len(MANAGER.queue)

    state = curr_status.get("state", "idle") if curr_status else "idle"
    msg = curr_status.get("message", "Server bereit - kein Auftrag aktiv.") if curr_status else "Server bereit - kein Auftrag aktiv."
    job_id = curr_status.get("job_id", "") if curr_status else ""
    progress = curr_status.get("progress", 0) if curr_status else 0
    est_sec = curr_status.get("est_seconds_left", 0) if curr_status else 0

    img = ""
    if state == "done" and job_id:
        img = f'<img src="/jobs/{job_id}/image.png" alt="Render">' \
              f'<p><a href="/jobs/{job_id}/image.png" target="_blank">Bild in Originalgroesse &ouml;ffnen</a></p>'
    color = {"done": "#2ecc71", "error": "#e74c3c", "idle": "#7f8c8d"}.get(state, "#f39c12")
    pub = tunnel.public_url()
    warn = ""
    if not config.TEST_MODE and not config.ROBLOX_API_KEY:
        warn += (
            '<p class="warn">Kein ROBLOX_API_KEY gesetzt. Seit Maerz 2026 braucht der '
            "3D-Avatar-Download einen Open-Cloud-Key mit Recht <code>thumbnails: Read</code>. "
            "Siehe ANLEITUNG.md Abschnitt 9.</p>"
        )
    if pub:
        warn += f'<p class="info">Oeffentliche URL fuer Live-Spiele: <code>{pub}</code></p>'

    step_info = f"<p style='color:#a0aec0;font-size:0.95rem;margin-top:8px'>Warteschlange: {queue_len} Auftraege &bull; Restzeit: ~{est_sec} s</p>"

    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="3"><title>Blender Render Server</title>
<style>body{{font-family:system-ui,Segoe UI,Arial;background:#121418;color:#eee;
display:flex;flex-direction:column;align-items:center;padding:40px}}
h1{{font-size:1.6rem}} .box{{background:#1b1f27;border-radius:14px;padding:24px 32px;
max-width:640px;text-align:center;box-shadow:0 8px 24px rgba(0,0,0,0.4)}} .state{{color:{color};font-size:1.3rem;font-weight:600}}
.bar{{height:12px;background:#282e3b;border-radius:6px;margin:16px 0;overflow:hidden}}
.fill{{height:100%;width:{progress}%;background:linear-gradient(90deg,#3b82f6,#10b981);transition:width 0.4s ease}} img{{max-width:100%;
border-radius:8px}} a{{color:#3b82f6;text-decoration:none}} a:hover{{text-decoration:underline}}
.warn{{background:#3a2424;color:#f5c2c2;padding:10px 12px;border-radius:8px;font-size:0.9rem;text-align:left}}
.info{{background:#1e293b;color:#93c5fd;padding:10px 12px;border-radius:8px;font-size:0.85rem;text-align:left}}
.btn{{background:#2563eb;color:#fff;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;font-weight:600}}
.btn:hover{{background:#1d4ed8}}
code{{color:#93c5fd}}</style></head><body>
<h1>&#129482; Blender Render Server (Rigged Cycles)</h1>
<div class="box">
<p class="state">{state.upper()}</p><p style="font-size:1.05rem">{msg}</p>
{step_info}
<div class="bar"><div class="fill"></div></div>
<p style="color:#718096;font-size:0.85rem;margin-bottom:16px">{progress}% &middot; Warteschlange: {queue_len}</p>
{warn}
{img}
<div style="margin-top:20px;border-top:1px solid #2d3748;padding-top:16px">
<form method="post" action="/update" style="display:inline">
<button class="btn" type="submit">&#128260; Auf Updates pr&uuml;fen &amp; Neustarten</button>
</form>
</div>
<p style="color:#718096;font-size:0.85rem;margin-top:16px">Version {config.version()} &middot;
Test-Modus: {'an' if config.TEST_MODE else 'aus'} &middot;
Aufbewahrungszeit: {config.JOB_RETENTION_DAYS} Tage &middot;
<a href="/diagnostics">Diagnose</a> &middot;
Aktualisiert alle 3 s.</p>
</div></body></html>"""
