"""Blender-Render-Skript: Roblox-Avatar mit Glas-Material in Cycles rendern.

Kann auf zwei Wegen ausgefuehrt werden:
  a) Als Skript in einer echten Blender-Installation:
     blender --background --factory-startup --python blender_render.py -- \
        --input MODELDIR --output BILD.png --width 1024 --height 1024 ...
  b) In-process, wenn Blender als Pip-Modul installiert ist (import bpy):
     from server.blender_render import render_scene
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path


# ------------------------------------------------------------------------------
#  Hilfsfunktionen
# ------------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(str(msg), flush=True)


def _world_bbox(objs):
    from mathutils import Vector

    mn = Vector((1e30, 1e30, 1e30))
    mx = Vector((-1e30, -1e30, -1e30))
    for o in objs:
        for corner in o.bound_box:
            world = o.matrix_world @ Vector(corner)
            mn.x = min(mn.x, world.x)
            mn.y = min(mn.y, world.y)
            mn.z = min(mn.z, world.z)
            mx.x = max(mx.x, world.x)
            mx.y = max(mx.y, world.y)
            mx.z = max(mx.z, world.z)
    return mn, mx


def _add_area_light(scene, name: str, energy: float, size: float, direction, distance: float):
    from mathutils import Vector

    import bpy

    light_data = bpy.data.lights.new(name, "AREA")
    light_data.energy = energy
    light_data.size = size
    light_obj = bpy.data.objects.new(name, light_data)
    bpy.context.scene.collection.objects.link(light_obj)
    d = Vector(direction).normalized()
    light_obj.location = d * distance
    # Wichtig: Das Licht muss AUF das Motiv (Ursprung) gerichtet werden!
    aim = (Vector((0.0, 0.0, 0.0)) - light_obj.location).normalized()
    light_obj.rotation_euler = aim.to_track_quat("-Z", "Y").to_euler()
    return light_obj


def _setup_world(scene):
    import bpy
    from math import radians

    world = bpy.data.worlds.new("BRS_World")
    world.use_nodes = True
    scene.world = world
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    for node in list(nodes):
        nodes.remove(node)
    out = nodes.new("ShaderNodeOutputWorld")
    background = nodes.new("ShaderNodeBackground")
    sky = nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_elevation = radians(38)
    sky.sun_rotation = radians(160)
    background.inputs["Strength"].default_value = 1.0
    links.new(sky.outputs["Color"], background.inputs["Color"])
    links.new(background.outputs["Background"], out.inputs["Surface"])
    return world


def _make_glass_material():
    import bpy

    glass = bpy.data.materials.new("RobloxGlass")
    glass.use_nodes = True
    bsdf = glass.node_tree.nodes.get("Principled BSDF")
    if bsdf is None:
        bsdf = glass.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
    inputs = bsdf.inputs
    try:
        inputs["Base Color"].default_value = (0.82, 0.91, 1.0, 1.0)
        inputs["Metallic"].default_value = 0.0
        inputs["Roughness"].default_value = 0.05
        inputs["IOR"].default_value = 1.45
    except KeyError:
        pass
    # "Coat" (Klarlack) sorgt fuer zusaetzliche, gut sichtbare Reflexe,
    # damit der Glas-Avatar auch auf transparentem Hintergrund klar zu sehen ist.
    for socket, value in (("Coat Weight", 0.45), ("Coat Roughness", 0.05)):
        if socket in inputs:
            inputs[socket].default_value = value
    # Blender 4.x: "Transmission Weight", aeltere: "Transmission"
    for socket in ("Transmission Weight", "Transmission"):
        if socket in inputs:
            inputs[socket].default_value = 1.0
            break
    return glass


def _select_all(meshes):
    import bpy

    for obj in bpy.context.scene.objects:
        obj.select_set(False)
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]


def _setup_device(scene, device: str) -> str:
    """Waehlt CPU/GPU. Gibt den tatsaechlich verwendeten Modus zurueck."""
    import bpy

    if device in ("GPU", "AUTO"):
        try:
            prefs = bpy.context.preferences.addons["cycles"].preferences
            try:
                prefs.get_devices()
            except Exception:
                pass
            for dtype in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
                try:
                    prefs.compute_device_type = dtype
                    scene.cycles.device = "GPU"
                    _log(f"[Blender] GPU-Rendering aktiviert ({dtype}).")
                    return "GPU"
                except Exception:
                    continue
        except Exception as exc:
            _log(f"[Blender] GPU konnte nicht aktiviert werden ({exc}) -> CPU.")
    scene.cycles.device = "CPU"
    return "CPU"


# ------------------------------------------------------------------------------
#  Hauptfunktion
# ------------------------------------------------------------------------------

def render_scene(params: dict, progress=None) -> None:
    """Rendert MODELDIR/avatar.obj nach params['output'].

    progress(stage, fraction) wird optional mit Fortschritt aufgerufen.
    """
    import bpy  # noqa: F401  (nur innerhalb Blender / bpy-Modul verfuegbar)
    from math import radians, tan
    from mathutils import Vector

    def report(stage: str, frac: float | None = None):
        if progress is not None:
            try:
                progress(stage, frac)
            except Exception:
                pass

    input_dir = Path(params["input"])
    output = str(params["output"])
    width = int(params.get("width", 1024))
    height = int(params.get("height", 1024))
    samples = int(params.get("samples", 96))
    material_mode = str(params.get("material", "glass")).lower()
    device = str(params.get("device", "CPU")).upper()

    obj_path = input_dir / "avatar.obj"
    if not obj_path.exists():
        raise RuntimeError(f"avatar.obj nicht gefunden in {input_dir}")

    # 1) Frische, leere Szene ---------------------------------------------------
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    report("loading", 0.05)

    # 2) OBJ importieren --------------------------------------------------------
    _log(f"[Blender] Importiere {obj_path} ...")
    bpy.ops.wm.obj_import(filepath=str(obj_path))
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("Im Modell wurden keine Meshes gefunden.")
    _log(f"[Blender] {len(meshes)} Mesh-Objekte importiert.")
    report("loading", 0.4)

    # WICHTIG: Alle Objekt-Transformationen sofort in die Mesh-Daten "einbacken",
    # damit die Welt-Koordinaten (Bounding-Box, Kamera) garantiert stimmen.
    bpy.context.view_layer.update()
    _select_all(meshes)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    # 3) Ausrichtung pruefen (falls das Modell doch "liegt" -> Y-hoch) ----------
    mn, mx = _world_bbox(meshes)
    _log(f"[Blender] Modell-Ausmasse: x={mx.x - mn.x:.2f} y={mx.y - mn.y:.2f} z={mx.z - mn.z:.2f}")
    if (mx.y - mn.y) > (mx.z - mn.z) * 1.3 and (mx.y - mn.y) > (mx.x - mn.x):
        _log("[Blender] Modell liegt 'flach' (Y-hoch) -> wird aufgerichtet.")
        _select_all(meshes)
        for obj in meshes:
            obj.rotation_euler.rotate_axis("X", radians(90))
        bpy.context.view_layer.update()
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    report("loading", 0.6)

    # 4) Zentrieren + einheitliche Groesse --------------------------------------
    mn, mx = _world_bbox(meshes)
    center = (mn + mx) / 2
    max_dim = max(mx.x - mn.x, mx.y - mn.y, mx.z - mn.z) or 1.0
    scale = 2.2 / max_dim
    _select_all(meshes)
    for obj in meshes:
        obj.location = (obj.location.x - center.x, obj.location.y - center.y, obj.location.z - center.z)
        obj.scale = (obj.scale.x * scale, obj.scale.y * scale, obj.scale.z * scale)
    bpy.context.view_layer.update()
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    report("loading", 0.8)

    # 5) Material: Glas (oder Original behalten) --------------------------------
    if material_mode == "glass":
        _log("[Blender] Erzeuge Glas-Material ...")
        glass = _make_glass_material()
        for obj in meshes:
            obj.data.materials.clear()
            obj.data.materials.append(glass)
    # Smooth shading fuer alle Flaechen
    for obj in meshes:
        for poly in obj.data.polygons:
            poly.use_smooth = True
    report("loading", 1.0)

    # 6) Licht + Himmel ---------------------------------------------------------
    _setup_world(scene)
    _add_area_light(scene, "BRS_Key", 500, 4.0, (1.5, -1.3, 1.7), 7.0)
    _add_area_light(scene, "BRS_Rim", 250, 3.0, (-1.7, 1.3, 1.0), 7.0)
    _add_area_light(scene, "BRS_Fill", 120, 6.0, (-0.6, -1.7, 0.3), 8.0)

    # 7) Kamera automatisch ausrichten ------------------------------------------
    mn, mx = _world_bbox(meshes)
    center = (mn + mx) / 2
    radius = max(mx.x - mn.x, mx.y - mn.y, mx.z - mn.z) / 2 or 1.0
    fov_deg = 32.0
    distance = radius / tan(radians(fov_deg) / 2.0) * 1.3 + radius * 0.6
    direction = Vector((1.35, -1.2, 0.5)).normalized()
    cam_data = bpy.data.cameras.new("BRS_Cam")
    cam_data.lens_unit = "FOV"
    cam_data.angle = radians(fov_deg)
    camera = bpy.data.objects.new("BRS_Cam", cam_data)
    scene.collection.objects.link(camera)
    camera.location = center + direction * distance
    # Kamera aufs Motiv ausrichten (-Z-Achse zeigt in Blickrichtung)
    aim = (center - camera.location).normalized()
    camera.rotation_euler = aim.to_track_quat("-Z", "Y").to_euler()
    scene.camera = camera

    # 8) Render-Einstellungen ---------------------------------------------------
    scene.render.engine = "CYCLES"
    used_device = _setup_device(scene, device)
    scene.cycles.samples = samples
    try:
        scene.cycles.use_denoising = True
    except Exception:
        pass
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    # Hintergrund: Himmel sichtbar (False) oder transparentes PNG (True).
    # Glas wirkt vor dem Himmel deutlich besser sichtbar.
    scene.render.film_transparent = bool(params.get("transparent_bg", False))
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = output

    # 9) Rendern ----------------------------------------------------------------
    _log(f"[Blender] Rendern startet ({width}x{height}, {samples} Samples, {used_device}) ...")
    report("rendering", 0.0)
    bpy.ops.render.render(write_still=True)
    report("rendering", 1.0)
    _log(f"[Blender] Fertig, Bild gespeichert: {output}")


# ------------------------------------------------------------------------------
#  Kommandozeilen-Modus (wird von Blender mit --python aufgerufen)
# ------------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Roblox-Avatar in Glas rendern")
    parser.add_argument("--input", required=True, help="Ordner mit avatar.obj")
    parser.add_argument("--output", required=True, help="Ziel-PNG")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--samples", type=int, default=96)
    parser.add_argument("--material", default="glass")
    parser.add_argument("--device", default="CPU")
    return parser


def _cli() -> int:
    if "--" in sys.argv:
        argv = sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = []
    args = _build_parser().parse_args(argv)
    render_scene(vars(args))
    return 0


if __name__ == "__main__":
    try:
        import bpy  # noqa: F401
    except ImportError:
        print("FEHLER: Dieses Skript benoetigt Blender (bpy).", flush=True)
        sys.exit(2)
    _log("BRS_STAGE loading")
    _cli()
    _log("BRS_RENDER_DONE")
