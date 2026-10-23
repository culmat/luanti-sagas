"""voxels.vx.gz + landmark.toml -> schematic grid (the reproducible half of the pipeline)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import doors, schematic, vocab
from . import ruin as ruinmod
from .classify import Classified, budget_findings, classify
from .config import Landmark
from .interior import interior_mask
from .voxels import NORMAL_UP, VoxelModel, compute_normals

COLOR_NODE = "sagas:color"
CLASS_PREFIX = "sagas:m_"
STONE_FAMILY = ("stone", "stone_dark", "cobble", "brick", "sandstone", "marble")


@dataclass
class BuildResult:
    landmark: Landmark
    model: VoxelModel  # after ruin/erosion
    classified: Classified
    interior: np.ndarray
    grid: schematic.Grid
    anchor: tuple[int, int, int]
    findings: list[str] = field(default_factory=list)  # budget violations etc.
    doorway: str = ""  # what the doorway step did (auto doorway cut, or why the rooms stay sealed)
    door: str = ""  # for the preview caption: "+z (auto)", "openings", "sealed" or "" (no rooms)
    sealed: bool = False  # rooms without a way in at ground level remain
    suggestions: list[str] = field(default_factory=list)  # doorway boxes per side when sealed

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


def build(landmark: Landmark, model: VoxelModel) -> BuildResult:
    model = model.cropped()
    rng = ruinmod.rng_for(landmark.ruin, landmark.id)
    r = landmark.ruin
    if r.enabled and r.erosion > 0:
        occ = ruinmod.erode(model.occ, r.erosion, rng, landmark.voxel.min_component)
        model.occ = occ
        model.normal = compute_normals(occ)
        model = model.cropped()

    inner = interior_mask(model.occ, landmark.voxel.interior_close) if landmark.voxel.interior == "carve" else None
    if inner is None:
        inner = np.zeros(model.size, bool)

    # Doorways: given openings, or one inferred from a porch or lintel when the rooms are sealed.
    v = landmark.voxel
    openings = doors.openings_mask(model.size, v.openings)
    doorway_note, door_label = "", "openings" if v.openings else ""
    if v.doorway == "auto" and not v.openings and inner.any() and doors.sealed(model.occ, inner):
        door = doors.find_doorway(model.occ, inner)
        if door is not None:
            openings |= door.cells
            doorway_note = f"doorway cut facing {door.facing}: openings = [{door.box}]"
            door_label = f"{door.facing} (auto)"
    # Checked after cutting: given openings must actually lead in, and so must an inferred doorway.
    still_sealed = v.doorway == "auto" and inner.any() and doors.sealed(model.occ & ~openings, inner)
    suggested = []
    if still_sealed:
        suggested = [f"{d.facing} {d.box}" for d in doors.suggestions(model.occ & ~openings, inner)]
    if openings.any():
        model.occ = model.occ & ~openings
        model.normal = compute_normals(model.occ)

    c = classify(model, landmark.materials)
    cid = {n: i for i, n in enumerate(c.names)}

    if r.enabled and r.debris_height > 0:
        fill = inner & ~openings
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

    findings = budget_findings(c, landmark.materials)

    used = sorted({c.names[int(i)] for i in np.unique(c.cls[c.cls >= 0])} | ({"debris"} if fill.any() else set()))
    names = ["air"] + ([COLOR_NODE] if (c.color >= 0).any() else []) + [CLASS_PREFIX + n for n in used]
    names = ["air"] + sorted(names[1:])
    nid = {n: i for i, n in enumerate(names)}

    grid = schematic.empty(model.size, names)
    force = schematic.FORCE_PLACE
    prob = ruinmod.variation_prob(model.occ, model.normal == NORMAL_UP, r.variation if r.enabled else 0.0)

    carve = (inner | openings) & ~model.occ & ~fill
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
        landmark=landmark,
        model=model,
        classified=c,
        interior=inner,
        grid=grid,
        anchor=anchor_for(model.size, landmark.transform.anchor),
        findings=findings,
        doorway=doorway_note,
        door="sealed" if still_sealed else door_label,
        sealed=still_sealed,
        suggestions=suggested,
    )


def chunk_limits() -> tuple[int, int]:
    lim = vocab.vocabulary()["chunk_limits"]
    return int(lim["footprint"]), int(lim["height"])


def fits_chunk(size: tuple[int, int, int]) -> bool:
    fp, h = chunk_limits()
    return max(size[0], size[2]) <= fp and size[1] <= h
