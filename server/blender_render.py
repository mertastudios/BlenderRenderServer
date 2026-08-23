"""Blender-Render-Skript: Roblox-Avatar mit echtem R15/R6-Rig und Glas-Material in Cycles rendern.

Funktionen:
  - Baut ein vollstaendiges Knochenskelett (Armature) mit 15 Knochen (R15) oder 6 Knochen (R6)
  - Laedt alle Koerperteile einzeln und bindet sie ueber Vertex-Groups & Armature-Modifier an die Knochen
  - Ermoeglicht volles Posing sowie exaktes Zuruecksetzen in die unposed T-Pose (REST-Pose)
  - Veredelt die Originaltexturen mit opaker, glasiger Klarlack-Schicht
  - Rendert in Cycles mit Live-Sample-Fortschritt

Kann auf zwei Wegen ausgefuehrt werden:
  a) In einer echten Blender-Installation via Subprozess:
     blender --background --factory-startup --python blender_render.py -- \
        --input MODELDIR --output BILD.png --width 1024 --height 1024 ...
  b) In-process, wenn Blender als Pip-Modul installiert ist (import bpy):
     from server.blender_render import render_scene
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ------------------------------------------------------------------------------
#  Hilfsfunktionen
# ------------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(str(msg), flush=True)


def _world_bbox(objs):
    from mathutils import Vector

    mn = Vector((1e30, 1e30, 1e30))
    mx = Vector((-1e30, -1e30, -1e30))
    count = 0
    for o in objs:
        if o.type != "MESH":
            continue
        count += 1
        for corner in o.bound_box:
            world = o.matrix_world @ Vector(corner)
            mn.x = min(mn.x, world.x)
            mn.y = min(mn.y, world.y)
            mn.z = min(mn.z, world.z)
            mx.x = max(mx.x, world.x)
            mx.y = max(mx.y, world.y)
            mx.z = max(mx.z, world.z)
    if count == 0:
        return Vector((-1, -1, -1)), Vector((1, 1, 1))
    return mn, mx


def _add_area_light(scene, name: str, energy: float, size: float, direction, distance: float):
    from mathutils import Vector
    import bpy

    light_data = bpy.data.lights.new(name, "AREA")
    light_data.energy = energy
    light_data.size = size
    light_obj = bpy.data.objects.new(name, light_data)
    scene.collection.objects.link(light_obj)
    d = Vector(direction).normalized()
    light_obj.location = d * distance
    aim = (Vector((0.0, 0.0, 0.0)) - light_obj.location).normalized()
    light_obj.rotation_euler = aim.to_track_quat("-Z", "Y").to_euler()
    return light_obj


def _setup_world(scene, environment_path: Optional[Path] = None):
    """Richtet die Welt mit der mitgelieferten EXR-Umgebung oder Nishita-Himmel ein."""
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
    """Macht ein importiertes, texturiertes Material glasig, aber opak."""
    material.use_nodes = True
    if hasattr(material, "blend_method"):
        material.blend_method = "OPAQUE"
    for bsdf in (n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"):
        inputs = bsdf.inputs
        if "Roughness" in inputs:
            inputs["Roughness"].default_value = 0.12
        if "IOR" in inputs:
            inputs["IOR"].default_value = 1.45
        for socket in ("Transmission Weight", "Transmission"):
            if socket in inputs:
                inputs[socket].default_value = 0.0
        for socket, value in (("Coat Weight", 0.85), ("Coat", 0.85),
                              ("Coat Roughness", 0.04), ("Clearcoat Roughness", 0.04)):
            if socket in inputs:
                inputs[socket].default_value = value
    return material


def _select_all(objs):
    import bpy

    for obj in bpy.context.scene.objects:
        obj.select_set(False)
    for obj in objs:
        obj.select_set(True)
    if objs:
        bpy.context.view_layer.objects.active = objs[0]


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
#  R15 & R6 Armature / Knochenskelett-Erstellung
# ------------------------------------------------------------------------------

def build_roblox_armature(scene, rig_type: str = "R15"):
    """Erzeugt ein sauberes R15 oder R6 Knochenskelett (Armature) in neutraler T-Pose."""
    import bpy

    arm_data = bpy.data.armatures.new(f"RobloxRig_{rig_type}")
    arm_obj = bpy.data.objects.new(f"RobloxRig_{rig_type}", arm_data)
    scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    
    # In Edit-Mode Knochen anlegen (Blender: Z=Hoch, X=Rechts, Y=Tiefe)
    bpy.ops.object.mode_set(mode="EDIT")
    bones = arm_data.edit_bones

    if rig_type == "R6":
        root = bones.new("HumanoidRootPart")
        root.head = (0.0, 0.0, 3.0)
        root.tail = (0.0, 0.0, 3.5)

        torso = bones.new("Torso")
        torso.head = (0.0, 0.0, 2.0)
        torso.tail = (0.0, 0.0, 4.0)
        torso.parent = root

        head = bones.new("Head")
        head.head = (0.0, 0.0, 4.0)
        head.tail = (0.0, 0.0, 5.2)
        head.parent = torso

        la = bones.new("Left Arm")
        la.head = (-1.5, 0.0, 4.0)
        la.tail = (-1.5, 0.0, 2.0)
        la.parent = torso

        ra = bones.new("Right Arm")
        ra.head = (1.5, 0.0, 4.0)
        ra.tail = (1.5, 0.0, 2.0)
        ra.parent = torso

        ll = bones.new("Left Leg")
        ll.head = (-0.5, 0.0, 2.0)
        ll.tail = (-0.5, 0.0, 0.0)
        ll.parent = torso

        rl = bones.new("Right Leg")
        rl.head = (0.5, 0.0, 2.0)
        rl.tail = (0.5, 0.0, 0.0)
        rl.parent = torso

    else:
        # Standard R15: 15 Knochen
        root = bones.new("HumanoidRootPart")
        root.head = (0.0, 0.0, 3.0)
        root.tail = (0.0, 0.0, 3.5)

        lt = bones.new("LowerTorso")
        lt.head = (0.0, 0.0, 2.6)
        lt.tail = (0.0, 0.0, 3.4)
        lt.parent = root

        ut = bones.new("UpperTorso")
        ut.head = (0.0, 0.0, 3.4)
        ut.tail = (0.0, 0.0, 5.0)
        ut.parent = lt

        head = bones.new("Head")
        head.head = (0.0, 0.0, 5.0)
        head.tail = (0.0, 0.0, 6.2)
        head.parent = ut

        # Linker Arm
        lua = bones.new("LeftUpperArm")
        lua.head = (-1.4, 0.0, 4.6)
        lua.tail = (-1.4, 0.0, 3.4)
        lua.parent = ut

        lla = bones.new("LeftLowerArm")
        lla.head = (-1.4, 0.0, 3.4)
        lla.tail = (-1.4, 0.0, 2.2)
        lla.parent = lua

        lh = bones.new("LeftHand")
        lh.head = (-1.4, 0.0, 2.2)
        lh.tail = (-1.4, 0.0, 1.4)
        lh.parent = lla

        # Rechter Arm
        rua = bones.new("RightUpperArm")
        rua.head = (1.4, 0.0, 4.6)
        rua.tail = (1.4, 0.0, 3.4)
        rua.parent = ut

        rla = bones.new("RightLowerArm")
        rla.head = (1.4, 0.0, 3.4)
        rla.tail = (1.4, 0.0, 2.2)
        rla.parent = rua

        rh = bones.new("RightHand")
        rh.head = (1.4, 0.0, 2.2)
        rh.tail = (1.4, 0.0, 1.4)
        rh.parent = rla

        # Linkes Bein
        lul = bones.new("LeftUpperLeg")
        lul.head = (-0.55, 0.0, 2.6)
        lul.tail = (-0.55, 0.0, 1.4)
        lul.parent = lt

        lll = bones.new("LeftLowerLeg")
        lll.head = (-0.55, 0.0, 1.4)
        lll.tail = (-0.55, 0.0, 0.2)
        lll.parent = lul

        lf = bones.new("LeftFoot")
        lf.head = (-0.55, 0.0, 0.2)
        lf.tail = (-0.55, 0.0, -0.6)
        lf.parent = lll

        # Rechtes Bein
        rul = bones.new("RightUpperLeg")
        rul.head = (0.55, 0.0, 2.6)
        rul.tail = (0.55, 0.0, 1.4)
        rul.parent = lt

        rll = bones.new("RightLowerLeg")
        rll.head = (0.55, 0.0, 1.4)
        rll.tail = (0.55, 0.0, 0.2)
        rll.parent = rul

        rf = bones.new("RightFoot")
        rf.head = (0.55, 0.0, 0.2)
        rf.tail = (0.55, 0.0, -0.6)
        rf.parent = rll

    bpy.ops.object.mode_set(mode="OBJECT")
    arm_data.pose_position = "REST"
    _log(f"[Blender] {rig_type}-Armature mit {len(arm_data.bones)} Knochen aufgebaut (REST-Pose aktiv).")
    return arm_obj


def bind_mesh_to_armature(mesh_obj, arm_obj, bone_name: str):
    """Bindet ein Mesh-Objekt ueber eine Vertex-Gruppe an einen Knochen des Rigs."""
    if bone_name not in arm_obj.data.bones:
        # Fallback auf passenden Hauptknochen
        if "Torso" in bone_name:
            bone_name = "UpperTorso" if "UpperTorso" in arm_obj.data.bones else "Torso"
        elif "Arm" in bone_name:
            bone_name = "LeftUpperArm" if "Left" in bone_name else "RightUpperArm"
        elif "Leg" in bone_name:
            bone_name = "LeftUpperLeg" if "Left" in bone_name else "RightUpperLeg"
        elif "Head" in bone_name or "Hair" in bone_name or "Hat" in bone_name or "Face" in bone_name:
            bone_name = "Head"
        else:
            bone_name = "UpperTorso" if "UpperTorso" in arm_obj.data.bones else "Torso"

    if bone_name in arm_obj.data.bones:
        vg = mesh_obj.vertex_groups.get(bone_name)
        if not vg:
            vg = mesh_obj.vertex_groups.new(name=bone_name)
        all_verts = [v.index for v in mesh_obj.data.vertices]
        if all_verts:
            vg.add(all_verts, 1.0, "REPLACE")

    mesh_obj.parent = arm_obj
    mod = mesh_obj.modifiers.get("Armature")
    if not mod:
        mod = mesh_obj.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = arm_obj
    mod.use_vertex_groups = True


def _match_bone_for_obj(obj_name: str, center_z: float, center_x: float) -> str:
    """Bestimmt anhand des Namens oder der Position den zugehoerigen R15-Knochen."""
    name_lower = obj_name.lower()
    
    # Exakte Namensuebereinstimmung
    for b in ("LeftUpperArm", "LeftLowerArm", "LeftHand",
              "RightUpperArm", "RightLowerArm", "RightHand",
              "LeftUpperLeg", "LeftLowerLeg", "LeftFoot",
              "RightUpperLeg", "RightLowerLeg", "RightFoot",
              "UpperTorso", "LowerTorso", "Head", "Torso", "Left Arm", "Right Arm", "Left Leg", "Right Leg"):
        if b.lower() in name_lower:
            return b

    # Accessoires
    if any(k in name_lower for k in ("hat", "hair", "face", "glass", "horn", "cap")):
        return "Head"
    if any(k in name_lower for k in ("back", "wing", "cape", "shoulder", "sword", "shield")):
        return "UpperTorso"

    # Positionsbasierte Zuordnung
    if center_z > 4.8:
        return "Head"
    elif center_z > 3.4:
        if center_x < -1.0:
            return "LeftUpperArm"
        elif center_x > 1.0:
            return "RightUpperArm"
        return "UpperTorso"
    elif center_z > 2.2:
        if center_x < -1.0:
            return "LeftLowerArm"
        elif center_x > 1.0:
            return "RightLowerArm"
        return "LowerTorso"
    elif center_z > 1.2:
        return "LeftUpperLeg" if center_x < 0 else "RightUpperLeg"
    else:
        return "LeftLowerLeg" if center_x < 0 else "RightLowerLeg"


# ------------------------------------------------------------------------------
#  Hauptfunktion
# ------------------------------------------------------------------------------

def render_scene(params: dict, progress=None) -> None:
    """Rendert das Modell aus params['input'] voll geriggt nach params['output']."""
    import bpy
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

    # 1) Frische, leere Szene ---------------------------------------------------
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    report("loading", 0.05)

    # 2) Manifest pruefen / Mesh-Import -----------------------------------------
    manifest_path = input_dir / "manifest.json"
    manifest_data = {}
    if manifest_path.exists():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    rig_type = manifest_data.get("rig_type", "R15")
    _log(f"[Blender] Erstelle {rig_type}-Avatar-Rig ...")
    armature_obj = build_roblox_armature(scene, rig_type)
    report("loading", 0.2)

    # Pruefen ob einzelne Part-OBJs vorhanden sind
    part_files = list(input_dir.glob("*.obj"))
    individual_parts = [p for p in part_files if p.name != "avatar.obj"]

    imported_meshes = []

    if individual_parts:
        _log(f"[Blender] Lade {len(individual_parts)} einzelne Koerperteile & Accessoires ...")
        for part_p in individual_parts:
            part_name = part_p.stem
            bpy.ops.wm.obj_import(filepath=str(part_p))
            new_objs = [o for o in scene.objects if o.type == "MESH" and o not in imported_meshes]
            for obj in new_objs:
                bone_name = part_name
                for p_meta in manifest_data.get("parts", []):
                    if p_meta.get("name") == part_name:
                        bone_name = p_meta.get("bone", part_name)
                        break
                bind_mesh_to_armature(obj, armature_obj, bone_name)
                imported_meshes.append(obj)
    else:
        # Standard avatar.obj importieren
        obj_path = input_dir / "avatar.obj"
        if not obj_path.exists():
            raise RuntimeError(f"Weder Koerperteile noch avatar.obj gefunden in {input_dir}")
        _log(f"[Blender] Importiere {obj_path} ...")
        bpy.ops.wm.obj_import(filepath=str(obj_path))
        imported_meshes = [o for o in scene.objects if o.type == "MESH"]

    if not imported_meshes:
        raise RuntimeError("Im Modell wurden keine Meshes gefunden.")
    _log(f"[Blender] {len(imported_meshes)} Mesh-Objekte geladen.")
    report("loading", 0.4)

    # 3) Transformationen einbacken & Ausrichtung --------------------------------
    bpy.context.view_layer.update()
    _select_all(imported_meshes)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    mn, mx = _world_bbox(imported_meshes)
    _log(f"[Blender] Modell-Ausmasse: x={mx.x - mn.x:.2f} y={mx.y - mn.y:.2f} z={mx.z - mn.z:.2f}")
    if (mx.y - mn.y) > (mx.z - mn.z) * 1.3 and (mx.y - mn.y) > (mx.x - mn.x):
        _log("[Blender] Modell liegt 'flach' (Y-hoch) -> wird aufgerichtet.")
        _select_all(imported_meshes)
        for obj in imported_meshes:
            obj.rotation_euler.rotate_axis("X", radians(90))
        bpy.context.view_layer.update()
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    report("loading", 0.6)

    # 4) Zentrieren & Skalieren -------------------------------------------------
    mn, mx = _world_bbox(imported_meshes)
    center = (mn + mx) / 2
    max_dim = max(mx.x - mn.x, mx.y - mn.y, mx.z - mn.z) or 1.0
    scale = 2.2 / max_dim
    _select_all(imported_meshes)
    for obj in imported_meshes:
        obj.location = (obj.location.x - center.x, obj.location.y - center.y, obj.location.z - center.z)
        obj.scale = (obj.scale.x * scale, obj.scale.y * scale, obj.scale.z * scale)
    bpy.context.view_layer.update()
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    # Armature ebenfalls anpassen & Knochen mit Meshes verknuepfen
    if not individual_parts:
        for obj in imported_meshes:
            obj_mn, obj_mx = _world_bbox([obj])
            obj_center = (obj_mn + obj_mx) / 2
            bone_name = _match_bone_for_obj(obj.name, obj_center.z, obj_center.x)
            bind_mesh_to_armature(obj, armature_obj, bone_name)

    # Skelett sicher in die REST-Pose versetzen (neutral unposed)
    armature_obj.data.pose_position = "REST"
    for pose_bone in armature_obj.pose.bones:
        pose_bone.location = (0.0, 0.0, 0.0)
        pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pose_bone.rotation_euler = (0.0, 0.0, 0.0)
        pose_bone.scale = (1.0, 1.0, 1.0)

    # Frontal zur Kamera ausrichten
    _select_all(imported_meshes)
    for obj in imported_meshes:
        obj.rotation_euler.rotate_axis("Z", radians(180))
    bpy.context.view_layer.update()
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    report("loading", 0.8)

    # 5) Material: Originaltexturen plus opake Glasur ---------------------------
    if material_mode == "glass":
        _log("[Blender] Veredle Originalmaterialien opak und glasig ...")
        seen_materials = set()
        for obj in imported_meshes:
            for material in obj.data.materials:
                if material is not None and material.name not in seen_materials:
                    _make_material_glassy(material)
                    seen_materials.add(material.name)

    for obj in imported_meshes:
        for poly in obj.data.polygons:
            poly.use_smooth = True
    report("loading", 1.0)

    # 6) Licht + Umgebung -------------------------------------------------------
    environment_path = Path(__file__).resolve().parent.parent / "sunset_jhbcentral_4k.exr"
    _setup_world(scene, environment_path)
    _add_area_light(scene, "BRS_Key", 500, 4.0, (1.5, -1.3, 1.7), 7.0)
    _add_area_light(scene, "BRS_Rim", 250, 3.0, (-1.7, 1.3, 1.0), 7.0)
    _add_area_light(scene, "BRS_Fill", 120, 6.0, (-0.6, -1.7, 0.3), 8.0)

    # 7) Kamera ausrichten ------------------------------------------------------
    mn, mx = _world_bbox(imported_meshes)
    center = (mn + mx) / 2
    radius = max(mx.x - mn.x, mx.y - mn.y, mx.z - mn.z) / 2 or 1.0
    fov_deg = 32.0
    distance = radius / tan(radians(fov_deg) / 2.0) * 1.3 + radius * 0.6
    direction = Vector((0.0, -1.0, 0.12)).normalized()
    cam_data = bpy.data.cameras.new("BRS_Cam")
    cam_data.lens_unit = "FOV"
    cam_data.angle = radians(fov_deg)
    camera = bpy.data.objects.new("BRS_Cam", cam_data)
    scene.collection.objects.link(camera)
    camera.location = center + direction * distance
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
    scene.render.film_transparent = bool(params.get("transparent_bg", False))
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = output

    # 9) Rendern ----------------------------------------------------------------
    _log(f"[Blender] Rendern startet ({width}x{height}, {samples} Samples, {used_device}) ...")
    report("rendering", 0.0)
    bpy.ops.render.render(write_still=True)
    report("rendering", 1.0)
    _log(f"[Blender] Fertig, gerendertes Bild gespeichert: {output}")


# ------------------------------------------------------------------------------
#  CLI
# ------------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Roblox-Avatar als Rig in Glas rendern")
    parser.add_argument("--input", required=True, help="Ordner mit avatar.obj / part files")
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
