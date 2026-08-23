"""Findet Blender und fuehrt den Render-Prozess aus.

Reihenfolge:
  1. BLENDER_PATH aus der .env (falls gesetzt)
  2. tools/blender/blender.exe im Projektordner (von 01_setup.bat)
  3. blender im PATH
  4. Blender als Pip-Modul (import bpy) -> in-process
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

from . import config

SCRIPT_PATH = Path(__file__).resolve().parent / "blender_render.py"

ProgressFn = Optional[Callable[[str, float | None], None]]

_SAMPLE_RE = re.compile(r"Sample:?\s*(\d+)\s*/\s*(\d+)")


def find_blender() -> Optional[str]:
    """Liefert den Pfad zu blender(.exe) oder None."""
    # 1) Explizit konfiguriert
    if config.BLENDER_PATH:
        p = Path(config.BLENDER_PATH)
        if p.is_dir():
            for name in ("blender.exe", "blender"):
                cand = p / name
                if cand.exists():
                    return str(cand)
        if p.exists():
            return str(p)
        print(f"[Blender] Warnung: BLENDER_PATH ({config.BLENDER_PATH}) existiert nicht.")

    # 2) tools/blender im Projektordner
    exe_name = "blender.exe" if os.name == "nt" else "blender"
    local = config.ROOT / "tools" / "blender" / exe_name
    if local.exists():
        return str(local)
    local_bin = config.ROOT / "tools" / "blender" / "blender" / exe_name
    if local_bin.exists():
        return str(local_bin)

    # 3) Im PATH
    found = shutil.which("blender")
    if found:
        return found

    return None


def blender_available() -> bool:
    if config.BLENDER_MODE == "bpy":
        return True
    if find_blender() is not None:
        return True
    try:
        import bpy  # noqa: F401
        return True
    except Exception:
        return False


def render(model_dir: Path, output_png: Path, progress: ProgressFn = None) -> None:
    """Rendert model_dir/avatar.obj nach output_png."""
    params = {
        "input": str(model_dir),
        "output": str(output_png),
        "width": config.RENDER_WIDTH,
        "height": config.RENDER_HEIGHT,
        "samples": config.RENDER_SAMPLES,
        "material": config.RENDER_MATERIAL,
        "device": config.RENDER_DEVICE,
        "transparent_bg": config.RENDER_TRANSPARENT_BG,
    }
    exe = find_blender()

    if exe and config.BLENDER_MODE != "bpy":
        _render_subprocess(exe, params, progress)
        return

    # Fallback: pip-Modul bpy (in-process)
    try:
        import bpy  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "Blender wurde nicht gefunden! Bitte einmal 01_setup.bat ausfuehren "
            "(laedt Blender automatisch herunter) oder BLENDER_PATH in der .env setzen. "
            f"(Detail: {exc})"
        ) from exc
    print("[Blender] Nutze bpy-Python-Modul (in-process).")
    from . import blender_render

    blender_render.render_scene(params, progress=progress)


def _render_subprocess(exe: str, params: dict, progress: ProgressFn) -> None:
    cmd = [
        exe,
        "--background",
        "--factory-startup",
        "--python", str(SCRIPT_PATH),
        "--",
        "--input", params["input"],
        "--output", params["output"],
        "--width", str(params["width"]),
        "--height", str(params["height"]),
        "--samples", str(params["samples"]),
        "--material", params["material"],
        "--device", params["device"],
    ]
    print(f"[Blender] Starte: {Path(exe).name} --background --python blender_render.py")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(config.ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    tail: list[str] = []
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.rstrip()
        if not line:
            continue
        print(f"  {line}")
        tail.append(line)
        tail = tail[-25:]
        if progress is not None:
            match = _SAMPLE_RE.search(line)
            if match:
                done, total = int(match.group(1)), int(match.group(2))
                if total > 0:
                    try:
                        progress("rendering", done / total)
                    except Exception:
                        pass
    code = proc.wait()
    if code != 0:
        raise RuntimeError(
            "Blender wurde mit Fehlercode %s beendet. Letzte Meldungen:\n%s"
            % (code, "\n".join(tail[-10:]))
        )
