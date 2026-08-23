"""Der Render-Server (FastAPI).

Endpunkte (Uebersicht, alle aus Roblox per HttpService nutzbar):
  GET  /                          -> Status-Webseite mit Live-Vorschau & Update-Status
  GET  /health                    -> {"status":"ok", "version": ..., "update_available": ...}
  POST /jobs                      -> neuen Auftrag anlegen {"username": "...", "avatar_data": ...}
  GET  /jobs/current              -> Status des aktuellen Auftrags inkl. Schritt & Restzeit
  GET  /jobs/{id}                 -> Status eines bestimmten Auftrags
  GET  /jobs/{id}/image/info      -> {width, height} (sobald fertig)
  GET  /jobs/{id}/image/rows?y=.. -> rohe RGBA-Pixelzeilen (application/octet-stream)
  GET  /jobs/{id}/image.png       -> fertiges Bild als PNG (Browser/Vorschau)
  GET  /update/status             -> Update-Status (Version, verfuegbare Updates)
  POST /update                    -> Prueft auf Updates, installiert sie und startet neu
  POST /update/restart            -> Veranlasst einen sauberen Server-Neustart
"""
from __future__ import annotations

import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from PIL import Image
from pydantic import BaseModel

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


app = FastAPI(title="BlenderRenderServer", version="1.2", lifespan=lifespan)


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


ACTIVE_STATES = {"queued", "downloading", "loading", "rendering", "encoding"}
STATE_STEPS = {
    "queued": (1, 5, "Auftrag in Warteschlange"),
    "downloading": (2, 5, "Avatar-Koerperteile & Texturen laden"),
    "loading": (3, 5, "3D-Rig & Materialien in Blender vorbereiten"),
    "rendering": (4, 5, "Blender Cycles High-End Rendern"),
    "encoding": (5, 5, "Bild fuer Uebertragung vorbereiten"),
    "done": (5, 5, "Fertig gerendert"),
    "error": (0, 5, "Fehler"),
}


class JobBody(BaseModel):
    username: str
    avatar_data: Optional[Dict[str, Any]] = None


def trigger_restart() -> None:
    """Startet den Server-Prozess sauber neu."""
    print("[Server] Neustart wird ausgeloest ...", flush=True)
    time.sleep(0.5)
    # Exit-Code 77 signalisiert dem Watchdog (run.py) den automatischen Neustart
    os._exit(77)


