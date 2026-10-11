from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from sagas import palette, vocab
from sagas.repo import Repo

CUBE_COLORS = {
    "px": (200, 30, 30),
    "nx": (30, 200, 30),
    "py": (30, 30, 200),
    "ny": (200, 200, 30),
    "pz": (200, 30, 200),
    "nz": (30, 200, 200),
}


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    (tmp_path / "content").mkdir()
    core = tmp_path / "mods" / "sagas"
    (core / "textures").mkdir(parents=True)
    (core / "vocabulary.json").write_bytes(vocab.vocabulary_bytes())
    palette.write_png(core / "textures" / "sagas_palette.png")
    return Repo(tmp_path)


def write_cube_obj(d: Path, size: float = 4.0) -> Path:
    """Axis-aligned cube [0, size]^3 whose six faces use six MTL materials with distinct Kd."""
    s = size
    v = [(0, 0, 0), (s, 0, 0), (s, s, 0), (0, s, 0), (0, 0, s), (s, 0, s), (s, s, s), (0, s, s)]
    faces = {  # outward winding (counter-clockwise seen from outside), 1-based
        "nz": [(1, 4, 3), (1, 3, 2)],
        "pz": [(5, 6, 7), (5, 7, 8)],
        "ny": [(1, 2, 6), (1, 6, 5)],
        "py": [(4, 8, 7), (4, 7, 3)],
        "nx": [(1, 5, 8), (1, 8, 4)],
        "px": [(2, 3, 7), (2, 7, 6)],
    }
    mtl = []
    for name, (r, g, b) in CUBE_COLORS.items():
        mtl += [f"newmtl {name}", f"Kd {r / 255:.6f} {g / 255:.6f} {b / 255:.6f}", ""]
    (d / "cube.mtl").write_text("\n".join(mtl))
    lines = ["mtllib cube.mtl", "o cube"] + [f"v {x} {y} {z}" for x, y, z in v]
    for name, tris in faces.items():
        lines.append(f"usemtl {name}")
        lines += [f"f {a} {b} {c}" for a, b, c in tris]
    p = d / "cube.obj"
    p.write_text("\n".join(lines) + "\n")
    return p


def write_vox(path: Path, size: tuple[int, int, int], voxels: list[tuple[int, ...]], colors: dict[int, tuple]):
    def chunk(cid: bytes, content: bytes, children: bytes = b"") -> bytes:
        return cid + struct.pack("<ii", len(content), len(children)) + content + children

    size_c = chunk(b"SIZE", struct.pack("<iii", *size))
    xyzi = chunk(b"XYZI", struct.pack("<i", len(voxels)) + b"".join(struct.pack("<4B", *v) for v in voxels))
    ntrn = chunk(b"nTRN", b"\x00" * 16)  # an unknown chunk the reader must skip
    pal = bytearray(256 * 4)
    for idx, (r, g, b) in colors.items():
        pal[(idx - 1) * 4 : (idx - 1) * 4 + 4] = bytes([r, g, b, 255])
    rgba = chunk(b"RGBA", bytes(pal))
    main = chunk(b"MAIN", b"", size_c + xyzi + ntrn + rgba)
    path.write_bytes(b"VOX " + struct.pack("<i", 150) + main)


def landmark_toml(repo: Repo, saga: str, sid: str, extra: str = "") -> Path:
    d = repo.content / saga / sid
    d.mkdir(parents=True, exist_ok=True)
    p = d / "landmark.toml"
    p.write_text(
        f'id = "{sid}"\nsaga = "{saga}"\ntitle = "Test {sid}"\n'
        + extra
        + '\n[source]\nkind = "voxels"\nfile = "model.txt"\nurl = "https://example.org/model"\n'
        'author = "Tester"\nlicense = "CC0-1.0"\n'
    )
    return p


def box_txt(path: Path, size=(6, 5, 6), door=True, color=None) -> Path:
    """Hollow box walls (no roof) with an optional door gap at x=2..3, z=0, y=1..2."""
    X, Y, Z = size
    lines = []
    for x in range(X):
        for y in range(Y):
            for z in range(Z):
                wall = x in (0, X - 1) or z in (0, Z - 1) or y == 0
                if door and z == 0 and x in (2, 3) and y in (1, 2):
                    wall = False
                if wall:
                    lines.append(f"{x}, {y}, {z}" + (", {}, {}, {}".format(*color) if color else ""))
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(1)
