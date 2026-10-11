"""VoxelModel: the raw voxelization of a source, and its committed file form `voxels.vx.gz`.

Arrays are indexed [x, y, z] with y up. The `.vx.gz` file decouples the source-dependent stage
(`sagas voxelize`, needs the downloaded model) from the reproducible stage (`sagas build`), so CI
and contributors can rebuild schematics without downloading anything.

File format (gzip, mtime 0, deterministic):
    line 1:  #vx1 {"size": [X, Y, Z], "pitch": 0.25, "source_sha256": "...", "parts": [["part", "material"], ...]}
    then one line per occupied voxel, sorted by x, y, z:
             x y z rrggbb|- part_index normal
    rrggbb is the colour or "-" when unknown; part_index is -1 when unknown; normal is U, D or S.
"""

from __future__ import annotations

import gzip
import io
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .config import Transform

NORMAL_SIDE, NORMAL_UP, NORMAL_DOWN = 0, 1, 2
_NORMAL_CHAR = {NORMAL_SIDE: "S", NORMAL_UP: "U", NORMAL_DOWN: "D"}
_CHAR_NORMAL = {v: k for k, v in _NORMAL_CHAR.items()}


@dataclass
class VoxelModel:
    occ: np.ndarray  # bool [x, y, z]
    rgb: np.ndarray  # uint8 [x, y, z, 3]
    has_rgb: np.ndarray  # bool [x, y, z]
    part: np.ndarray  # int16 [x, y, z], -1 = unknown
    normal: np.ndarray  # uint8 [x, y, z]
    parts: list[tuple[str, str]] = field(default_factory=list)  # (part name, material name)
    pitch: float = 1.0  # model units per voxel
    source_sha256: str = ""

    @property
    def size(self) -> tuple[int, int, int]:
        x, y, z = self.occ.shape
        return int(x), int(y), int(z)

    @property
    def count(self) -> int:
        return int(self.occ.sum())

    @classmethod
    def empty(cls, size: tuple[int, int, int]) -> VoxelModel:
        return cls(
            occ=np.zeros(size, bool),
            rgb=np.zeros((*size, 3), np.uint8),
            has_rgb=np.zeros(size, bool),
            part=np.full(size, -1, np.int16),
            normal=np.zeros(size, np.uint8),
        )

    def cropped(self) -> VoxelModel:
        """Trim empty borders so the occupied voxels start at 0 and the box is tight."""
        if not self.occ.any():
            raise ValueError("model has no voxels")
        idx = np.argwhere(self.occ)
        lo, hi = idx.min(axis=0), idx.max(axis=0) + 1
        sl = tuple(slice(int(a), int(b)) for a, b in zip(lo, hi, strict=True))
        return VoxelModel(
            occ=self.occ[sl].copy(),
            rgb=self.rgb[sl].copy(),
            has_rgb=self.has_rgb[sl].copy(),
            part=self.part[sl].copy(),
            normal=self.normal[sl].copy(),
            parts=list(self.parts),
            pitch=self.pitch,
            source_sha256=self.source_sha256,
        )


def compute_normals(occ: np.ndarray) -> np.ndarray:
    """Up if the voxel above is empty, down if only the one below is empty, else side."""
    above = np.zeros_like(occ)
    above[:, :-1, :] = occ[:, 1:, :]
    below = np.zeros_like(occ)
    below[:, 1:, :] = occ[:, :-1, :]
    n = np.full(occ.shape, NORMAL_SIDE, np.uint8)
    n[occ & ~below & above] = NORMAL_DOWN
    n[occ & ~above] = NORMAL_UP
    return n


def write(model: VoxelModel, path: Path) -> None:
    header = {
        "size": list(model.size),
        "pitch": round(float(model.pitch), 9),
        "source_sha256": model.source_sha256,
        "parts": [list(p) for p in model.parts],
    }
    buf = io.StringIO()
    buf.write("#vx1 " + json.dumps(header, sort_keys=True, ensure_ascii=False) + "\n")
    idx = np.argwhere(model.occ)  # argwhere is C order: sorted by x, then y, then z
    for x, y, z in idx:
        if model.has_rgb[x, y, z]:
            r, g, b = model.rgb[x, y, z]
            col = f"{r:02x}{g:02x}{b:02x}"
        else:
            col = "-"
        buf.write(f"{x} {y} {z} {col} {int(model.part[x, y, z])} {_NORMAL_CHAR[int(model.normal[x, y, z])]}\n")
    raw = buf.getvalue().encode("utf-8")
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", compresslevel=9, mtime=0, filename="") as gz:
        gz.write(raw)
    Path(path).write_bytes(out.getvalue())


def read(path: Path) -> VoxelModel:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        first = f.readline()
        if not first.startswith("#vx1 "):
            raise ValueError(f"{path}: not a vx1 file")
        header = json.loads(first[5:])
        size = tuple(int(v) for v in header["size"])
        m = VoxelModel.empty(size)  # type: ignore[arg-type]
        m.parts = [tuple(p) for p in header.get("parts", [])]  # type: ignore[misc]
        m.pitch = float(header.get("pitch", 1.0))
        m.source_sha256 = header.get("source_sha256", "")
        for line in f:
            x, y, z, col, part, normal = line.split()
            xi, yi, zi = int(x), int(y), int(z)
            m.occ[xi, yi, zi] = True
            if col != "-":
                m.rgb[xi, yi, zi] = (int(col[0:2], 16), int(col[2:4], 16), int(col[4:6], 16))
                m.has_rgb[xi, yi, zi] = True
            m.part[xi, yi, zi] = int(part)
            m.normal[xi, yi, zi] = _CHAR_NORMAL[normal]
    return m


def orient(m: VoxelModel, t: Transform) -> VoxelModel:
    """Right-handed Y-up grid -> Luanti (left-handed: flip X), then transform.rotate_y and mirror."""

    def apply(a: np.ndarray) -> np.ndarray:
        a = np.flip(a, 0)  # right-handed -> Luanti's left-handed frame
        k = (t.rotate_y // 90) % 4
        if k:
            a = np.rot90(a, k, axes=(0, 2))
        if t.mirror == "x":
            a = np.flip(a, 0)
        elif t.mirror == "z":
            a = np.flip(a, 2)
        return np.ascontiguousarray(a)

    return VoxelModel(
        occ=apply(m.occ),
        rgb=apply(m.rgb),
        has_rgb=apply(m.has_rgb),
        part=apply(m.part),
        normal=apply(m.normal),
        parts=m.parts,
        pitch=m.pitch,
        source_sha256=m.source_sha256,
    )
