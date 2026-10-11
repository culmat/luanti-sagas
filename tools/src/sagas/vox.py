"""MagicaVoxel .vox reader (https://github.com/ephtracy/voxel-model, format version 150/200).

Chunks: id(4) content_bytes(int32) children_bytes(int32) content children. We read the first
SIZE/XYZI pair and the RGBA palette (stored entry k is colour index k+1) and skip everything else.
MagicaVoxel is right-handed with z up; the model is converted like meshes (Y up, then X flipped).
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from .config import Transform
from .voxels import VoxelModel, compute_normals, orient


def read_vox(path: Path, transform: Transform | None = None) -> VoxelModel:
    data = Path(path).read_bytes()
    if data[:4] != b"VOX ":
        raise ValueError(f"{path}: not a MagicaVoxel file")
    (version,) = struct.unpack_from("<i", data, 4)
    if version not in (150, 200):
        raise ValueError(f"{path}: unsupported .vox version {version}")
    off = 8
    if data[off : off + 4] != b"MAIN":
        raise ValueError(f"{path}: MAIN chunk missing")
    _, n, m = struct.unpack_from("<4sii", data, off)
    off += 12 + n
    end = off + m
    size = None
    xyzi = None
    palette = None
    models = 0
    while off + 12 <= end:
        cid, n, m = struct.unpack_from("<4sii", data, off)
        body = data[off + 12 : off + 12 + n]
        if cid == b"SIZE" and size is None:
            size = struct.unpack_from("<iii", body, 0)
        elif cid == b"XYZI":
            models += 1
            if xyzi is None:
                (count,) = struct.unpack_from("<i", body, 0)
                xyzi = np.frombuffer(body, np.uint8, count * 4, 4).reshape(-1, 4)
        elif cid == b"RGBA":
            raw = np.frombuffer(body, np.uint8, 256 * 4).reshape(256, 4)
            palette = np.zeros((256, 3), np.uint8)
            palette[1:256] = raw[0:255, :3]
        off += 12 + n + m
    if size is None or xyzi is None:
        raise ValueError(f"{path}: no voxel model found")
    sx, sy, sz = size
    # right-handed z-up (x, y, z) -> right-handed y-up (x, z, sy-1-y)
    X, Y, Z = sx, sz, sy
    model = VoxelModel.empty((X, Y, Z))
    xs, ys, zs, ci = (xyzi[:, i].astype(np.int64) for i in range(4))
    gx, gy, gz = xs, zs, sy - 1 - ys
    model.occ[gx, gy, gz] = True
    if palette is not None:
        model.rgb[gx, gy, gz] = palette[ci]
        model.has_rgb[gx, gy, gz] = True
    model = orient(model, transform or Transform())
    model.normal = compute_normals(model.occ)
    return model.cropped()
