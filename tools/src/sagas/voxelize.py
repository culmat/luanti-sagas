"""Colour-aware surface voxelizer (numpy only; no OpenGL, no Blender).

Each triangle is sampled on a barycentric lattice dense enough that samples are at most
1/supersample voxels apart; every sample votes for the voxel it falls into. A voxel's colour is the
mean of its samples, its part is the part with most samples, its normal class the majority of the
triangle normals (up / down / side). The result is a shell; `mode = "solid"` fills enclosed space.

Frames: the source frame is converted to right-handed Y-up, voxelized, then the X axis is flipped
(Luanti is left-handed), and finally rotate_y / mirror are applied on the voxel grid.
"""

from __future__ import annotations

import fnmatch

import numpy as np
from scipy import ndimage

from .config import Transform, Voxel
from .load import MeshPart, Model, part_key
from .ruin import remove_small
from .voxels import NORMAL_DOWN, NORMAL_SIDE, NORMAL_UP, VoxelModel, orient

MAX_SAMPLES = 60_000_000
CHUNK = 1_500_000  # samples per batch

_UP = {
    "y": np.eye(3),
    "z": np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float),  # (x, y, z) -> (x, z, -y)
    "x": np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float),  # (x, y, z) -> (-y, x, z)
    "-y": np.array([[1, 0, 0], [0, -1, 0], [0, 0, -1]], float),
    "-z": np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float),  # (x, y, z) -> (x, -z, y)
    "-x": np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1]], float),  # (x, y, z) -> (y, -x, z)
}


def excluded(part: MeshPart, patterns: list[str]) -> bool:
    name, mat = part.name.lower(), part.material.lower()
    return any(fnmatch.fnmatchcase(name, p.lower()) or fnmatch.fnmatchcase(mat, p.lower()) for p in patterns)


def _lattice(n: int) -> np.ndarray:
    ij = [(i, j) for i in range(n + 1) for j in range(n + 1 - i)]
    a = np.array(ij, np.float64) / n
    return np.column_stack([1.0 - a[:, 0] - a[:, 1], a[:, 0], a[:, 1]])  # (S, 3) weights for v0, v1, v2


