"""Der Render-Server (FastAPI).

Endpunkte (Uebersicht, alle aus Roblox per HttpService nutzbar):
  GET  /                          -> kleine Status-Webseite (fuer den Browser)
  GET  /health                    -> {"status":"ok", ...}
  POST /jobs                      -> neuen Auftrag anlegen {"username": "..."}
  GET  /jobs/current              -> Status des aktuellen/letzten Auftrags
  GET  /jobs/{id}                 -> Status eines bestimmten Auftrags
  GET  /jobs/{id}/image/info      -> {width, height} (erst wenn fertig)
  GET  /jobs/{id}/image/rows?y=.. -> rohe RGBA-Pixelzeilen (application/octet-stream)
  GET  /jobs/{id}/image.png       -> fertiges Bild als PNG (Browser/Vorschau)

Es wird immer nur EIN Auftrag gleichzeitig bearbeitet; maximal EIN weiterer
Auftrag wartet in der Warteschlange ("queued").
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from PIL import Image
from pydantic import BaseModel

from . import avatar, blender_runner, config, diagnostics, tunnel, updater

app = FastAPI(title="BlenderRenderServer", version="1.1")

# Pfade, die ohne Token erreichbar bleiben (Statusseite, Health, Diagnose).
_OPEN_PATHS = {"/", "/health", "/diagnostics", "/favicon.ico"}


def _request_token(request: Request) -> str:
    header = (request.headers.get("x-brs-token") or "").strip()
    if header:
        return header
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.query_params.get("token") or "").strip()


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
STATE_LABELS = {
    "queued": "Auftrag in der Warteschlange",
    "downloading": "Avatar wird von Roblox heruntergeladen",
    "loading": "3D-Modell wird in Blender geladen",
    "rendering": "Blender Cycles rendert",
    "encoding": "Bild wird fuer die Uebertragung vorbereitet",
    "done": "Fertig",
    "error": "Fehler",
}


class JobBody(BaseModel):
    username: str


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

    def _set(self, job: dict, state: str, message: str = "") -> None:
        job["state"] = state
        job["message"] = message or STATE_LABELS.get(state, state)
        job["updated_at"] = time.time()
        print(f"[Job {job['id'][:8]}] {state}: {job['message']}", flush=True)

    def active(self) -> bool:
        job = self.jobs.get(self.current_id or "")
        return bool(job and job["state"] in ACTIVE_STATES)

    def get(self, job_id: str) -> dict | None:
        return self.jobs.get(job_id)

    def current(self) -> dict | None:
        return self.jobs.get(self.current_id or "") or self.jobs.get(self.pending_id or "")

    # --------------------------------------------------------- Auftrag anlegen
    def submit(self, username: str) -> dict:
        username = username.strip()
        with self.lock:
            if self.active():
                # Es laeuft schon etwas -> hoechstens EINEN wartenden Auftrag ersetzen
                if self.pending_id and self.pending_id in self.jobs:
                    old = self.jobs[self.pending_id]
                    if old["state"] == "queued":
                        old["state"] = "superseded"
                job_id = uuid.uuid4().hex[:12]
                job = self._new_job(job_id, username)
                self.pending_id = job_id
                self._set(job, "queued", "Auftrag wartet (nur ein Auftrag gleichzeitig)")
                return job
            job_id = uuid.uuid4().hex[:12]
            job = self._new_job(job_id, username)
            self.current_id = job_id
            self.pending_id = None
            self._start_worker()
            return job

    def _new_job(self, job_id: str, username: str) -> dict:
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        job = {
            "id": job_id,
            "username": username,
            "state": "queued",
            "message": "Auftrag angelegt",
            "progress": 0,
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
        try:
            # Phase 1: Avatar laden ------------------------------------------------
            self._set(job, "downloading", f"Avatar von '{job['username']}' wird geladen ...")
            job["progress"] = 4
            model_dir = job_dir / "model"
            if config.TEST_MODE:
                info = avatar.make_test_model(model_dir)
            else:
                info = avatar.download_avatar_model(job["username"], model_dir)
            job["avatar_info"] = info
            self._set(job, "loading", "3D-Modell wird in Blender geladen (Glas-Material) ...")
            job["progress"] = 12

            # Phase 2: Rendern ------------------------------------------------------
            def progress(stage: str, frac: float | None):
                base = {"loading": 12, "rendering": 20, "encoding": 96}.get(stage, 20)
                span = {"loading": 8, "rendering": 76, "encoding": 4}.get(stage, 0)
                if frac is None:
                    job["progress"] = base
                else:
                    job["progress"] = min(99, int(base + span * max(0.0, min(1.0, frac))))
                if stage == "rendering":
                    job["message"] = f"Blender Cycles rendert ... {job['progress']}%"

            png_path = job_dir / "render.png"
            blender_runner.render(model_dir, png_path, progress=progress)

            # Phase 3: In RGBA-Pixel umwandeln (fuer EditableImage) ----------------
            self._set(job, "encoding", "Bild wird fuer die Uebertragung vorbereitet ...")
            img = Image.open(png_path).convert("RGBA")
            if img.width > 1024 or img.height > 1024:
                img = img.resize((1024, 1024), Image.LANCZOS)
            rgba_path = job_dir / "render.rgba"
            rgba_path.write_bytes(img.tobytes())
            job["width"] = img.width
            job["height"] = img.height
            job["rgba_path"] = str(rgba_path)

            self._set(job, "done", f"Fertig! ({img.width}x{img.height} Pixel)")
            job["progress"] = 100
        except Exception as exc:  # noqa: BLE001
            job["error"] = str(exc)
            self._set(job, "error", str(exc))

    # ----------------------------------------------------------- Status-JSON
    def payload(self, job: dict | None) -> dict:
        if not job:
            return {"state": "idle", "message": "Server ist bereit - kein Auftrag aktiv."}
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
        # Nur updaten, wenn gerade kein Auftrag laeuft
        if MANAGER.active():
            continue
        try:
            updated, msg = updater.check_and_apply()
            print(f"[Update] {msg}", flush=True)
            if updated:
                import os

                print("[Update] Neustart des Servers ...", flush=True)
                os._exit(77)  # Watchdog (run.py) startet automatisch neu
        except Exception as exc:  # noqa: BLE001
            print(f"[Update] Fehler beim Update-Check: {exc}", flush=True)


@app.on_event("startup")
def _on_startup() -> None:
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


# ------------------------------------------------------------------------------
#  Endpunkte
# ------------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    pub = tunnel.public_url()
    return {
        "status": "ok",
        "version": config.version(),
        "blender": blender_runner.blender_available(),
        "test_mode": config.TEST_MODE,
        "api_key_set": bool(config.ROBLOX_API_KEY),
        "access_token_set": bool(config.BRS_ACCESS_TOKEN),
        "studio_url": f"http://localhost:{config.PORT}",
        "public_url": pub or None,
        "current_state": (MANAGER.current() or {}).get("state", "idle"),
    }


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
    job = MANAGER.submit(username)
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
            "3D-Avatar-Download (OBJ + Texturen, kein Profilbild) einen Open-Cloud-Key "
            "mit Recht <code>thumbnails: Read</code>. Siehe ANLEITUNG.md Abschnitt 9.</p>"
        )
    if pub:
        warn += f'<p class="info">Oeffentliche URL fuer Live-Spiele: <code>{pub}</code></p>'
    else:
        warn += (
            '<p class="info">Studio: <code>http://localhost:'
            f"{config.PORT}</code> &nbsp;|&nbsp; Veroeffentlichtes Spiel: "
            "<code>08_oeffentliche_adresse.bat</code> starten und die https-URL "
            "im Lua-Skript eintragen.</p>"
        )
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="5"><title>Blender Render Server</title>
<style>body{{font-family:system-ui,Segoe UI,Arial;background:#14161a;color:#eee;
display:flex;flex-direction:column;align-items:center;padding:40px}}
h1{{font-size:1.6rem}} .box{{background:#1f232b;border-radius:12px;padding:24px 32px;
max-width:640px;text-align:center}} .state{{color:{color};font-size:1.3rem;font-weight:600}}
.bar{{height:10px;background:#2b313c;border-radius:6px;margin:16px 0;overflow:hidden}}
.fill{{height:100%;width:{progress}%;background:linear-gradient(90deg,#3498db,#2ecc71)}} img{{max-width:100%;
border-radius:8px}} a{{color:#3498db}}
.warn{{background:#3a2424;color:#f5c2c2;padding:10px 12px;border-radius:8px;font-size:0.9rem;text-align:left}}
.info{{background:#243044;color:#c5d4ea;padding:10px 12px;border-radius:8px;font-size:0.85rem;text-align:left}}
code{{color:#9cdcfe}}</style></head><body>
<h1>&#129482; Blender Render Server</h1>
<div class="box">
<p class="state">{state}</p><p>{msg}</p>
<div class="bar"><div class="fill"></div></div>
{warn}
{img}
<p style="color:#8892a4;font-size:0.85rem">Version {config.version()} &middot;
Test-Modus: {'an' if config.TEST_MODE else 'aus'} &middot;
API-Key: {'ja' if config.ROBLOX_API_KEY else 'fehlt'} &middot;
<a href="/diagnostics">Verbindungscheck</a> &middot;
Diese Seite aktualisiert sich alle 5 s selbst.</p>
</div></body></html>"""
