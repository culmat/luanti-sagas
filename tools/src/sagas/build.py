"""voxels.vx.gz + saga.toml -> schematic grid (the reproducible half of the pipeline)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import ruin as ruinmod
from . import schematic, vocab
from .classify import Classified, budget_findings, classify
from .config import Saga
from .interior import interior_mask
from .voxels import NORMAL_UP, VoxelModel, compute_normals

COLOR_NODE = "sagas:color"
CLASS_PREFIX = "sagas:m_"
STONE_FAMILY = ("stone", "stone_dark", "cobble", "brick", "sandstone", "marble")


@dataclass
class BuildResult:
    saga: Saga
    model: VoxelModel  # after ruin/erosion
    classified: Classified
    interior: np.ndarray
    grid: schematic.Grid
    anchor: tuple[int, int, int]
    findings: list[str] = field(default_factory=list)  # budget violations etc.

    @property
    def size(self) -> tuple[int, int, int]:
        return self.grid.size

    @property
    def node_count(self) -> int:
        return int(self.model.occ.sum())


def anchor_for(size: tuple[int, int, int], mode: str) -> tuple[int, int, int]:
    x, y, z = size
    if mode == "bottom-min":
        return 0, 0, 0
    if mode == "center":
        return x // 2, y // 2, z // 2
    return x // 2, 0, z // 2


def build(saga: Saga, model: VoxelModel) -> BuildResult:
    model = model.cropped()
    rng = ruinmod.rng_for(saga.ruin, saga.id)
    r = saga.ruin
    if r.enabled and r.erosion > 0:
        occ = ruinmod.erode(model.occ, r.erosion, rng, saga.voxel.min_component)
        model.occ = occ
        model.normal = compute_normals(occ)
        model = model.cropped()

    c = classify(model, saga.materials)
    cid = {n: i for i, n in enumerate(c.names)}

    inner = interior_mask(model.occ, saga.voxel.interior_close) if saga.voxel.interior == "carve" else None
    if inner is None:
        inner = np.zeros(model.size, bool)

    if r.enabled and r.debris_height > 0:
        fill = inner.copy()
        fill[:, r.debris_height :, :] = False
        # layer 0 inside the walls is natural ground; debris starts on top of it
        fill[:, 0, :] = False
        ys = np.arange(model.size[1])
        top = max(1, r.debris_height - 1)
        ramp = np.clip(127 - (ys - 1) * (40 // top), 80, 127).astype(np.uint8)
        debris_prob = np.broadcast_to(ramp[None, :, None], model.size)
    else:
        fill = np.zeros(model.size, bool)
        debris_prob = None

    if r.enabled and r.moss > 0:
        stone_ids = [cid[n] for n in STONE_FAMILY]
        top = model.occ & (model.normal == NORMAL_UP) & np.isin(c.cls, stone_ids)
        mossy = top & (rng.random(model.size) < r.moss)
        c.cls[mossy] = cid["moss"]

    findings = budget_findings(c, saga.materials)

    used = sorted({c.names[int(i)] for i in np.unique(c.cls[c.cls >= 0])} | ({"debris"} if fill.any() else set()))
    names = ["air"] + ([COLOR_NODE] if (c.color >= 0).any() else []) + [CLASS_PREFIX + n for n in used]
    names = ["air"] + sorted(names[1:])
    nid = {n: i for i, n in enumerate(names)}

    grid = schematic.empty(model.size, names)
    force = schematic.FORCE_PLACE
    prob = ruinmod.variation_prob(model.occ, model.normal == NORMAL_UP, r.variation if r.enabled else 0.0)

    carve = inner & ~model.occ & ~fill
    grid.param1[carve] = schematic.PROB_ALWAYS | force

    if fill.any():
        grid.content[fill] = nid[CLASS_PREFIX + "debris"]
        assert debris_prob is not None
        grid.param1[fill] = debris_prob[fill] | force

    col = model.occ & (c.color >= 0)
    if col.any():
        grid.content[col] = nid[COLOR_NODE]
        grid.param2[col] = c.color[col].astype(np.uint8)
    for name in used:
        sel = model.occ & (c.cls == cid[name])
        if sel.any():
            grid.content[sel] = nid[CLASS_PREFIX + name]
    grid.param1[model.occ] = prob[model.occ] | force

    return BuildResult(
        saga=saga,
        model=model,
        classified=c,
        interior=inner,
        grid=grid,
        anchor=anchor_for(model.size, saga.transform.anchor),
        findings=findings,
    )


def chunk_limits() -> tuple[int, int]:
    lim = vocab.vocabulary()["chunk_limits"]
    return int(lim["footprint"]), int(lim["height"])


def fits_chunk(size: tuple[int, int, int]) -> bool:
    fp, h = chunk_limits()
    return max(size[0], size[2]) <= fp and size[1] <= h
