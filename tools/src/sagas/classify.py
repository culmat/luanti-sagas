"""Assign every voxel either a material class (`sagas:m_<class>`) or a palette colour (`sagas:color`).

Rules are evaluated in order; the first match wins. Unmatched voxels:
    classes  -> materials.default
    hybrid   -> palette colour if the voxel has one, else materials.default
    palette  -> palette colour; voxels without colour get the default class's colour
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

import numpy as np

from . import palette, vocab
from .config import Materials, Rule
from .voxels import NORMAL_DOWN, NORMAL_SIDE, NORMAL_UP, VoxelModel

NORMAL_CODE = {"up": NORMAL_UP, "down": NORMAL_DOWN, "side": NORMAL_SIDE}


@dataclass
class Classified:
    names: list[str]  # class names, index = class id
    cls: np.ndarray  # int16 [x, y, z]; -1 = no class (colour node or empty)
    color: np.ndarray  # int16 [x, y, z]; palette index or -1

    def class_counts(self) -> dict[str, int]:
        ids, n = np.unique(self.cls[self.cls >= 0], return_counts=True)
        return {self.names[int(i)]: int(c) for i, c in zip(ids, n, strict=True)}

    @property
    def color_count(self) -> int:
        return int((self.color >= 0).sum())


def _part_lookup(model: VoxelModel, pattern: str, which: int) -> np.ndarray:
    """Boolean per part index (+1 so that index 0 is 'unknown part')."""
    pat = pattern.lower()
    flags = [False] + [fnmatch.fnmatchcase(p[which].lower(), pat) for p in model.parts]
    return np.array(flags, bool)


def rule_mask(model: VoxelModel, rule: Rule) -> np.ndarray:
    m = rule.match
    mask = model.occ.copy()
    if "material" in m:
        mask &= _part_lookup(model, m["material"], 1)[model.part + 1]
    if "part" in m:
        mask &= _part_lookup(model, m["part"], 0)[model.part + 1]
    if "normal" in m:
        mask &= model.normal == NORMAL_CODE[m["normal"]]
    if "y" in m:
        lo, hi = m["y"]
        ys = np.arange(model.size[1])
        mask &= ((ys >= lo) & (ys <= hi))[None, :, None]
    if "y_frac" in m:
        lo, hi = m["y_frac"]
        top = max(1, model.size[1] - 1)
        frac = np.arange(model.size[1]) / top
        mask &= ((frac >= lo) & (frac <= hi))[None, :, None]
    if "color" in m:
        tol = float(m.get("tol", 20))
        sel = mask & model.has_rgb
        idx = np.argwhere(sel)
        if len(idx):
            cols = model.rgb[sel]
            uniq, inv = np.unique(cols, axis=0, return_inverse=True)
            d = palette.lab_distance(vocab.hex_to_rgb(m["color"]), uniq)[inv.ravel()]
            keep = np.zeros(model.size, bool)
            ok = idx[d <= tol]
            keep[ok[:, 0], ok[:, 1], ok[:, 2]] = True
            mask &= keep
        else:
            mask &= False
    return mask


def classify(model: VoxelModel, mats: Materials) -> Classified:
    names = vocab.class_names()
    cid = {n: i for i, n in enumerate(names)}
    cls = np.full(model.size, -1, np.int16)
    want_color = np.zeros(model.size, bool)
    assigned = np.zeros(model.size, bool)
    for rule in mats.rules:
        mask = rule_mask(model, rule) & ~assigned
        if rule.color:
            want_color |= mask
        else:
            cls[mask] = cid[rule.cls]
        assigned |= mask
    # hand-built sagas carry classes in their part materials ("class:stone", "color")
    if any(m.startswith("class:") or m == "color" for _, m in model.parts):
        for i, (_, mat) in enumerate(model.parts):
            sel = model.occ & ~assigned & (model.part == i)
            if mat.startswith("class:") and mat[6:] in cid:
                cls[sel] = cid[mat[6:]]
                assigned |= sel
            elif mat == "color":
                want_color |= sel & model.has_rgb
                assigned |= sel & model.has_rgb
    rest = model.occ & ~assigned
    default = cid[mats.default]
    if mats.mode == "classes":
        cls[rest] = default
    elif mats.mode == "hybrid":
        want_color |= rest & model.has_rgb
        cls[rest & ~model.has_rgb] = default
    else:  # palette
        want_color |= rest
    color = np.full(model.size, -1, np.int16)
    sel = want_color & model.occ
    if sel.any():
        rgb = model.rgb[sel].copy()
        missing = ~model.has_rgb[sel]
        if missing.any():
            rgb[missing] = vocab.classes()[mats.default].rgb
        color[sel] = palette.quantize(rgb).astype(np.int16)
    return Classified(names=names, cls=cls, color=color)


def budget_findings(c: Classified, mats: Materials) -> list[str]:
    """Value-budget violations as messages (empty = fine)."""
    out = []
    hard = int(vocab.vocabulary()["precious_hard_cap"])
    counts = c.class_counts()
    for name, cdef in vocab.classes().items():
        if cdef.tier == "common":
            continue
        n = counts.get(name, 0)
        cap = mats.value_budget.get(name, cdef.default_cap)
        if cap is None:
            continue
        if cdef.tier == "precious" and cap > hard:
            out.append(f"value_budget.{name} = {cap} exceeds the hard cap of {hard} for precious materials")
            cap = hard
        if n > cap:
            out.append(
                f"{n} {name} nodes exceed the value budget of {cap} (raise materials.value_budget.{name} "
                f"or map these voxels to another class)"
            )
    return out
