"""Load 3D models into a uniform list of coloured triangle parts.

Formats: DAE (pycollada, keeps material and texture names), glTF/GLB, OBJ, STL, PLY, OFF (trimesh).
Every part carries world-space vertices, triangle indices and one colour source: a texture with UVs,
per-vertex colours, or a flat base colour. Source files are untrusted data: nothing is executed.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

import numpy as np

SUPPORTED = (".dae", ".gltf", ".glb", ".obj", ".stl", ".ply", ".off")
DEFAULT_UP = {".dae": "y", ".gltf": "y", ".glb": "y", ".obj": "y", ".stl": "z", ".ply": "z", ".off": "y"}
_SUFFIX = re.compile(r"([_.\-]\d+)+$")


@dataclass
class MeshPart:
    name: str
    material: str  # material name plus texture file name, e.g. "Brick [3td_BrickOld_34.jpg]"
    vertices: np.ndarray  # float64 (n, 3), source frame
    faces: np.ndarray  # int64 (m, 3)
    uv: np.ndarray | None = None  # float64 (n, 2), OpenGL convention (v up)
    texture: np.ndarray | None = None  # uint8 (H, W, 3) or (H, W, 4) when the texture has transparency
    vertex_rgb: np.ndarray | None = None  # uint8 (n, 3)
    base_rgb: tuple[int, int, int] | None = None

    @property
    def tris(self) -> int:
        return int(len(self.faces))


@dataclass
class Model:
    path: Path
    parts: list[MeshPart] = field(default_factory=list)
    up: str = "y"  # up axis of the source frame
    unit: str = ""

    def bounds(self) -> np.ndarray:
        allv = np.concatenate([p.vertices for p in self.parts]) if self.parts else np.zeros((1, 3))
        return np.stack([allv.min(axis=0), allv.max(axis=0)])


def part_key(name: str) -> str:
    """Strip numeric suffixes so geom-Wall_1 .. geom-Wall_80 become one logical part."""
    return _SUFFIX.sub("", name) or name


def _rgb8(color) -> tuple[int, int, int] | None:
    if color is None:
        return None
    c = np.asarray(color, np.float64).ravel()[:3]
    if c.max() <= 1.0:
        c = c * 255.0
    return tuple(int(v) for v in np.clip(np.rint(c), 0, 255))  # type: ignore[return-value]


def _image_array(img) -> np.ndarray | None:
    """RGB array, or RGBA when the image has meaningful transparency (cut-out leaves, vines, fences)."""
    if img is None:
        return None
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = np.asarray(img.convert("RGBA"), np.uint8)
        if (rgba[..., 3] < 128).any():
            return rgba
    return np.asarray(img.convert("RGB"), np.uint8)


def load_model(path: Path | str) -> Model:
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"{path.name}: unsupported format (use one of {', '.join(SUPPORTED)}, or .vox / .txt)")
    model = _load_dae(path) if ext == ".dae" else _load_trimesh(path)
    model.parts = [p for p in model.parts if p.tris > 0]
    if not model.parts:
        raise ValueError(f"{path.name}: no triangles found")
    return model


def _resolve_image(base: Path, ref: str):
    from PIL import Image

    raw = unquote(ref.replace("file://", "")).replace("\\", "/")
    for cand in (base / raw, base / os.path.basename(raw)):
        try:
            if cand.is_file():
                return Image.open(cand)
        except OSError:
            continue
    return None


def _load_dae(path: Path) -> Model:
    import collada
    from collada import common

    c = collada.Collada(str(path), ignore=[common.DaeUnsupportedError, common.DaeBrokenRefError])
    up = {"X_UP": "x", "Y_UP": "y", "Z_UP": "z"}.get(getattr(c.assetInfo, "upaxis", "Y_UP"), "y")
    unit = getattr(c.assetInfo, "unitname", "") or ""
    model = Model(path=path, up=up, unit=unit)
    images: dict[str, np.ndarray | None] = {}
    geoms = list(c.scene.objects("geometry")) if c.scene is not None else []
    for g in geoms:
        gname = getattr(g.original, "name", None) or getattr(g.original, "id", "geometry")
        for prim in g.primitives():
            if hasattr(prim, "triangleset") and not hasattr(prim, "vertex_index"):
                continue
            tri = prim.triangleset() if hasattr(prim, "triangleset") else prim
            if tri.vertex is None or tri.vertex_index is None or len(tri.vertex_index) == 0:
                continue
            vi = np.asarray(tri.vertex_index, np.int64).reshape(-1, 3)
            verts = np.asarray(tri.vertex, np.float64)[vi].reshape(-1, 3)
            faces = np.arange(len(verts), dtype=np.int64).reshape(-1, 3)
            part = MeshPart(name=str(gname), material="", vertices=verts, faces=faces)
            ts, tis = tri.texcoordset, tri.texcoord_indexset
            if len(ts) and len(tis) and tis[0] is not None and len(tis[0]):
                ti = np.asarray(tis[0], np.int64).reshape(-1, 3)
                part.uv = np.asarray(ts[0], np.float64)[ti].reshape(-1, 2)
            mat = tri.material
            matname, texname = "", ""
            if mat is not None and not isinstance(mat, str):
                matname = getattr(mat, "name", None) or getattr(mat, "id", "") or ""
                diffuse = getattr(getattr(mat, "effect", None), "diffuse", None)
                if isinstance(diffuse, tuple | list):
                    part.base_rgb = _rgb8(diffuse)
                elif diffuse is not None and hasattr(diffuse, "sampler"):
                    try:
                        ref = diffuse.sampler.surface.image.path
                    except AttributeError:
                        ref = ""
                    if ref:
                        texname = os.path.basename(unquote(ref).replace("\\", "/"))
                        if ref not in images:
                            images[ref] = _image_array(_resolve_image(path.parent, ref))
                        part.texture = images[ref]
                        if part.uv is None:
                            part.texture = None
            elif isinstance(mat, str):
                matname = mat
            part.material = f"{matname} [{texname}]" if texname else matname
            model.parts.append(part)
    return model


def _load_trimesh(path: Path) -> Model:
    import trimesh
    from trimesh import resolvers

    class BasenameResolver(resolvers.FilePathResolver):
        def get(self, name):
            try:
                return super().get(name)
            except Exception:
                return super().get(os.path.basename(unquote(name).replace("\\", "/")))

    scene = trimesh.load(str(path), force="scene", resolver=BasenameResolver(str(path.parent)), process=False)
    model = Model(path=path, up=DEFAULT_UP[path.suffix.lower()])
    images: dict[int, np.ndarray | None] = {}
    for node in scene.graph.nodes_geometry:
        transform, gname = scene.graph[node]
        g = scene.geometry[gname]
        if not isinstance(g, trimesh.Trimesh) or len(g.faces) == 0:
            continue
        verts = trimesh.transform_points(np.asarray(g.vertices, np.float64), transform)
        part = MeshPart(name=str(node), material="", vertices=verts, faces=np.asarray(g.faces, np.int64))
        vis = g.visual
        if vis.kind == "texture":
            mat = vis.material
            name = getattr(mat, "name", None) or ""
            img = getattr(mat, "baseColorTexture", None) if hasattr(mat, "baseColorTexture") else None
            if img is None:
                img = getattr(mat, "image", None)
            factor = getattr(mat, "baseColorFactor", None)
            if factor is None:
                factor = getattr(mat, "diffuse", None)
            if img is not None and vis.uv is not None:
                if id(img) not in images:
                    images[id(img)] = _image_array(img)
                part.texture = images[id(img)]
                part.uv = np.asarray(vis.uv, np.float64)
                f = _rgb8(factor)
                tinted = f is not None and f != (255, 255, 255) and hasattr(mat, "baseColorFactor")
                if tinted and part.texture is not None:
                    tex = part.texture.astype(np.float32)
                    tex[..., :3] *= np.array(f) / 255.0
                    part.texture = tex.astype(np.uint8)
            else:
                part.base_rgb = _rgb8(factor) if factor is not None else _rgb8(getattr(mat, "main_color", None))
            part.material = name
        elif vis.kind in ("vertex", "face"):
            vc = np.asarray(vis.vertex_colors, np.uint8)
            if len(vc) == len(verts):
                part.vertex_rgb = vc[:, :3]
        model.parts.append(part)
    return model


def apply_texture(model: Model, image_path: Path, alpha: str = "cutout") -> int:
    """Give every UV-mapped part without a texture this image (0 A.D. actors define textures outside
    the mesh). With alpha == "ignore" the alpha channel of all textures is dropped. Returns parts changed."""
    from PIL import Image

    changed = 0
    tex = None
    if image_path:
        with Image.open(image_path) as img:
            tex = _image_array(img)
    for p in model.parts:
        if tex is not None and p.texture is None and p.uv is not None:
            p.texture = tex
            changed += 1
        if alpha == "ignore" and p.texture is not None and p.texture.shape[-1] == 4:
            p.texture = np.ascontiguousarray(p.texture[..., :3])
    return changed


def inspect(model: Model) -> dict:
    b = model.bounds()
    ext = b[1] - b[0]
    return {
        "file": str(model.path),
        "up": model.up,
        "unit": model.unit or "-",
        "extents": [round(float(v), 4) for v in ext],
        "triangles": int(sum(p.tris for p in model.parts)),
        "parts": [
            {
                "name": p.name,
                "material": p.material,
                "tris": p.tris,
                "texture": None if p.texture is None else f"{p.texture.shape[1]}x{p.texture.shape[0]}",
                "color": "vertex"
                if p.vertex_rgb is not None
                else (p.base_rgb and "#{:02x}{:02x}{:02x}".format(*p.base_rgb)),
            }
            for p in model.parts
        ],
    }