def _sample_colors(
    part: MeshPart, tri_idx: np.ndarray, w: np.ndarray, faces: np.ndarray
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """(colours (k*S, 3) uint8 or None, keep mask or None) for the samples of triangles tri_idx.

    Samples on transparent texels (alpha < 128) are dropped: they are holes in cut-out textures."""
    f = faces[tri_idx]  # (k, 3)
    if part.texture is not None and part.uv is not None:
        uv = np.einsum("sv,kvc->ksc", w, part.uv[f]).reshape(-1, 2)
        h, wdt = part.texture.shape[:2]
        u = uv[:, 0] - np.floor(uv[:, 0])
        v = uv[:, 1] - np.floor(uv[:, 1])
        px = np.minimum((u * wdt).astype(np.int64), wdt - 1)
        py = np.minimum(((1.0 - v) * h).astype(np.int64), h - 1)
        texels = part.texture[py, px]
        if texels.shape[1] == 4:
            return texels[:, :3], texels[:, 3] >= 128
        return texels, None
    if part.vertex_rgb is not None:
        c = np.einsum("sv,kvc->ksc", w, part.vertex_rgb[f].astype(np.float64)).reshape(-1, 3)
        return np.clip(np.rint(c), 0, 255).astype(np.uint8), None
    if part.base_rgb is not None:
        return np.broadcast_to(np.array(part.base_rgb, np.uint8), (len(tri_idx) * len(w), 3)), None
    return None, None


def oriented(model: Model, t: Transform, v: Voxel) -> tuple[list[MeshPart], list[np.ndarray]]:
    """The parts that are voxelized (voxel.exclude applied) and their vertices, right-handed Y-up."""
    up = model.up if t.up == "auto" else t.up
    rot = _UP[up]
    parts = [p for p in model.parts if not excluded(p, v.exclude)]
    if not parts:
        raise ValueError("all parts are excluded")
    return parts, [p.vertices @ rot.T for p in parts]


def voxelize(model: Model, t: Transform, v: Voxel) -> VoxelModel:
    parts, verts = oriented(model, t, v)
    allv = np.concatenate(verts)
    lo, hi = allv.min(axis=0), allv.max(axis=0)
    ext = hi - lo
    pitch = (1.0 / t.scale) if t.scale > 0 else float(ext.max()) / t.target_size
    if pitch <= 0:
        raise ValueError("model has zero size")
    size = tuple(int(np.floor(e / pitch)) + 1 for e in ext)
    X, Y, Z = size
    nvox = X * Y * Z
    if nvox > 400**3:
        raise ValueError(f"grid {size} is too large; lower transform.target_size")

    # logical parts: geometry names without numeric suffixes, per material
    keys: list[tuple[str, str]] = []
    key_index: dict[tuple[str, str], int] = {}
    part_ids = []
    for p in parts:
        k = (part_key(p.name), p.material)
        if k not in key_index:
            key_index[k] = len(keys)
            keys.append(k)
        part_ids.append(key_index[k])

    # sample budget
    total = 0
    plans = []
    for p, vv in zip(parts, verts, strict=True):
        tri = (vv[p.faces] - lo) / pitch  # (m, 3, 3) voxel units
        edges = np.stack([tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 1], tri[:, 0] - tri[:, 2]], axis=1)
        longest = np.sqrt((edges**2).sum(axis=2)).max(axis=1)
        n = np.maximum(1, np.ceil(longest * v.supersample)).astype(np.int64)
        total += int(((n + 1) * (n + 2) // 2).sum())
        plans.append((tri, n))
    if total > MAX_SAMPLES:
        raise ValueError(f"{total} surface samples needed (limit {MAX_SAMPLES}); lower target_size or supersample")

    csum = np.zeros((nvox, 3), np.float64)
    ccnt = np.zeros(nvox, np.int64)
    hits = np.zeros(nvox, np.int64)
    nvote = np.zeros((nvox, 3), np.int32)
    best_part = np.full(nvox, -1, np.int32)
    best_cnt = np.zeros(nvox, np.int64)
    part_cnt: dict[int, np.ndarray] = {}

    for p, (tri, n), pid in zip(parts, plans, part_ids, strict=True):
        normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        ln = np.linalg.norm(normals, axis=1)
        ny = np.where(ln > 0, normals[:, 1] / np.where(ln > 0, ln, 1), 0.0)
        ncls = np.where(ny > 0.5, NORMAL_UP, np.where(ny < -0.5, NORMAL_DOWN, NORMAL_SIDE)).astype(np.int64)
        pc = part_cnt.setdefault(pid, np.zeros(nvox, np.int64))
        for nval in np.unique(n):
            w = _lattice(int(nval))
            sel = np.nonzero(n == nval)[0]
            step = max(1, CHUNK // len(w))
            for s0 in range(0, len(sel), step):
                ti = sel[s0 : s0 + step]
                pts = np.einsum("sv,kvc->ksc", w, tri[ti]).reshape(-1, 3)
                idx3 = np.clip(np.floor(pts).astype(np.int64), 0, np.array(size) - 1)
                lin = (idx3[:, 0] * Y + idx3[:, 1]) * Z + idx3[:, 2]
                nk = np.repeat(ncls[ti], len(w))
                cols, keep = _sample_colors(p, ti, w, p.faces)
                if keep is not None:
                    lin, nk = lin[keep], nk[keep]
                    cols = cols[keep] if cols is not None else None
                    if len(lin) == 0:
                        continue
                hits += np.bincount(lin, minlength=nvox)
                pc += np.bincount(lin, minlength=nvox)
                for c in (NORMAL_SIDE, NORMAL_UP, NORMAL_DOWN):
                    m = nk == c
                    if m.any():
                        nvote[:, c] += np.bincount(lin[m], minlength=nvox).astype(np.int32)
                if cols is not None:
                    cols = np.asarray(cols, np.float64)
                    for ch in range(3):
                        csum[:, ch] += np.bincount(lin, weights=cols[:, ch], minlength=nvox)
                    ccnt += np.bincount(lin, minlength=nvox)
    for pid in sorted(part_cnt):
        pc = part_cnt[pid]
        better = pc > best_cnt
        best_cnt[better] = pc[better]
        best_part[better] = pid

    occ = (hits > 0).reshape(size)
    has_rgb = (ccnt > 0).reshape(size)
    rgb = np.zeros((nvox, 3), np.uint8)
    ok = ccnt > 0
    rgb[ok] = np.clip(np.rint(csum[ok] / ccnt[ok, None]), 0, 255).astype(np.uint8)
    model_v = VoxelModel(
        occ=occ,
        rgb=rgb.reshape((*size, 3)),
        has_rgb=has_rgb,
        part=best_part.astype(np.int16).reshape(size),
        normal=nvote.argmax(axis=1).astype(np.uint8).reshape(size),
        parts=keys,
        pitch=pitch,
    )
    if v.close_radius > 0 or v.mode == "solid":
        _fill(model_v, v)
    model_v.occ = remove_small(model_v.occ, v.min_component)
    _trim(model_v, t)
    model_v = orient(model_v, t)
    return model_v.cropped()


def _fill(m: VoxelModel, v: Voxel) -> None:
    """Close small gaps (close_radius) and, for solid mode, fill enclosed space; new voxels copy the
    colour, part and normal of the nearest surface voxel."""
    occ = m.occ
    closed = ndimage.binary_closing(occ, iterations=v.close_radius) | occ if v.close_radius > 0 else occ
    new = closed & ~occ
    if v.mode == "solid":
        padded = np.pad(~closed, 1, constant_values=True)
        labels, _ = ndimage.label(padded)
        outside = labels == labels[0, 0, 0]
        inside = ~outside[1:-1, 1:-1, 1:-1] & ~closed
        new |= inside
    if not new.any():
        return
    _, (ix, iy, iz) = ndimage.distance_transform_edt(~occ, return_indices=True)
    sel = np.nonzero(new)
    src = (ix[sel], iy[sel], iz[sel])
    m.rgb[sel] = m.rgb[src]
    m.has_rgb[sel] = m.has_rgb[src]
    m.part[sel] = m.part[src]
    m.normal[sel] = NORMAL_SIDE
    m.occ = occ | new


def _trim(m: VoxelModel, t: Transform) -> None:
    Y = m.size[1]
    lo = int(np.floor(t.trim_below * Y))
    hi = int(np.ceil(t.trim_above * Y))
    if lo > 0:
        m.occ[:, :lo, :] = False
    if hi < Y:
        m.occ[:, hi:, :] = False