class JobManager:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.jobs: dict[str, dict] = {}
        self.order: list[str] = []
        self.current_id: str | None = None
        self.pending_id: str | None = None

    # ------------------------------------------------------------- Hilfen
    @staticmethod
    def _job_dir(job_id: str) -> Path:
        return config.ROOT / "data" / "jobs" / job_id

    def _set(self, job: dict, state: str, message: str = "", step: Optional[int] = None,
             est_seconds_left: Optional[int] = None) -> None:
        job["state"] = state
        step_num, step_total, default_name = STATE_STEPS.get(state, (1, 5, state))
        job["step"] = step if step is not None else step_num
        job["step_total"] = step_total
        job["step_name"] = default_name
        if est_seconds_left is not None:
            job["est_seconds_left"] = est_seconds_left
        job["message"] = message or default_name
        job["updated_at"] = time.time()
        print(f"[Job {job['id'][:8]}] Schritt {job['step']}/{job['step_total']} ({state}): {job['message']}", flush=True)

    def active(self) -> bool:
        job = self.jobs.get(self.current_id or "")
        return bool(job and job["state"] in ACTIVE_STATES)

    def get(self, job_id: str) -> dict | None:
        return self.jobs.get(job_id)

    def current(self) -> dict | None:
        return self.jobs.get(self.current_id or "") or self.jobs.get(self.pending_id or "")

    # --------------------------------------------------------- Auftrag anlegen
    def submit(self, username: str, avatar_data: Optional[Dict[str, Any]] = None) -> dict:
        username = username.strip()
        with self.lock:
            if self.active():
                if self.pending_id and self.pending_id in self.jobs:
                    old = self.jobs[self.pending_id]
                    if old["state"] == "queued":
                        old["state"] = "superseded"
                job_id = uuid.uuid4().hex[:12]
                job = self._new_job(job_id, username, avatar_data)
                self.pending_id = job_id
                self._set(job, "queued", "Auftrag wartet (nur ein Auftrag gleichzeitig)", est_seconds_left=35)
                return job
            job_id = uuid.uuid4().hex[:12]
            job = self._new_job(job_id, username, avatar_data)
            self.current_id = job_id
            self.pending_id = None
            self._start_worker()
            return job

    def _new_job(self, job_id: str, username: str, avatar_data: Optional[Dict[str, Any]] = None) -> dict:
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        job = {
            "id": job_id,
            "username": username,
            "avatar_data": avatar_data,
            "state": "queued",
            "message": "Auftrag angelegt",
            "progress": 0,
            "step": 1,
            "step_total": 5,
            "step_name": "Initialisierung",
            "est_seconds_left": 30,
            "error": None,
            "created_at": time.time(),
            "updated_at": time.time(),
            "dir": str(job_dir),
            "width": None,
            "height": None,
            "rgba_path": None,
        }
        self.jobs[job_id] = job
        self.order.append(job_id)
        self._cleanup_old()
        return job

    def _cleanup_old(self) -> None:
        while len(self.order) > 6:
            old_id = self.order.pop(0)
            old = self.jobs.pop(old_id, None)
            if old and old.get("state") not in ACTIVE_STATES:
                try:
                    import shutil
                    shutil.rmtree(old["dir"], ignore_errors=True)
                except Exception:
                    pass
            elif old:
                self.order.insert(0, old_id)
                break

    # --------------------------------------------------------------- Worker
    def _start_worker(self) -> None:
        thread = threading.Thread(target=self._worker, daemon=True, name="brs-worker")
        thread.start()

    def _worker(self) -> None:
        while True:
            with self.lock:
                if not self.active() and self.pending_id:
                    self.current_id = self.pending_id
                    self.pending_id = None
                job = self.jobs.get(self.current_id or "")
                if not job or job["state"] not in ACTIVE_STATES:
                    return
            self._run_job(job)

    def _run_job(self, job: dict) -> None:
        job_dir = Path(job["dir"])
        render_start_time = 0.0
        try:
            # Schritt 2: Avatar & Koerperteile herunterladen -------------------------
            self._set(job, "downloading", f"Avatar '{job['username']}' wird von Roblox geladen ...", est_seconds_left=28)
            job["progress"] = 10
            model_dir = job_dir / "model"

            if config.TEST_MODE:
                info = avatar.make_test_model(model_dir)
            else:
                info = avatar.download_avatar_model(job["username"], model_dir, avatar_data=job.get("avatar_data"))
            job["avatar_info"] = info

            # Schritt 3: Rig & Materialien in Blender aufbauen -----------------------
            self._set(job, "loading", "3D-Avatar wird geriggt & Knochenskelett aufgebaut ...", est_seconds_left=22)
            job["progress"] = 25

            # Schritt 4: Blender Cycles Rendern -------------------------------------
            render_start_time = time.time()

            def progress(stage: str, frac: float | None):
                if stage == "loading":
                    job["progress"] = min(28, int(20 + 8 * (frac or 0.0)))
                elif stage == "rendering":
                    f = max(0.0, min(1.0, frac if frac is not None else 0.0))
                    job["progress"] = min(94, int(30 + 64 * f))
                    elapsed = time.time() - render_start_time
                    if f > 0.05:
                        total_est = elapsed / f
                        remaining = max(1, int(total_est - elapsed))
                        job["est_seconds_left"] = remaining + 2
                    else:
                        job["est_seconds_left"] = 18
                    job["message"] = f"Blender Cycles rendert ... {job['progress']}% (ca. {job['est_seconds_left']} s)"
                elif stage == "encoding":
                    job["progress"] = 96
                    job["est_seconds_left"] = 2

            png_path = job_dir / "render.png"
            blender_runner.render(model_dir, png_path, progress=progress)

            # Schritt 5: RGBA Pixel vorbereiten (fuer EditableImage) -----------------
            self._set(job, "encoding", "Bild wird fuer die Uebertragung vorbereitet ...", est_seconds_left=2)
            job["progress"] = 96

            img = Image.open(png_path).convert("RGBA")
            if img.width > 1024 or img.height > 1024:
                img = img.resize((1024, 1024), Image.LANCZOS)
            rgba_path = job_dir / "render.rgba"
            rgba_path.write_bytes(img.tobytes())
            job["width"] = img.width
            job["height"] = img.height
            job["rgba_path"] = str(rgba_path)

            self._set(job, "done", f"Fertig! ({img.width}x{img.height} Pixel gerendert)", est_seconds_left=0)
            job["progress"] = 100
        except Exception as exc:  # noqa: BLE001
            job["error"] = str(exc)
            self._set(job, "error", str(exc), est_seconds_left=0)

    # ----------------------------------------------------------- Status-JSON
    def payload(self, job: dict | None) -> dict:
        if not job:
            return {
                "state": "idle",
                "message": "Server ist bereit - kein Auftrag aktiv.",
                "progress": 0,
                "step": 0,
                "step_total": 5,
                "est_seconds_left": 0,
            }
        queued = []
        if self.pending_id and self.pending_id in self.jobs:
            pending = self.jobs[self.pending_id]
            queued = [{"job_id": pending["id"], "username": pending["username"]}]
        out = {
            "job_id": job["id"],
            "username": job["username"],
            "state": job["state"],
            "message": job.get("message", job["state"]),
            "progress": job.get("progress", 0),
            "step": job.get("step", 1),
            "step_total": job.get("step_total", 5),
            "step_name": job.get("step_name", ""),
            "est_seconds_left": job.get("est_seconds_left", 0),
            "error": job.get("error"),
            "queued": queued,
        }
        if job.get("width"):
            out["image"] = {"width": job["width"], "height": job["height"]}
        return out


