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


def _setup_world(scene, environment_path: Path | None = None):
    """Richtet die Welt mit der mitgelieferten EXR-Umgebung ein.

    Der Nishita-Himmel bleibt als robuster Fallback erhalten, damit lokale
    Installationen mit einer unvollstaendigen/alten Kopie weiter rendern.
    """
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
    background.inputs["Strength"].default_value = 1.0
    if environment_path and environment_path.is_file():
        environment = nodes.new("ShaderNodeTexEnvironment")
        environment.name = "BRS_Sunset_JHBCentral"
        environment.image = bpy.data.images.load(str(environment_path), check_existing=True)
        links.new(environment.outputs["Color"], background.inputs["Color"])
        _log(f"[Blender] Umgebungsbeleuchtung: {environment_path.name}")
    else:
        sky = nodes.new("ShaderNodeTexSky")
        sky.sky_type = "NISHITA"
        sky.sun_elevation = radians(38)
        sky.sun_rotation = radians(160)
        links.new(sky.outputs["Color"], background.inputs["Color"])
        _log("[Blender] EXR nicht gefunden; verwende Nishita-Himmel.")
    links.new(background.outputs["Background"], out.inputs["Surface"])
    return world


def _make_material_glassy(material):
    """Macht ein importiertes, texturiertes Material glasig, aber opak.

    Anders als echtes Transmissionsglas bleibt der Avatar dadurch voll
    sichtbar. Vorhandene Base-Color-Verknuepfungen (Roblox-Texturen) werden
    absichtlich nicht ersetzt.
    """
    material.use_nodes = True
    if hasattr(material, "blend_method"):
        material.blend_method = "OPAQUE"
    for bsdf in (n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"):
        inputs = bsdf.inputs
        if "Roughness" in inputs:
            inputs["Roughness"].default_value = 0.12
        if "IOR" in inputs:
            inputs["IOR"].default_value = 1.45
        # Keine Transmission: glasige Klarlack-Reflexe ohne Durchsichtigkeit.
        for socket in ("Transmission Weight", "Transmission"):
            if socket in inputs:
                inputs[socket].default_value = 0.0
        for socket, value in (("Coat Weight", 0.85), ("Coat", 0.85),
                              ("Coat Roughness", 0.04), ("Clearcoat Roughness", 0.04)):
            if socket in inputs:
                inputs[socket].default_value = value
    return material


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

    # Avatar-Thumbnail-OBJs sind bereits in der Profilpose gebacken und haben
    # kein Rig. Eine echte Rueckkehr in die Ruhepose ist beim OBJ nicht moeglich;
    # vorhandene Armatures (z.B. bei lokal bereitgestellten Modellen) werden aber
    # sicher in ihre unverformte REST-Pose versetzt.
    for armature in (o for o in scene.objects if o.type == "ARMATURE"):
        armature.data.pose_position = "REST"

    # Roblox schaut entlang -Z. Nach dem Aufrichten zeigt die Vorderseite +Y;
    # 180 Grad um die Hochachse dreht den Torso frontal zur Kamera auf -Y.
    _select_all(meshes)
    for obj in meshes:
        obj.rotation_euler.rotate_axis("Z", radians(180))
    bpy.context.view_layer.update()
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)

    # 5) Material: Originaltexturen plus opake, glasige Klarlackschicht ----------
    if material_mode == "glass":
        _log("[Blender] Veredle Originalmaterialien opak und glasig ...")
        seen_materials = set()
        for obj in meshes:
            for material in obj.data.materials:
                if material is not None and material.name not in seen_materials:
                    _make_material_glassy(material)
                    seen_materials.add(material.name)
    # Smooth shading fuer alle Flaechen
    for obj in meshes:
        for poly in obj.data.polygons:
            poly.use_smooth = True
    report("loading", 1.0)

    # 6) Licht + Himmel ---------------------------------------------------------
    environment_path = Path(__file__).resolve().parent.parent / "sunset_jhbcentral_4k.exr"
    _setup_world(scene, environment_path)
    _add_area_light(scene, "BRS_Key", 500, 4.0, (1.5, -1.3, 1.7), 7.0)
    _add_area_light(scene, "BRS_Rim", 250, 3.0, (-1.7, 1.3, 1.0), 7.0)
    _add_area_light(scene, "BRS_Fill", 120, 6.0, (-0.6, -1.7, 0.3), 8.0)

    # 7) Kamera automatisch ausrichten ------------------------------------------
    mn, mx = _world_bbox(meshes)
    center = (mn + mx) / 2
    radius = max(mx.x - mn.x, mx.y - mn.y, mx.z - mn.z) / 2 or 1.0
    fov_deg = 32.0
    distance = radius / tan(radians(fov_deg) / 2.0) * 1.3 + radius * 0.6
    # Frontal statt Profil-/Dreiviertelansicht; nur leicht von oben.
    direction = Vector((0.0, -1.0, 0.12)).normalized()
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
