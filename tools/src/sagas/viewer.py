"""`sagas view`: judge size and detail before a landmark ships.

One HTML page shows what `sagas build` makes of a landmark at several target sizes, next to things
every player knows: the player, trees and village houses of the installed games. Authors turn it,
zoom in on the detail, cut it open layer by layer and pick the size that reads well without towering
over the forest. The page runs offline (WebGL 2, data inside the file). It embeds schematics of the
games installed on this machine, which keep their own licences, so it is for the author's machine:
it lives in the ignored `.dev/view/` and is never committed or published.

`still()` renders the same comparison as a PNG for agents, which read images but cannot turn a page.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import __version__, handbuilt, palette, preview, schematic, vocab, voxels
from . import build as buildmod
from .config import Landmark, Transform, Voxel
from .errors import SagasError, SourceMissing
from .repo import Repo

LADDER = (12, 16, 24, 32, 48, 64)
MAX_SIZE = 160  # bigger grids make the page sluggish
CARVED_RGB = (120, 180, 255)
UNKNOWN_RGB = (150, 150, 150)
PLACEHOLDER = "/*SAGAS_DATA*/null"


@dataclass
class Voxels:
    """A voxel object for the page: material index per cell (0 = empty) and the material table."""

    cells: np.ndarray  # uint16 [x, y, z]
    mats: list[tuple[str, tuple[int, int, int]]]  # index 0 is empty
    carved: int = 0  # material index of carved air (rooms and doorways the build cuts), 0 = none
    scale: float = 1.0  # node size; the player is built from eighth-node cubes

    @property
    def dims(self) -> tuple[int, int, int]:
        x, y, z = self.cells.shape
        return int(x), int(y), int(z)

    def size_in_nodes(self) -> tuple[float, float, float]:
        x, y, z = self.dims
        return x * self.scale, y * self.scale, z * self.scale

    def json(self) -> dict:
        return {
            "dims": list(self.dims),
            "cells": rle(self.cells),
            "mats": [[label, list(rgb)] for label, rgb in self.mats],
            "carved": self.carved,
            "scale": self.scale,
        }


@dataclass
class ModelSize:
    target: int
    vox: Voxels
    nodes: int
    current: bool
    life: float  # longest side / real size; 0 when the real size is unknown
    fits: bool  # within one map chunk (else placement.large)
    door: str = ""
    sealed: bool = False
    findings: list[str] = field(default_factory=list)
    note: str = ""
    mesh: dict | None = None  # where the source model sits in this size's grid (mesh_affine)

    def json(self) -> dict:
        d = dataclasses.asdict(self)
        d["vox"] = self.vox.json()
        return d


@dataclass
class SourceMesh:
    """The source model for the page, scaled to its longest side (0..1, right-handed Y-up, before
    Luanti's X flip) and simplified by vertex clustering: enough to see what the nodes keep."""

    verts: np.ndarray  # float [n, 3]
    faces: np.ndarray  # int [m, 3]
    ext: np.ndarray  # extents of the oriented model in source units
    triangles: int  # before simplification

    @property
    def big(self) -> float:
        return float(self.ext.max())

    def json(self) -> dict:
        q = np.clip(np.rint(self.verts * 65535), 0, 65535).astype("<u2")
        wide = len(self.verts) > 65535
        faces = self.faces.astype("<u4" if wide else "<u2")
        return {
            "verts": base64.b64encode(q.tobytes()).decode("ascii"),
            "faces": base64.b64encode(faces.tobytes()).decode("ascii"),
            "wide": wide,
            "triangles": self.triangles,
        }


@dataclass
class Reference:
    key: str
    group: str
    label: str
    vox: Voxels
    on: bool = False

    @property
    def height(self) -> float:
        return round(self.vox.size_in_nodes()[1], 2)

    def json(self) -> dict:
        return {"key": self.key, "group": self.group, "label": self.label, "height": self.height,
                "on": self.on, "vox": self.vox.json()}  # fmt: skip


# -- encoding -------------------------------------------------------------------------------------


def rle(cells: np.ndarray) -> str:
    """uint16 [x, y, z] -> base64 of little-endian (value, run length) uint16 pairs, x fastest
    (index = x + X * (y + Y * z)). Voxel grids are mostly empty, so runs keep the page small."""
    flat = np.ascontiguousarray(cells.transpose(2, 1, 0)).ravel().astype(np.uint16)
    if flat.size == 0:
        return ""
    starts = np.flatnonzero(np.r_[True, flat[1:] != flat[:-1]])
    lengths = np.diff(np.r_[starts, flat.size])
    reps = (lengths + 65534) // 65535  # runs longer than 65535 are split
    values = np.repeat(flat[starts], reps)
    runs = np.full(values.size, 65535, np.int64)
    runs[np.cumsum(reps) - 1] = lengths - (reps - 1) * 65535
    pairs = np.empty(values.size * 2, "<u2")
    pairs[0::2] = values
    pairs[1::2] = runs
    return base64.b64encode(pairs.tobytes()).decode("ascii")


def unrle(data: str, dims: tuple[int, int, int]) -> np.ndarray:
    pairs = np.frombuffer(base64.b64decode(data), "<u2")
    flat = np.repeat(pairs[0::2], pairs[1::2].astype(np.int64))
    x, y, z = dims
    return flat.reshape(z, y, x).transpose(2, 1, 0)


# -- the landmark at several sizes ----------------------------------------------------------------


def ladder(current: int) -> list[int]:
    """The usual steps up to 64 (further when the current size is bigger) and the current size."""
    top = max(64, current)
    return sorted({s for s in LADDER if s <= top} | {current})


def from_build(res: buildmod.BuildResult) -> Voxels:
    """Placed nodes of a build by material class or palette colour, plus carved air."""
    g = res.grid
    placed = (g.param1 & 0x7F) > 0
    classes = vocab.classes()
    pal = palette.rgb_array()
    cells = np.zeros(g.size, np.uint16)
    mats: list[tuple[str, tuple[int, int, int]]] = [("", (0, 0, 0))]
    carved = 0
    for i, name in enumerate(g.names):
        sel = placed & (g.content == i)
        if not sel.any():
            continue
        if name == "sagas:color":
            for p2 in np.unique(g.param2[sel]):
                mats.append((f"colour {int(p2)}", tuple(int(c) for c in pal[p2])))
                cells[sel & (g.param2 == p2)] = len(mats) - 1
            continue
        if name == "air":
            mats.append(("carved air", CARVED_RGB))
            carved = len(mats) - 1
        elif name.startswith("sagas:m_") and name[len("sagas:m_") :] in classes:
            cls = name[len("sagas:m_") :]
            mats.append((cls, tuple(int(c) for c in classes[cls].rgb)))
        else:
            mats.append((name, UNKNOWN_RGB))
        cells[sel] = len(mats) - 1
    return Voxels(cells, mats, carved)


def source_mesh(mesh, t: Transform, v: Voxel, cells: int) -> SourceMesh:
    """The voxelized parts of the source, vertices merged on a cells^3 grid over the longest side."""
    from . import voxelize as vz

    parts, verts = vz.oriented(mesh, t, v)
    offsets = np.cumsum([0] + [len(v) for v in verts[:-1]])
    points = np.concatenate(verts)
    faces = np.concatenate([p.faces.astype(np.int64) + o for p, o in zip(parts, offsets, strict=True)])
    lo = points.min(axis=0)
    ext = points.max(axis=0) - lo
    unit = (points - lo) / float(ext.max())
    q = np.minimum(np.floor(unit * cells).astype(np.int64), cells)
    _, inv = np.unique((q[:, 0] * (cells + 1) + q[:, 1]) * (cells + 1) + q[:, 2], return_inverse=True)
    inv = inv.ravel()
    count = np.bincount(inv)
    merged = np.stack([np.bincount(inv, weights=unit[:, a]) / count for a in range(3)], axis=1)
    f = inv[faces]
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
    return SourceMesh(merged, np.unique(np.sort(f, axis=1), axis=0), ext, len(faces))


def mesh_affine(src: SourceMesh, t: Transform, pitch: float) -> dict:
    """Where the source sits in a size's node grid: grid = A (verts * s) + b. These are the steps
    voxelize takes on the grid (Luanti's X flip, rotate_y, mirror), on continuous coordinates."""
    dims = np.floor(src.ext / pitch) + 1
    a, b = np.eye(3), np.zeros(3)

    def flip(axis: int) -> None:
        a[axis] *= -1
        b[axis] = dims[axis] - b[axis]

    flip(0)
    for _ in range((t.rotate_y // 90) % 4):  # np.rot90(axes=(0, 2)): (x, z) -> (Z - z, x)
        a[[0, 2]] = np.stack([-a[2], a[0]])
        b[[0, 2]] = [dims[2] - b[2], b[0]]
        dims[[0, 2]] = dims[[2, 0]]
    if t.mirror == "x":
        flip(0)
    elif t.mirror == "z":
        flip(2)
    return {"s": src.big / pitch, "A": a.ravel().tolist(), "b": b.tolist()}


def scaled_openings(boxes: list[list[int]], f: float) -> list[list[int]]:
    return [[int(round(c * f)) for c in b] for b in boxes]


def current_size(landmark: Landmark, committed: voxels.VoxelModel | None) -> int:
    t = landmark.transform
    if landmark.source.kind == "mesh" and t.scale <= 0:
        return t.target_size
    if committed is not None:
        return max(committed.size)
    return t.target_size


class SizeBuilder:
    """Builds the landmark at any size, from the source mesh when it is fetched; without it (or for a
    voxel source) only the committed voxels, which is what ships. `src` is the simplified source
    model, placed in each size's grid by ModelSize.mesh."""

    def __init__(self, landmark: Landmark, repo: Repo, sizes: list[int] | None = None):
        from . import pipeline

        self.landmark = landmark
        self.notes: list[str] = []
        self.committed = voxels.read(landmark.vx_path) if landmark.vx_path.exists() else None
        self.current = current_size(landmark, self.committed)
        self.mesh = None
        if landmark.source.kind == "mesh":
            try:
                self.mesh = pipeline.load_mesh(landmark, repo)
            except SourceMissing:
                self.notes.append(
                    f"source not downloaded (sagas fetch {landmark.qualified_id}): only the committed size"
                )
        elif sizes:
            self.notes.append(f"source.kind = {landmark.source.kind!r} has a fixed size: only the committed size")
        if self.committed is None and self.mesh is None:
            raise SagasError(
                f"{landmark.qualified_id}: no voxels.vx.gz and no source mesh (sagas fetch, sagas voxelize)"
            )
        live = self.mesh is not None
        self.wanted = sorted(set(sizes or ladder(self.current)) | {self.current}) if live else [self.current]
        t, v = landmark.transform, landmark.voxel
        cells = int(min(256, max(128, 2 * max(self.wanted))))
        self.src = source_mesh(self.mesh, t, v, cells) if live else None

    @property
    def any_size(self) -> bool:
        return self.mesh is not None

    def build(self, s: int) -> ModelSize | None:
        """The landmark at size s; None (with a note) when it cannot be built."""
        from . import voxelize as vz

        landmark, current = self.landmark, self.current
        t, v = landmark.transform, landmark.voxel
        if s != current and (self.mesh is None or not 4 <= s <= MAX_SIZE):
            self.notes.append(f"size {s}: only sizes 4 to {MAX_SIZE} from a fetched source")
            return None
        note = ""
        lm, model = landmark, self.committed
        if self.mesh is not None:
            if s != current:
                lm = dataclasses.replace(
                    landmark,
                    transform=dataclasses.replace(t, target_size=s, scale=0.0),
                    voxel=dataclasses.replace(v, openings=scaled_openings(v.openings, s / current)),
                )
                if v.openings:
                    note = f"voxel.openings scaled from size {current}"
            try:
                model = vz.voxelize(self.mesh, lm.transform, lm.voxel)
            except ValueError as e:
                self.notes.append(f"size {s}: {e}")
                return None
            if s == current and self.committed is not None and not np.array_equal(model.occ, self.committed.occ):
                self.notes.append(
                    "voxels.vx.gz differs from a fresh voxelize (landmark.toml, the source or the tools changed):"
                    f" sagas voxelize {landmark.saga}/{landmark.id} --force"
                )
        res = buildmod.build(lm, model)
        x, y, z = res.size
        real = t.real_size
        entry = ModelSize(
            target=s,
            vox=from_build(res),
            nodes=int(res.node_count),
            current=s == current,
            life=round(max(x, y, z) / real, 2) if real > 0 else 0.0,
            fits=bool(buildmod.fits_chunk(res.size)),
            door=res.door,
            sealed=bool(res.sealed),
            findings=list(res.findings),
            note=note,
        )
        if self.src is not None:
            lt = lm.transform
            entry.mesh = mesh_affine(self.src, lt, 1.0 / lt.scale if lt.scale > 0 else self.src.big / lt.target_size)
        return entry


def model_sizes(
    landmark: Landmark, repo: Repo, sizes: list[int] | None = None, on_size: Callable[[ModelSize], None] | None = None
) -> tuple[list[ModelSize], list[str], SourceMesh | None]:
    """The landmark at the wanted sizes (see SizeBuilder), the notes, and the source model."""
    builder = SizeBuilder(landmark, repo, sizes)
    out = []
    for s in builder.wanted:
        entry = builder.build(s)
        if entry is not None:
            out.append(entry)
            if on_size:
                on_size(entry)
    return out, builder.notes, builder.src


# -- references: player, trees and houses of the installed games ----------------------------------


@dataclass(frozen=True)
class Known:
    key: str
    label: str
    file: str  # schematic file name, looked up in the game folders
    family: str  # mtg or mcl: which games to prefer


KNOWN = (
    Known("mtg_apple", "apple tree", "apple_tree.mts", "mtg"),
    Known("mtg_aspen", "aspen", "aspen_tree.mts", "mtg"),
    Known("mtg_pine", "pine", "pine_tree.mts", "mtg"),
    Known("mtg_jungle", "jungle tree", "jungle_tree.mts", "mtg"),
    Known("mtg_emergent", "emergent jungle tree", "emergent_jungle_tree.mts", "mtg"),
    Known("mcl_oak", "oak", "mcl_core_oak_classic.mts", "mcl"),
    Known("mcl_oak_large", "large oak", "mcl_core_oak_large_2.mts", "mcl"),
    Known("mcl_spruce", "spruce", "mcl_core_spruce_3.mts", "mcl"),
    Known("mcl_spruce_huge", "huge spruce", "mcl_core_spruce_huge_3.mts", "mcl"),
    Known("mcl_jungle_huge", "huge jungle tree", "mcl_core_jungle_tree_huge_2.mts", "mcl"),
    Known("mcl_house", "village house", "house_2_bed.mts", "mcl"),
    Known("mcl_house_large", "large village house", "house_4_bed.mts", "mcl"),
    Known("mcl_church", "village church", "church.mts", "mcl"),
)
PREFER = {"mtg": ("minetest_game", "minetest"), "mcl": ("mineclonia", "mineclone2", "voxelibre")}
DEFAULT_ON = {"mtg_apple", "mtg_pine"}
SKIP = re.compile(r"^(air|ignore)$|^mcl_villages:|jigsaw|structure_void|barrier")
TINTS = [  # display colours where the material class is too coarse; first match wins
    (re.compile(r":apple$"), (200, 40, 30)),
    (re.compile(r"pine_needles|leaves_spruce|spruce_leaves"), (46, 92, 56)),
    (re.compile(r"jungleleaves|leaves_jungle"), (52, 128, 36)),
    (re.compile(r"aspen_leaves|leaves_birch"), (112, 168, 66)),
    (re.compile(r"aspen_tree|tree_birch|birchtree"), (214, 208, 192)),
    (re.compile(r"jungletree|tree_jungle"), (88, 68, 40)),
    (re.compile(r"torch|lantern|lamp"), (255, 214, 102)),
]


def game_roots(extra: list[Path] | None = None) -> list[Path]:
    """Folders that hold Luanti games: --games, $SAGAS_GAMES, avanti's corpus, the Luanti user folders."""
    roots = list(extra or [])
    roots += [Path(p) for p in os.environ.get("SAGAS_GAMES", "").split(os.pathsep) if p]
    home = Path.home()
    roots += [
        home / ".avanti" / "corpus" / "games",
        home / "Library" / "Application Support" / "minetest" / "games",
        home / ".minetest" / "games",
        home / ".var" / "app" / "org.luanti.luanti" / ".minetest" / "games",
        home / "snap" / "luanti" / "current" / ".minetest" / "games",
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "Minetest" / "games")
    seen, out = set(), []
    for r in roots:
        r = r.expanduser()
        if r.is_dir() and r.resolve() not in seen:
            seen.add(r.resolve())
            out.append(r)
    return out


def _game_title(game: Path) -> str:
    conf = game / "game.conf"
    if conf.exists():
        m = re.search(r"^\s*title\s*=\s*(.+?)\s*$", conf.read_text(encoding="utf-8", errors="replace"), re.M)
        if m:
            return m.group(1)
    return game.name


def _schematics(game: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for dirpath, dirnames, filenames in os.walk(game):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for f in filenames:
            if f.endswith(".mts"):
                out.setdefault(f, Path(dirpath) / f)
    return out


def _rgb(name: str) -> tuple[int, int, int]:
    for pat, rgb in TINTS:
        if pat.search(name):
            return rgb
    cls, rgb = handbuilt.classify_node(name)
    if rgb:
        return rgb
    classes = vocab.classes()
    return tuple(int(c) for c in classes[cls].rgb) if cls in classes else UNKNOWN_RGB


def from_schematic(data: bytes, seed: str) -> Voxels:
    """A game schematic as one typical instance: nodes with a placement probability are rolled
    (seeded, so the page is stable), markers and air dropped, cropped to what is placed."""
    g = schematic.read_mts(data)
    prob = (g.param1 & 0x7F).astype(np.int64)
    rng = np.random.default_rng(int.from_bytes(seed.encode()[:8].ljust(8, b"\0"), "little"))
    keep = (prob > 0) & (rng.integers(0, 127, size=prob.shape) < prob)
    cells = np.zeros(g.size, np.uint16)
    mats: list[tuple[str, tuple[int, int, int]]] = [("", (0, 0, 0))]
    for i, name in enumerate(g.names):
        sel = keep & (g.content == i)
        if SKIP.search(name) or not sel.any():
            continue
        mats.append((name.split(":", 1)[-1], _rgb(name)))
        cells[sel] = len(mats) - 1
    occ = cells > 0
    if not occ.any():
        raise ValueError("nothing placed")
    lo = [int(np.flatnonzero(occ.any(axis=tuple(a for a in range(3) if a != k))).min()) for k in range(3)]
    hi = [int(np.flatnonzero(occ.any(axis=tuple(a for a in range(3) if a != k))).max()) + 1 for k in range(3)]
    return Voxels(cells[lo[0] : hi[0], lo[1] : hi[1], lo[2] : hi[2]].copy(), mats)


def player() -> Reference:
    """A player 1.75 nodes high (Luanti's collision box is 1.7 to 1.8 depending on the game)."""
    c = np.zeros((6, 14, 4), np.uint16)  # eighth-node cubes: 0.75 x 1.75 x 0.5 nodes
    c[1:5, 0, 1:3] = 5  # shoes
    c[1:5, 1:6, 1:3] = 1  # trousers
    c[1:5, 6:11, 1:3] = 2  # shirt
    c[0, 7:11, 1:3] = c[5, 7:11, 1:3] = 2  # sleeves
    c[0, 6, 1:3] = c[5, 6, 1:3] = 3  # hands
    c[1:5, 11:14, 0:4] = 3  # head
    c[1:5, 13, 0:4] = c[1:5, 11:14, 3] = 4  # hair
    mats = [("", (0, 0, 0)), ("trousers", (59, 79, 140)), ("shirt", (58, 166, 185)), ("skin", (228, 183, 140)),
            ("hair", (90, 60, 35)), ("shoes", (60, 60, 64))]  # fmt: skip
    return Reference("player", "", "player", Voxels(c, mats, scale=0.125), on=True)


def _blob(c: np.ndarray, centre: tuple[float, float, float], r: float, m: int) -> None:
    x, y, z = np.indices(c.shape)
    sel = ((x - centre[0]) ** 2 + (y - centre[1]) ** 2 + (z - centre[2]) ** 2 <= r * r) & (c == 0)
    c[sel] = m


def generic_trees() -> list[Reference]:
    """Stand-ins when no game is installed, sized like Minetest Game's apple tree, pine and emergent
    jungle tree."""
    mats = [("", (0, 0, 0)), ("trunk", (94, 69, 40)), ("leaves", (63, 122, 42)), ("needles", (46, 92, 56))]
    small = np.zeros((7, 8, 7), np.uint16)
    small[3, 0:5, 3] = 1
    _blob(small, (3, 5.5, 3), 2.6, 2)
    pine = np.zeros((5, 16, 5), np.uint16)
    pine[2, 0:15, 2] = 1
    for y in range(4, 16):
        r = max(0.6, 2.4 * (15 - y) / 11)
        x, z = np.indices((5, 5))
        sel = ((x - 2) ** 2 + (z - 2) ** 2 <= r * r) & (pine[:, y, :] == 0)
        pine[:, y, :][sel] = 3
    giant = np.zeros((9, 37, 9), np.uint16)
    giant[3:5, 0:33, 3:5] = 1
    _blob(giant, (3.5, 32, 3.5), 4.4, 2)
    return [
        Reference("generic_small", "generic", "small tree", Voxels(small, mats), on=True),
        Reference("generic_pine", "generic", "tall conifer", Voxels(pine, mats), on=True),
        Reference("generic_giant", "generic", "giant tree", Voxels(giant, mats)),
    ]


def references(roots: list[Path] | None = None) -> list[Reference]:
    """The player, then the known trees and houses found in the installed games (the stand-in trees
    when none is found)."""
    games = []
    for root in game_roots(roots):
        for g in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
            games.append(g)
    index: dict[Path, dict[str, Path]] = {}
    out = [player()]
    for k in KNOWN:
        prefer = PREFER[k.family]
        for g in sorted(games, key=lambda g: prefer.index(g.name) if g.name in prefer else len(prefer)):
            if g not in index:
                index[g] = _schematics(g)
            path = index[g].get(k.file)
            if path is None:
                continue
            try:
                vox = from_schematic(path.read_bytes(), k.key)
            except (ValueError, OSError):
                continue
            out.append(Reference(k.key, _game_title(g), k.label, vox, on=k.key in DEFAULT_ON))
            break
    if len(out) == 1:
        out += generic_trees()
    elif not any(r.on for r in out[1:]):
        trees = [r for r in out[1:] if "tree" in r.label or r.label in ("oak", "spruce", "pine")]
        for r in trees[:1] + sorted(trees, key=lambda r: -r.height)[:1]:
            r.on = True
    return out


# -- page and still -------------------------------------------------------------------------------


def page_data(
    landmark: Landmark,
    sizes: list[ModelSize],
    refs: list[Reference],
    notes: list[str],
    src: SourceMesh | None = None,
    live: bool = False,
) -> dict:
    return {
        "id": landmark.qualified_id,
        "selector": f"{landmark.saga}/{landmark.id}",
        "live": live,
        "max_size": MAX_SIZE,
        "title": landmark.title,
        "real_size": landmark.transform.real_size,
        "current": next((s.target for s in sizes if s.current), 0),
        "sizes": [s.json() for s in sizes],
        "refs": [r.json() for r in refs],
        "notes": notes,
        "mesh": src.json() if src is not None else None,
        "version": __version__,
    }


def template() -> str:
    return resources.files("sagas").joinpath("data/viewer.html").read_text(encoding="utf-8")


def page(data: dict) -> str:
    tpl = template()
    if PLACEHOLDER not in tpl:
        raise SagasError("viewer template has no data placeholder")
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return tpl.replace(PLACEHOLDER, blob, 1)


def _side(vox: Voxels) -> np.ndarray:
    """Side view (looking along x) at one pixel per node; eighth-node objects are reduced to nodes."""
    cells = vox.cells
    k = int(round(1 / vox.scale)) if vox.scale < 1 else 1
    if k > 1:
        x, y, z = cells.shape
        pad = [(0, (-n) % k) for n in (x, y, z)]
        c = np.pad(cells, pad)
        c = c.reshape(c.shape[0] // k, k, c.shape[1] // k, k, c.shape[2] // k, k).max(axis=(1, 3, 5))
        cells = c
    rgb = np.array([m[1] for m in vox.mats], np.uint8)
    occ = (cells > 0) & (cells != vox.carved)
    return np.flip(preview._ortho(occ, rgb[cells], axis=0, reverse=True), 0)


def still(sizes: list[ModelSize], refs: list[Reference], path: Path, px: int = 6) -> Path:
    """Top: the references shown by default and every size side by side at true scale, standing on
    one ground line. Bottom: each size enlarged, to judge what still reads."""
    shown = [r for r in refs if r.on]
    tallest = max((r for r in refs if r.key != "player"), key=lambda r: r.height, default=None)
    if tallest is not None and tallest not in shown:
        shown.append(tallest)
    items = [(r.label, f"{r.height:g} high", _side(r.vox)) for r in shown]
    for s in sizes:
        life = f"x{s.life:.1f} life size" if s.life else ""
        items.append((f"size {s.target}" + (" (now)" if s.current else ""), life, _side(s.vox)))
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    gap = 4 * px
    slots = [
        max(img.shape[1] * px, int(measure.textlength(label)), int(measure.textlength(sub)))
        for label, sub, img in items
    ]
    width = sum(slots) + gap * (len(items) + 1)
    height = (max(img.shape[0] for _, _, img in items) + 2) * px
    lineup = Image.new("RGB", (width, height + 44), preview.BG)
    d = ImageDraw.Draw(lineup)
    x = gap
    for (label, sub, img), slot in zip(items, slots, strict=True):
        h, w = img.shape[:2]
        lineup.paste(Image.fromarray(img, "RGB").resize((w * px, h * px), Image.NEAREST), (x, height - h * px))
        d.text((x, height + 6), label, fill=preview.INK)
        d.text((x, height + 22), sub, fill=preview.INK)
        x += slot + gap
    d.line([(0, height), (width, height)], fill=preview.INK)
    panel = 300
    detail = Image.new("RGB", (panel * len(sizes), panel + 44), preview.BG)
    dd = ImageDraw.Draw(detail)
    for i, s in enumerate(sizes):
        detail.paste(preview._panel(_side(s.vox), panel), (i * panel, 0))
        x_, y_, z_ = s.vox.dims
        dd.text((i * panel + 6, panel + 6), f"size {s.target}: {x_}x{y_}x{z_}, {s.nodes} nodes", fill=preview.INK)
        if s.life:
            dd.text((i * panel + 6, panel + 22), f"x{s.life:.1f} life size", fill=preview.INK)
    sheet = Image.new("RGB", (max(lineup.width, detail.width), lineup.height + detail.height + 16), preview.BG)
    sheet.paste(lineup, (0, 0))
    sheet.paste(detail, (0, lineup.height + 16))
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path, optimize=True)
    return path


def server(builder: SizeBuilder, html: str, port: int = 0):
    """Live mode: an HTTP server on this machine only that serves the page and builds any size it
    asks for (GET /size?target=N), caching each."""
    import http.server
    import urllib.parse

    cache: dict[int, bytes] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def reply(self, code: int, body: bytes, kind: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def fail(self, code: int, message: str) -> None:
            self.reply(code, json.dumps({"error": message}).encode(), "application/json")

        def do_GET(self) -> None:  # noqa: N802 (http.server's name)
            url = urllib.parse.urlsplit(self.path)
            if url.path in ("/", "/index.html"):
                self.reply(200, html.encode("utf-8"), "text/html; charset=utf-8")
                return
            if url.path != "/size":
                self.fail(404, "not found")
                return
            try:
                n = int(urllib.parse.parse_qs(url.query).get("target", [""])[0])
            except ValueError:
                self.fail(400, "target must be a number")
                return
            if n not in cache:
                seen = len(builder.notes)
                entry = builder.build(n)
                if entry is None:
                    self.fail(422, "; ".join(builder.notes[seen:]) or f"size {n} cannot be built")
                    return
                cache[n] = json.dumps(entry.json(), separators=(",", ":")).encode()
            self.reply(200, cache[n], "application/json")

        def log_message(self, format: str, *args) -> None:  # noqa: A002 (http.server's name)
            pass

    return http.server.HTTPServer(("127.0.0.1", port), Handler)


def serve(builder: SizeBuilder, html: str, port: int, ready: Callable[[str], None]) -> None:
    """Run the live server until interrupted."""
    httpd = server(builder, html, port)
    ready(f"http://127.0.0.1:{httpd.server_address[1]}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def default_path(repo: Repo, landmark: Landmark) -> Path:
    return repo.root / ".dev" / "view" / f"{landmark.saga}-{landmark.id}.html"
