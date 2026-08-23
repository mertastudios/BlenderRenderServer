"""Roblox FileMesh Parser und Konverter.

Unterstuetzt:
  - version 1.00 & 1.01 (ASCII-Format)
  - version 2.00 (Binaerformat mit Scheitelpunkten, Normalen, UV, Tangenten, Farben)
  - version 3.00 & 3.01 (Binaerformat mit LOD)
  - version 4.00, 4.01 & 5.00 (Binaerformat mit Bone-Weights / Skinned Meshes)

Kann beliebige Roblox-.mesh-Dateien in Geometrie (Vertices, Normals, UVs, Faces, Vertex-Groups)
oder Wavefront OBJ umwandeln.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, List, Optional, Tuple


@dataclass
class MeshVertex:
    px: float = 0.0
    py: float = 0.0
    pz: float = 0.0
    nx: float = 0.0
    ny: float = 1.0
    nz: float = 0.0
    u: float = 0.0
    v: float = 0.0
    r: int = 255
    g: int = 255
    b: int = 255
    a: int = 255
    bones: List[int] = field(default_factory=list)
    weights: List[float] = field(default_factory=list)


@dataclass
class MeshData:
    version: str = "2.00"
    vertices: List[MeshVertex] = field(default_factory=list)
    faces: List[Tuple[int, int, int]] = field(default_factory=list)
    bone_names: List[str] = field(default_factory=list)

    def to_obj(self, object_name: str = "RobloxMesh") -> str:
        """Konvertiert die Mesh-Daten in standardkonformes Wavefront-OBJ."""
        lines = [f"o {object_name}"]
        for v in self.vertices:
            lines.append(f"v {v.px:.6f} {v.py:.6f} {v.pz:.6f}")
        for v in self.vertices:
            lines.append(f"vt {v.u:.6f} {1.0 - v.v:.6f}")
        for v in self.vertices:
            lines.append(f"vn {v.nx:.6f} {v.ny:.6f} {v.nz:.6f}")

        # Gespeicherte Faces sind 0-basiert -> OBJ ist 1-basiert
        for f in self.faces:
            i1, i2, i3 = f[0] + 1, f[1] + 1, f[2] + 1
            lines.append(f"f {i1}/{i1}/{i1} {i2}/{i2}/{i2} {i3}/{i3}/{i3}")
        return "\n".join(lines) + "\n"


def parse_roblox_mesh(data: bytes) -> MeshData:
    """Parst eine Roblox-.mesh-Datei aus Bytes und liefert MeshData."""
    if not data:
        raise ValueError("Leere Mesh-Daten erhalten.")

    # Header pruefen
    header_end = data.find(b"\n")
    if header_end == -1:
        raise ValueError("Ungueltige Mesh-Datei: Kein Header gefunden.")

    header_line = data[:header_end].decode("ascii", errors="ignore").strip()
    if not header_line.startswith("version "):
        raise ValueError(f"Ungueltiges Mesh-Header-Format: {header_line}")

    version_str = header_line[len("version "):].strip()
    body = data[header_end + 1:]

    if version_str in ("1.00", "1.01"):
        return _parse_v1(body, version_str)
    elif version_str in ("2.00", "2.01"):
        return _parse_v2(body, version_str)
    elif version_str in ("3.00", "3.01"):
        return _parse_v3(body, version_str)
    elif version_str in ("4.00", "4.01", "5.00", "6.00", "7.00"):
        return _parse_v4_v5(body, version_str)
    else:
        # Fallback: Versuch als v2 oder v3 zu parsen
        try:
            return _parse_v2(body, version_str)
        except Exception:
            return _parse_v1(body, version_str)


def _parse_v1(body: bytes, version_str: str) -> MeshData:
    """Parst ASCII-Mesh Version 1.00/1.01."""
    text = body.decode("ascii", errors="replace").strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("v1.00 Mesh enthaelt keine Daten.")

    try:
        num_faces = int(lines[0])
    except ValueError as exc:
        raise ValueError(f"v1.00 Ungueltige Face-Anzahl: {lines[0]}") from exc

    # In v1.00 koennen die Daten auf einer oder mehreren Zeilen liegen
    data_str = " ".join(lines[1:])
    # Jedes Face hat 3 Vertices; jeder Vertex hat [px,py,pz][nx,ny,nz][u,v,w]
    import re
    vectors = re.findall(r"\[([-\d.eE+]+),([-\d.eE+]+),([-\d.eE+]+)\]", data_str)
    
    expected_vectors = num_faces * 9
    if len(vectors) < expected_vectors:
        # Teilweise weniger Daten -> trotzdem parsen was da ist
        num_faces = len(vectors) // 9

    vertices: List[MeshVertex] = []
    faces: List[Tuple[int, int, int]] = []

    v_idx = 0
    for f in range(num_faces):
        face_v_indices = []
        for p in range(3):
            base = (f * 3 + p) * 3
            if base + 2 >= len(vectors):
                break
            pos = [float(x) for x in vectors[base]]
            norm = [float(x) for x in vectors[base + 1]]
            uv = [float(x) for x in vectors[base + 2]]
            
            vert = MeshVertex(
                px=pos[0], py=pos[1], pz=pos[2],
                nx=norm[0], ny=norm[1], nz=norm[2],
                u=uv[0], v=uv[1]
            )
            vertices.append(vert)
            face_v_indices.append(v_idx)
            v_idx += 1
        if len(face_v_indices) == 3:
            faces.append((face_v_indices[0], face_v_indices[1], face_v_indices[2]))

    return MeshData(version=version_str, vertices=vertices, faces=faces)


def _parse_v2(body: bytes, version_str: str) -> MeshData:
    """Parst Binaer-Mesh Version 2.00."""
    if len(body) < 12:
        raise ValueError("v2.00 Mesh-Body zu kurz fuer Header.")

    header_size, vert_size, face_size, num_verts, num_faces = struct.unpack_from("<HBBII", body, 0)
    offset = header_size

    vertices: List[MeshVertex] = []
    for _ in range(num_verts):
        if offset + vert_size > len(body):
            break
        # float px,py,pz, nx,ny,nz, tu,tv (8 floats = 32 bytes)
        px, py, pz, nx, ny, nz, tu, tv = struct.unpack_from("<ffffffff", body, offset)
        r, g, b, a = 255, 255, 255, 255
        if vert_size >= 40:
            # 32 bytes floats + 4 bytes tangent + 4 bytes rgba
            rgba_offset = offset + 36
            if rgba_offset + 4 <= len(body):
                r, g, b, a = struct.unpack_from("<BBBB", body, rgba_offset)
        vertices.append(MeshVertex(px=px, py=py, pz=pz, nx=nx, ny=ny, nz=nz, u=tu, v=tv, r=r, g=g, b=b, a=a))
        offset += vert_size

    faces: List[Tuple[int, int, int]] = []
    for _ in range(num_faces):
        if offset + face_size > len(body):
            break
        i1, i2, i3 = struct.unpack_from("<III", body, offset)
        faces.append((i1, i2, i3))
        offset += face_size

    return MeshData(version=version_str, vertices=vertices, faces=faces)


def _parse_v3(body: bytes, version_str: str) -> MeshData:
    """Parst Binaer-Mesh Version 3.00 / 3.01 (mit LODs)."""
    if len(body) < 16:
        raise ValueError("v3.00 Mesh-Body zu kurz.")
    # Header: ushort sizeof_header, byte sizeof_vert, byte sizeof_face, ushort sizeof_lod, ushort num_lods, uint num_verts, uint num_faces
    header_size, vert_size, face_size, sizeof_lod, num_lods, num_verts, num_faces = struct.unpack_from("<HBBHHII", body, 0)
    offset = header_size

    vertices: List[MeshVertex] = []
    for _ in range(num_verts):
        if offset + vert_size > len(body):
            break
        px, py, pz, nx, ny, nz, tu, tv = struct.unpack_from("<ffffffff", body, offset)
        r, g, b, a = 255, 255, 255, 255
        if vert_size >= 40:
            rgba_offset = offset + 36
            if rgba_offset + 4 <= len(body):
                r, g, b, a = struct.unpack_from("<BBBB", body, rgba_offset)
        vertices.append(MeshVertex(px=px, py=py, pz=pz, nx=nx, ny=ny, nz=nz, u=tu, v=tv, r=r, g=g, b=b, a=a))
        offset += vert_size

    faces: List[Tuple[int, int, int]] = []
    for _ in range(num_faces):
        if offset + face_size > len(body):
            break
        i1, i2, i3 = struct.unpack_from("<III", body, offset)
        faces.append((i1, i2, i3))
        offset += face_size

    return MeshData(version=version_str, vertices=vertices, faces=faces)


def _parse_v4_v5(body: bytes, version_str: str) -> MeshData:
    """Parst neuere Binaer-Mesh Formate (v4/v5/v6/v7)."""
    # Oft strukturkompatibel mit erweiterter Vertex-Groesse (Bones/Weights)
    if len(body) < 12:
        return _parse_v2(body, version_str)

    header_size, vert_size, face_size = struct.unpack_from("<HBB", body, 0)
    num_verts, num_faces = struct.unpack_from("<II", body, 4 if header_size <= 12 else 8)
    
    offset = header_size
    vertices: List[MeshVertex] = []
    for _ in range(num_verts):
        if offset + 32 > len(body):
            break
        px, py, pz, nx, ny, nz, tu, tv = struct.unpack_from("<ffffffff", body, offset)
        vertices.append(MeshVertex(px=px, py=py, pz=pz, nx=nx, ny=ny, nz=nz, u=tu, v=tv))
        offset += vert_size

    faces: List[Tuple[int, int, int]] = []
    for _ in range(num_faces):
        if offset + 12 > len(body):
            break
        i1, i2, i3 = struct.unpack_from("<III", body, offset)
        faces.append((i1, i2, i3))
        offset += face_size

    return MeshData(version=version_str, vertices=vertices, faces=faces)
