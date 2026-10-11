"""Import voxel point lists: `x, y, z[, r, g, b]` per line (matmod files, drububu.com .txt export).

Coordinates are non-negative integers with y up. Lines without colour leave the voxel uncoloured.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from .voxels import VoxelModel, compute_normals

_LINE = re.compile(r"^\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)(?:[ ,]+(\d+)[ ,]+(\d+)[ ,]+(\d+))?\s*$")


def read_txt(path: Path) -> VoxelModel:
    pts: list[tuple[int, int, int]] = []
    cols: list[tuple[int, int, int] | None] = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith(("#", "//")):
            continue
        m = _LINE.match(line)
        if not m:
            raise ValueError(f"{path}:{n}: expected 'x, y, z[, r, g, b]', got {line[:60]!r}")
        x, y, z = int(m[1]), int(m[2]), int(m[3])
        pts.append((x, y, z))
        cols.append((int(m[4]), int(m[5]), int(m[6])) if m[4] is not None else None)
    if not pts:
        raise ValueError(f"{path}: no voxels")
    arr = np.array(pts, np.int64)
    lo = arr.min(axis=0)
    arr -= lo
    size = tuple(int(v) + 1 for v in arr.max(axis=0))
    model = VoxelModel.empty(size)  # type: ignore[arg-type]
    for (x, y, z), col in zip(arr, cols, strict=True):
        model.occ[x, y, z] = True
        if col is not None:
            if max(col) > 255:
                raise ValueError(f"{path}: colour component above 255")
            model.rgb[x, y, z] = col
            model.has_rgb[x, y, z] = True
    model.normal = compute_normals(model.occ)
    return model