MANAGER = JobManager()


# ------------------------------------------------------------------------------
#  Hintergrund-Update-Thread
# ------------------------------------------------------------------------------

def _update_loop() -> None:
    while True:
        time.sleep(config.AUTO_UPDATE_CHECK_SECONDS)
        if not config.AUTO_UPDATE:
            continue
        if MANAGER.active():
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
        "current_state": (MANAGER.current() or {}).get("state", "idle"),
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
def create_job(body: JobBody) -> dict:
    username = body.username.strip()
    if not (3 <= len(username) <= 20) or not all(
        ch.isalnum() or ch == "_" for ch in username
    ):
        raise HTTPException(400, "Ungueltiger Roblox-Benutzername (3-20 Zeichen, A-Z, 0-9, _).")
    job = MANAGER.submit(username, avatar_data=body.avatar_data)
    return MANAGER.payload(job)


@app.get("/jobs")
def list_jobs() -> dict:
    return {
        "current": MANAGER.payload(MANAGER.jobs.get(MANAGER.current_id or "")),
        "queued": [
            MANAGER.payload(MANAGER.jobs[j])
            for j in ([MANAGER.pending_id] if MANAGER.pending_id else [])
        ],
        "history": [
            {"job_id": j["id"], "username": j["username"], "state": j["state"]}
            for j in MANAGER.jobs.values()
        ][-10:],
    }


@app.get("/jobs/current")
def current_job() -> dict:
    return MANAGER.payload(MANAGER.jobs.get(MANAGER.current_id or ""))


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = MANAGER.get(job_id)
    if not job:
        raise HTTPException(404, "Auftrag nicht gefunden.")
    return MANAGER.payload(job)


@app.get("/jobs/{job_id}/image/info")
def image_info(job_id: str) -> dict:
    job = MANAGER.get(job_id)
    if not job:
        raise HTTPException(404, "Auftrag nicht gefunden.")
    if job["state"] != "done" or not job.get("rgba_path"):
        raise HTTPException(409, f"Bild noch nicht fertig (Status: {job['state']}).")
    return {"width": job["width"], "height": job["height"]}


@app.get("/jobs/{job_id}/image/rows")
def image_rows(job_id: str, y: int = 0, rows: int = 16) -> Response:
    job = MANAGER.get(job_id)
    if not job:
        raise HTTPException(404, "Auftrag nicht gefunden.")
    if job["state"] != "done" or not job.get("rgba_path"):
        raise HTTPException(409, f"Bild noch nicht fertig (Status: {job['state']}).")
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


@app.get("/jobs/{job_id}/image.png")
def image_png(job_id: str) -> FileResponse:
    job = MANAGER.get(job_id)
    if not job:
        raise HTTPException(404, "Auftrag nicht gefunden.")
    png = Path(job["dir"]) / "render.png"
    if not png.exists():
        raise HTTPException(409, f"Bild noch nicht fertig (Status: {job['state']}).")
    return FileResponse(png, media_type="image/png")


@app.get("/roblox/asset/{asset_id}")
def roblox_asset(asset_id: str) -> Response:
    """Debug-Endpunkt: laedt ein Roblox-Asset per API-Key (asset-legacy-delivery)."""
    session = avatar._session()  # noqa: SLF001
    try:
        data = avatar.legacy_delivery_download(session, asset_id)
    except avatar.AvatarError as exc:
        raise HTTPException(502, str(exc)) from exc
    return Response(content=data, media_type="application/octet-stream")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    payload = MANAGER.payload(MANAGER.jobs.get(MANAGER.current_id or ""))
    state = payload.get("state", "idle")
    msg = payload.get("message", "")
    job_id = payload.get("job_id", "")
    progress = payload.get("progress", 0)
    step = payload.get("step", 0)
    step_total = payload.get("step_total", 5)
    est_sec = payload.get("est_seconds_left", 0)

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

    step_info = f"<p style='color:#a0aec0;font-size:0.95rem;margin-top:8px'>Schritt {step} von {step_total} &bull; Restzeit: ~{est_sec} s</p>" if state in ACTIVE_STATES else ""

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
<p style="color:#718096;font-size:0.85rem;margin-bottom:16px">{progress}% abgeschlossen</p>
{warn}
{img}
<div style="margin-top:20px;border-top:1px solid #2d3748;padding-top:16px">
<form method="post" action="/update" style="display:inline">
<button class="btn" type="submit">&#128260; Auf Updates pr&uuml;fen &amp; Neustarten</button>
</form>
</div>
<p style="color:#718096;font-size:0.85rem;margin-top:16px">Version {config.version()} &middot;
Test-Modus: {'an' if config.TEST_MODE else 'aus'} &middot;
<a href="/diagnostics">Diagnose</a> &middot;
Aktualisiert alle 3 s.</p>
</div></body></html>"""
