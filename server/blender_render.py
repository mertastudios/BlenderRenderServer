"""Blender-Render-Skript: Roblox-Szenen mit Avataren, Posen, Custom-3D-Modellen,
Spezial-Haenden (Herzform) und 3 Material-Modi (MATT, GLAS, DURCHSICHTIGES_GLAS) in Cycles rendern.

Funktionen:
  - Unterstuetzt beliebig viele Avatare in einer Szene
  - Exakte Uebernahme aller Roblox-Part-CFrames (Positionen & Rotationen fuer R15/R6-Posing)
  - Ersetzt bei Bedarf die Haende durch ein Herzform-3D-Modell (Heart Hands)
  - Laedt benutzerdefinierte 3D-Modelle aus assets/models/
  - 3 Material-Modi pro Objekt/Avatar:
      * MATT: Matter, diffuser Look
      * GLAS: Veredelter Klarlack-Glas-Look mit prozentualer Staerke
      * DURCHSICHTIGES_GLAS: Vollstaendig transparentes, lichtbrechendes Glas
  - Rendert in Cycles mit Live-Sample-Fortschritt
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ------------------------------------------------------------------------------
#  Hilfsfunktionen & Koordinaten-Transformation
# ------------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(str(msg), flush=True)


def cframe_to_blender_matrix(cf: list[float] | tuple[float, ...]):
    """Wandelt ein 12-teiliges Roblox-CFrame in eine 4x4 Blender-Transformationsmatrix um.

    Roblox CFrame: [x, y, z, R00, R01, R02, R10, R11, R12, R20, R21, R22]
    Roblox-Koordinaten: +X=Rechts, +Y=Oben, +Z=Hinten (-Z=Vorwaerts)
    Blender-Koordinaten: +X=Rechts, +Y=Vorwaerts/Tiefe, +Z=Oben
    """
    try:
        from mathutils import Matrix
    except ImportError:
        Matrix = None

    if not cf or len(cf) < 12:
        return Matrix.Identity(4) if Matrix else [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]

    x, y, z = float(cf[0]), float(cf[1]), float(cf[2])
    r00, r01, r02 = float(cf[3]), float(cf[4]), float(cf[5])
    r10, r11, r12 = float(cf[6]), float(cf[7]), float(cf[8])
    r20, r21, r22 = float(cf[9]), float(cf[10]), float(cf[11])

    # Blender-Spalten aus Roblox-Rotationsmatrix:
    # Col 0 (Roblox X): [r00, -r20, r10]
    # Col 1 (Roblox -Z): [-r02, r22, -r12]
    # Col 2 (Roblox Y): [r01, -r21, r11]
    # Position: [x, -z, y]
    rows = (
        (r00, -r02, r01, x),
        (-r20, r22, -r21, -z),
        (r10, -r12, r11, y),
        (0.0, 0.0, 0.0, 1.0)
    )
    if Matrix:
        return Matrix(rows)
    return rows


def roblox_pos_to_blender(pos: list[float] | tuple[float, ...]):
    try:
        from mathutils import Vector
    except ImportError:
        Vector = None
    if not pos or len(pos) < 3:
        return Vector((0.0, 0.0, 0.0)) if Vector else (0.0, 0.0, 0.0)
    res = (float(pos[0]), -float(pos[2]), float(pos[1]))
    return Vector(res) if Vector else res


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
    """Richtet die Welt mit HDRI oder Nishita-Himmel ein."""
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


def _setup_device(scene, device: str) -> str:
    """Waehlt CPU/GPU fuer Cycles."""
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
#  Material-Modi (MATT, GLAS, DURCHSICHTIGES_GLAS)
# ------------------------------------------------------------------------------

def apply_material_mode(material, mode: str = "GLAS", glass_strength: float = 0.85,
                        base_color: Optional[Tuple[float, float, float, float]] = None):
    """Passt ein Material an einen der 3 Material-Modi an:

      * MATT: Diffus, rau, matter Finish ohne Reflexionen
      * GLAS: Opaker Farb-/Texturkörper mit eleganter Klarlack-Schicht (glass_strength 0..1)
      * DURCHSICHTIGES_GLAS: Reales, transparentes lichtbrechendes Glas (Transmission 1.0)
    """
    if not material:
        return
    material.use_nodes = True
    mode_str = str(mode or "GLAS").strip().upper()

    # Normalisiere glass_strength (falls als 0..100 uebergeben)
    if glass_strength > 1.0:
        glass_strength = glass_strength / 100.0
    glass_strength = max(0.0, min(1.0, float(glass_strength)))

    tree = material.node_tree
    bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if not bsdf:
        bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
        out = next((n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"), None)
        if not out:
            out = tree.nodes.new("ShaderNodeOutputMaterial")
        tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    inputs = bsdf.inputs

    # Falls eine Basisfarbe angegeben wurde und kein Bild an Base Color haengt
    if base_color and not inputs["Base Color"].is_linked:
        inputs["Base Color"].default_value = base_color

    if mode_str in ("DURCHSICHTIGES_GLAS", "TRANSPARENT_GLAS", "CLEAR_GLASS"):
        # Modus 3: Reales, durchsichtiges Glas
        if hasattr(material, "blend_method"):
            material.blend_method = "BLEND"
        if "Transmission Weight" in inputs:
            inputs["Transmission Weight"].default_value = 1.0
        elif "Transmission" in inputs:
            inputs["Transmission"].default_value = 1.0
        if "Roughness" in inputs:
            inputs["Roughness"].default_value = 0.05
        if "IOR" in inputs:
            inputs["IOR"].default_value = 1.52
        for socket in ("Coat Weight", "Coat"):
            if socket in inputs:
                inputs[socket].default_value = glass_strength
        for socket in ("Coat Roughness", "Clearcoat Roughness"):
            if socket in inputs:
                inputs[socket].default_value = 0.02

    elif mode_str in ("MATT", "MATTE", "DIFFUSE"):
        # Modus 1: Matt
        if hasattr(material, "blend_method"):
            material.blend_method = "OPAQUE"
        if "Roughness" in inputs:
            inputs["Roughness"].default_value = 0.65
        if "IOR" in inputs:
            inputs["IOR"].default_value = 1.45
        for socket in ("Transmission Weight", "Transmission"):
            if socket in inputs:
                inputs[socket].default_value = 0.0
        for socket in ("Coat Weight", "Coat"):
            if socket in inputs:
                inputs[socket].default_value = 0.0

    else:
        # Modus 2: Glas (Standard, opak mit edler Glasur)
        if hasattr(material, "blend_method"):
            material.blend_method = "OPAQUE"
        if "Roughness" in inputs:
            inputs["Roughness"].default_value = 0.12
        if "IOR" in inputs:
            inputs["IOR"].default_value = 1.45
        for socket in ("Transmission Weight", "Transmission"):
            if socket in inputs:
                inputs[socket].default_value = 0.0
        for socket in ("Coat Weight", "Coat"):
            if socket in inputs:
                inputs[socket].default_value = glass_strength
        for socket in ("Coat Roughness", "Clearcoat Roughness"):
            if socket in inputs:
                inputs[socket].default_value = 0.04


def _create_color_material(name: str, color: Tuple[float, float, float, float],
                           mode: str = "GLAS", glass_strength: float = 0.85):
    import bpy
    mat = bpy.data.materials.new(name=name)
    apply_material_mode(mat, mode=mode, glass_strength=glass_strength, base_color=color)
    return mat


# ------------------------------------------------------------------------------
#  Knochen- und Part-Erkennung fuer Roblox Avatare
# ------------------------------------------------------------------------------

def _match_bone_for_obj(obj_name: str, center_z: float = 0.0, center_x: float = 0.0) -> str:
    """Ermittelt das zugehoerige R15-Koerperteil anhand des Namens oder der Position."""
    name_lower = obj_name.lower()
    for b in ("LeftUpperArm", "LeftLowerArm", "LeftHand",
              "RightUpperArm", "RightLowerArm", "RightHand",
              "LeftUpperLeg", "LeftLowerLeg", "LeftFoot",
              "RightUpperLeg", "RightLowerLeg", "RightFoot",
              "UpperTorso", "LowerTorso", "Head", "Torso", "Left Arm", "Right Arm", "Left Leg", "Right Leg"):
        if b.lower() in name_lower:
            return b

    if any(k in name_lower for k in ("hat", "hair", "face", "glass", "horn", "cap")):
        return "Head"
    if any(k in name_lower for k in ("back", "wing", "cape", "shoulder", "sword", "shield")):
        return "UpperTorso"

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
#  Szenen-Aufbau: Avatare, Custom-Modelle, Herz-Haende
# ------------------------------------------------------------------------------

def _find_custom_model_file(model_name: str, search_dirs: list[Path]) -> Optional[Path]:
    """Sucht nach einer benutzerdefinierten 3D-Datei im Repository."""
    if not model_name:
        return None
    extensions = (".obj", ".glb", ".gltf", ".fbx")
    cleaned = Path(model_name).stem.lower()

    for directory in search_dirs:
        if not directory.is_dir():
            continue
        # Exakte Uebereinstimmung
        for ext in extensions:
            cand = directory / f"{model_name}{ext}"
            if cand.is_file():
                return cand
        # Case-insensitive Suche
        for f in directory.iterdir():
            if f.is_file() and f.stem.lower() == cleaned and f.suffix.lower() in extensions:
                return f
    return None


def _import_obj_mesh(filepath: Path) -> list:
    """Importiert eine OBJ-Datei in die aktuelle Szene und gibt alle neuen Meshes zurueck."""
    import bpy
    before = set(bpy.context.scene.objects)
    bpy.ops.wm.obj_import(filepath=str(filepath))
    after = set(bpy.context.scene.objects)
    return [o for o in (after - before) if o.type == "MESH"]


def _process_avatar(scene, avatar_spec: dict, repo_root: Path, all_scene_meshes: list):
    """Laedt einen Avatar, wendet die Posen aller Koerperteile an und fuegt Herz-Haende ein."""
    import bpy
    from math import radians
    from mathutils import Matrix, Vector

    username = avatar_spec.get("username", "Avatar")
    model_dir_str = avatar_spec.get("model_dir")
    model_dir = Path(model_dir_str) if model_dir_str else repo_root / "data" / "jobs" / "model"
    
    mat_mode = avatar_spec.get("material_mode", "GLAS")
    glass_strength = float(avatar_spec.get("glass_strength", 0.85))
    heart_hands = bool(avatar_spec.get("heart_hands", False))
    skin_color_list = avatar_spec.get("skin_color") or [245, 205, 170]
    skin_color_rgba = (
        skin_color_list[0] / 255.0,
        skin_color_list[1] / 255.0,
        skin_color_list[2] / 255.0,
        1.0,
    )
    parts_data = avatar_spec.get("parts") or {}

    obj_file = model_dir / "avatar.obj"
    if not obj_file.is_file():
        # Suche nach beliebigem OBJ im Ordner
        objs = list(model_dir.glob("*.obj"))
        if objs:
            obj_file = objs[0]
        else:
            _log(f"[Blender] Warnung: Kein OBJ fuer Avatar '{username}' in {model_dir} gefunden.")
            return

    _log(f"[Blender] Lade Avatar '{username}' aus {obj_file.name} (Modus: {mat_mode}, Herz-Haende: {heart_hands}) ...")
    avatar_meshes = _import_obj_mesh(obj_file)
    if not avatar_meshes:
        return

    # Grundausrichtung des OBJ (Roblox Y-hoch -> Blender Z-hoch)
    bpy.ops.object.select_all(action="DESELECT")
    for m in avatar_meshes:
        m.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    
    mn, mx = _world_bbox(avatar_meshes)
    if (mx.y - mn.y) > (mx.z - mn.z) * 1.3 and (mx.y - mn.y) > (mx.x - mn.x):
        for m in avatar_meshes:
            m.rotation_euler.rotate_axis("X", radians(90))
        bpy.context.view_layer.update()
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    # Koerperteil-Zuordnung & Posing
    left_hand_cframe = None
    right_hand_cframe = None

    kept_avatar_meshes = []
    for obj in avatar_meshes:
        obj_mn, obj_mx = _world_bbox([obj])
        obj_center = (obj_mn + obj_mx) / 2
        bone_name = _match_bone_for_obj(obj.name, obj_center.z, obj_center.x)

        # Bei Herz-Haenden werden die Original-Haende geloescht
        if heart_hands and bone_name in ("LeftHand", "RightHand"):
            # Speichere die CFrame der Haende fuer die Positionierung des Herz-Modells
            if bone_name == "LeftHand" and "LeftHand" in parts_data:
                left_hand_cframe = parts_data["LeftHand"].get("cframe")
            if bone_name == "RightHand" and "RightHand" in parts_data:
                right_hand_cframe = parts_data["RightHand"].get("cframe")
            bpy.data.objects.remove(obj, do_unlink=True)
            continue

        kept_avatar_meshes.append(obj)

        # Wenn Posen-Daten fuer dieses Koerperteil vorhanden sind -> transformieren
        if bone_name in parts_data and parts_data[bone_name].get("cframe"):
            cf = parts_data[bone_name]["cframe"]
            target_matrix = cframe_to_blender_matrix(cf)
            
            # Ursprung auf Zentrum setzen und an Zielmatrix ausrichten
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
            obj.matrix_world = target_matrix
        elif avatar_spec.get("cframe"):
            # Fallback: gesamter Avatar an Basis-CFrame
            obj.matrix_world = cframe_to_blender_matrix(avatar_spec["cframe"])

        # Material anpassen
        for mat in obj.data.materials:
            if mat:
                apply_material_mode(mat, mode=mat_mode, glass_strength=glass_strength)
        
        for poly in obj.data.polygons:
            poly.use_smooth = True

    all_scene_meshes.extend(kept_avatar_meshes)

    # Herz-Haende einfuegen, falls gewuenscht
    if heart_hands:
        hands_file = _find_custom_model_file("heart_hands", [
            repo_root / "assets" / "models",
            repo_root / "assets" / "hands",
            repo_root / "assets",
        ])
        if hands_file and hands_file.is_file():
            _log(f"[Blender] Fuege Herz-Haende ({hands_file.name}) fuer '{username}' ein ...")
            hand_meshes = _import_obj_mesh(hands_file)
            
            # Positionierung: Mitte zwischen linker und rechter Hand
            if left_hand_cframe and right_hand_cframe:
                m_l = cframe_to_blender_matrix(left_hand_cframe)
                m_r = cframe_to_blender_matrix(right_hand_cframe)
                pos_mid = (m_l.to_translation() + m_r.to_translation()) / 2.0
                target_mat = m_l.copy()
                target_mat.translation = pos_mid
            elif left_hand_cframe:
                target_mat = cframe_to_blender_matrix(left_hand_cframe)
            elif right_hand_cframe:
                target_mat = cframe_to_blender_matrix(right_hand_cframe)
            elif "UpperTorso" in parts_data and parts_data["UpperTorso"].get("cframe"):
                # Vor die Brust platzieren
                m_torso = cframe_to_blender_matrix(parts_data["UpperTorso"]["cframe"])
                target_mat = m_torso.copy()
                target_mat.translation = target_mat.translation + target_mat.to_3x3() @ Vector((0.0, 0.6, 0.0))
            else:
                target_mat = Matrix.Translation((0.0, 0.0, 3.5))

            skin_mat = _create_color_material(
                f"HeartSkin_{username}",
                skin_color_rgba,
                mode=mat_mode,
                glass_strength=glass_strength
            )

            for hm in hand_meshes:
                bpy.context.view_layer.objects.active = hm
                bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
                hm.matrix_world = target_mat
                hm.data.materials.clear()
                hm.data.materials.append(skin_mat)
                for poly in hm.data.polygons:
                    poly.use_smooth = True
                all_scene_meshes.append(hm)


def _process_custom_object(scene, obj_spec: dict, repo_root: Path, all_scene_meshes: list):
    """Laedt ein benutzerdefiniertes 3D-Modell (MeshPart) oder erzeugt eine Box."""
    import bpy
    from mathutils import Matrix, Vector

    model_name = obj_spec.get("model_name") or obj_spec.get("name", "CustomPart")
    mat_mode = obj_spec.get("material_mode", "MATT")
    glass_strength = float(obj_spec.get("glass_strength", 0.85))
    size = obj_spec.get("size") or [1.0, 1.0, 1.0]
    color_list = obj_spec.get("color") or [200, 200, 200]
    color_rgba = (
        color_list[0] / 255.0,
        color_list[1] / 255.0,
        color_list[2] / 255.0,
        1.0,
    )
    cf = obj_spec.get("cframe")
    target_matrix = cframe_to_blender_matrix(cf) if cf else Matrix.Identity(4)

    # Suche in assets/models und assets/
    model_file = _find_custom_model_file(model_name, [
        repo_root / "assets" / "models",
        repo_root / "assets" / "hands",
        repo_root / "assets",
    ])

    if model_file and model_file.is_file():
        _log(f"[Blender] Lade Custom-Modell '{model_name}' aus {model_file.name} ...")
        meshes = _import_obj_mesh(model_file)
        if meshes:
            for m in meshes:
                bpy.context.view_layer.objects.active = m
                bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
                m.matrix_world = target_matrix
                
                # Skalierung anhand Roblox Size anpassen
                if size:
                    # In Blender: x=sx, y=sz, z=sy
                    sx, sy, sz = float(size[0]), float(size[1]), float(size[2])
                    m.scale = (sx, sz, sy)

                if not m.data.materials:
                    mat = _create_color_material(f"Mat_{model_name}", color_rgba, mode=mat_mode, glass_strength=glass_strength)
                    m.data.materials.append(mat)
                else:
                    for mat in m.data.materials:
                        if mat:
                            apply_material_mode(mat, mode=mat_mode, glass_strength=glass_strength)

                for poly in m.data.polygons:
                    poly.use_smooth = True
                all_scene_meshes.append(m)
            return

    # Fallback: erstelle primitive Box mit Roblox-Farbe und Material
    _log(f"[Blender] Erstelle Primitive fuer Part '{model_name}' (Farbe: {color_list}, Modus: {mat_mode}) ...")
    sx, sy, sz = float(size[0]), float(size[1]), float(size[2])
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    cube = bpy.context.active_object
    cube.name = model_name
    cube.scale = (sx, sz, sy)
    cube.matrix_world = target_matrix
    
    mat = _create_color_material(f"Mat_{model_name}", color_rgba, mode=mat_mode, glass_strength=glass_strength)
    cube.data.materials.append(mat)
    all_scene_meshes.append(cube)


# ------------------------------------------------------------------------------
#  Hauptfunktion
# ------------------------------------------------------------------------------

def render_scene(params: dict, progress=None) -> None:
    """Rendert die vollstaendige Szene (Avatare, Custom-Modelle, Posen) in Cycles."""
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
    device = str(params.get("device", "CPU")).upper()
    repo_root = Path(__file__).resolve().parent.parent

    # 1) Frische, leere Szene ---------------------------------------------------
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    report("loading", 0.05)

    # 2) Manifest / Szene laden ------------------------------------------------
    scene_file = input_dir / "scene.json"
    manifest_file = input_dir / "manifest.json"
    
    scene_data: Dict[str, Any] = {}
    if scene_file.is_file():
        try:
            scene_data = json.loads(scene_file.read_text(encoding="utf-8"))
        except Exception as exc:
            _log(f"[Blender] Fehler beim Lesen von scene.json: {exc}")
    elif manifest_file.is_file():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            scene_data = {
                "avatars": [{
                    "username": manifest.get("username", "Avatar"),
                    "model_dir": str(input_dir),
                    "material_mode": params.get("material", "GLAS"),
                    "glass_strength": 0.85,
                    "heart_hands": False,
                }]
            }
        except Exception:
            pass

    if not scene_data.get("avatars") and not scene_data.get("objects"):
        # Fallback auf Standard-Avatar im input_dir
        scene_data = {
            "avatars": [{
                "username": "Default",
                "model_dir": str(input_dir),
                "material_mode": params.get("material", "GLAS"),
                "glass_strength": 0.85,
                "heart_hands": False,
            }]
        }

    all_scene_meshes = []
    report("loading", 0.2)

    # 3) Avatare laden und posieren --------------------------------------------
    avatars_list = scene_data.get("avatars") or []
    for av_spec in avatars_list:
        _process_avatar(scene, av_spec, repo_root, all_scene_meshes)

    report("loading", 0.5)

    # 4) Custom 3D Modelle & Parts laden ---------------------------------------
    objects_list = scene_data.get("objects") or []
    for obj_spec in objects_list:
        _process_custom_object(scene, obj_spec, repo_root, all_scene_meshes)

    if not all_scene_meshes:
        raise RuntimeError("In der Szene wurden keine 3D-Objekte oder Avatare gefunden.")

    _log(f"[Blender] Gesamt geladen: {len(all_scene_meshes)} 3D-Meshes.")
    report("loading", 0.7)

    # 5) Licht & Welt ----------------------------------------------------------
    environment_path = repo_root / "sunset_jhbcentral_4k.exr"
    _setup_world(scene, environment_path)
    
    # 3-Punkt-Beleuchtung
    mn, mx = _world_bbox(all_scene_meshes)
    center = (mn + mx) / 2.0
    radius = max(mx.x - mn.x, mx.y - mn.y, mx.z - mn.z) / 2.0 or 1.0

    _add_area_light(scene, "BRS_Key", 600, 4.0, (1.5, -1.3, 1.7), radius * 3.5)
    _add_area_light(scene, "BRS_Rim", 350, 3.0, (-1.7, 1.3, 1.0), radius * 3.5)
    _add_area_light(scene, "BRS_Fill", 180, 6.0, (-0.6, -1.7, 0.3), radius * 4.0)

    # 6) Kamera einrichten ------------------------------------------------------
    cam_data = bpy.data.cameras.new("BRS_Cam")
    camera = bpy.data.objects.new("BRS_Cam", cam_data)
    scene.collection.objects.link(camera)
    scene.camera = camera

    cam_spec = scene_data.get("camera") or {}
    fov_deg = float(cam_spec.get("fov", 32.0))
    cam_data.lens_unit = "FOV"
    cam_data.angle = radians(fov_deg)

    if cam_spec.get("position") and cam_spec.get("position") != [0, 0, 0]:
        # Benutzerdefinierte Kameraposition
        cam_pos = roblox_pos_to_blender(cam_spec["position"])
        target_pos = roblox_pos_to_blender(cam_spec.get("target", [0, 0, 0]))
        camera.location = cam_pos
        aim = (target_pos - cam_pos).normalized()
        camera.rotation_euler = aim.to_track_quat("-Z", "Y").to_euler()
    else:
        # Standard: Kamera bei (0,0,0) in Richtung der Szene / Vorwaerts (+Y)
        distance = radius / tan(radians(fov_deg) / 2.0) * 1.3 + radius * 0.5
        direction = Vector((0.0, -1.0, 0.08)).normalized()
        camera.location = center + direction * distance
        aim = (center - camera.location).normalized()
        camera.rotation_euler = aim.to_track_quat("-Z", "Y").to_euler()

    report("loading", 0.9)

    # 7) Render-Einstellungen (Cycles) ------------------------------------------
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

    # 8) Rendern ----------------------------------------------------------------
    _log(f"[Blender] Rendern startet ({width}x{height}, {samples} Samples, {used_device}) ...")
    report("rendering", 0.0)
    bpy.ops.render.render(write_still=True)
    report("rendering", 1.0)
    _log(f"[Blender] Fertig! Render-Bild gespeichert: {output}")


# ------------------------------------------------------------------------------
#  CLI
# ------------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Roblox-Szene mit Avataren, Posen und Custom-Modellen rendern")
    parser.add_argument("--input", required=True, help="Ordner mit scene.json / avatar.obj")
    parser.add_argument("--output", required=True, help="Ziel-PNG")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--samples", type=int, default=96)
    parser.add_argument("--material", default="GLAS")
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
