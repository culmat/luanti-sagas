"""Doorways: keep buildings enterable.

Models often have no hole where the door is: 0 A.D. and many game assets paint the door onto the
wall texture, so the voxelized wall is closed and the rooms behind it are sealed. This module

* cuts `voxel.openings` (boxes in schematic coordinates) given in landmark.toml, and
* with `voxel.doorway = "auto"` (the default), when the rooms have no way in at ground level, cuts
  one doorway where the model shows an entrance: through the wall under a porch roof or lintel.

Coordinates are schematic grid indices [x, y, z] (after cropping, before rotation). Layer 0 is
the ground the landmark stands in; people stand on it and occupy layers 1 and 2, so doorways are
2 high (layers 1-2) and 2 wide.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

FLOOR_Y = 1  # first layer above the ground
DOOR_H = 2
DOOR_W = 2
MAX_WALL = 4  # thickest wall a doorway is cut through
MAX_PORCH = 4  # how far a porch may reach out over the doorway
MIN_ROOM = 6  # smaller sealed hollows (2 x 3 floor) are pockets of the wall, not rooms
DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))  # (dx, dz) outward


@dataclass
class Doorway:
    cells: np.ndarray  # bool mask, same shape as occ: cut to forced air
    facing: str  # +x, -x, +z or -z
    box: list[int]  # [x1, y1, z1, x2, y2, z2] for landmark.toml


def openings_mask(shape: tuple[int, int, int], boxes: list[list[int]]) -> np.ndarray:
    out = np.zeros(shape, bool)
    for b in boxes:
        x1, y1, z1, x2, y2, z2 = b
        out[min(x1, x2) : max(x1, x2) + 1, min(y1, y2) : max(y1, y2) + 1, min(z1, z2) : max(z1, z2) + 1] = True
    return out


def _outside(occ: np.ndarray, inner: np.ndarray, x: int, y: int, z: int) -> bool:
    X, Y, Z = occ.shape
    if not (0 <= x < X and 0 <= z < Z):
        return True
    return not occ[x, y, z] and not inner[x, y, z]


def _floor_plan(occ: np.ndarray, inner: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """2D masks at floor level: `free` where a player fits (layers 1 and 2 empty) and `room` where
    that is inside the rooms."""
    free = ~occ[:, FLOOR_Y, :] & ~occ[:, FLOOR_Y + 1, :]
    room = free & inner[:, FLOOR_Y, :]
    return free, room


def sealed(occ: np.ndarray, inner: np.ndarray) -> bool:
    """True when the model has a room a player can stand in (2 high, at least MIN_ROOM cells) that
    no walkable way leads into from outside: notches, cracks and diagonal gaps of a voxelized wall
    don't count as ways in, and hollows lower than 2 are no rooms."""
    X, Y, Z = occ.shape
    if Y <= FLOOR_Y + 2 or not inner[:, FLOOR_Y, :].any():
        return False
    return bool(_reach(occ, inner)[2].any())


def _reach(occ: np.ndarray, inner: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """2D masks at floor level: `outside` where a player can walk in from beyond the model, `shut`
    for room cells nobody can walk into, and `target`, the largest sealed room (empty when every
    sealed hollow is smaller than MIN_ROOM)."""
    free, room = _floor_plan(occ, inner)
    labels, _ = ndimage.label(np.pad(free, 1, constant_values=True))
    outside = labels[1:-1, 1:-1] == labels[0, 0]
    shut = room & ~outside
    rooms, n = ndimage.label(shut)
    target = np.zeros_like(shut)
    if n:
        sizes = ndimage.sum(shut, rooms, range(1, n + 1))
        if sizes.max() >= MIN_ROOM:
            target = rooms == int(np.argmax(sizes)) + 1
    return outside, shut, target


def _covered(occ: np.ndarray, x: int, z: int) -> bool:
    """A porch roof or lintel at door-top height (layers 2-3) over free floor. Eaves sit higher and
    run all around a building, so they are no cue."""
    X, Y, Z = occ.shape
    if not (0 <= x < X and 0 <= z < Z) or occ[x, FLOOR_Y, z]:
        return False
    return bool(occ[x, FLOOR_Y + 1 : min(Y, FLOOR_Y + DOOR_H + 1), z].any())


def _lanes(occ: np.ndarray, inner: np.ndarray, d: tuple[int, int]) -> dict[tuple[int, int], dict]:
    """For direction d: straight ways out of the sealed rooms, keyed by the room cell they start
    from: the cells to cut (walls, side rooms, pockets) up to the first cell a player can reach from
    outside, and whether a porch or lintel covers the way."""
    X, Y, Z = occ.shape
    dx, dz = d
    outside, shut, target = _reach(occ, inner)
    out = {}
    xs, zs = np.nonzero(target)
    for x, z in zip(xs, zs, strict=True):
        nx, nz = x + dx, z + dz
        if 0 <= nx < X and 0 <= nz < Z and target[nx, nz]:
            continue  # not at the room's edge
        path = []
        cx, cz = nx, nz
        while 0 <= cx < X and 0 <= cz < Z and not outside[cx, cz] and len(path) < MAX_WALL + MAX_PORCH:
            path.append((cx, cz))
            cx, cz = cx + dx, cz + dz
        inside = 0 <= cx < X and 0 <= cz < Z
        if not path or (inside and not outside[cx, cz]):
            continue
        covered = any(_covered(occ, px, pz) for px, pz in path) or (inside and _covered(occ, cx, cz))
        out[(int(x), int(z))] = {"path": path, "covered": covered}
    return out


FACING = {(1, 0): "+x", (-1, 0): "-x", (0, 1): "+z", (0, -1): "-z"}


def _best_pair(lanes: dict, d: tuple[int, int]) -> tuple[tuple, tuple] | None:
    """Two neighbouring lanes (a doorway 2 wide) in the middle of `lanes`, with the shortest cut."""
    if not lanes:
        return None
    side = (abs(d[1]), abs(d[0]))  # along the wall
    cx = np.mean([k[0] for k in lanes])
    cz = np.mean([k[1] for k in lanes])
    best = None
    for k, lane in lanes.items():
        k2 = (k[0] + side[0], k[1] + side[1])
        if k2 not in lanes:
            continue
        dist = abs((k[0] + k2[0]) / 2 - cx) + abs((k[1] + k2[1]) / 2 - cz)
        cut = len(lane["path"]) + len(lanes[k2]["path"])
        score = (-dist, -cut)
        if best is None or score > best[0]:
            best = (score, (k, k2))
    return None if best is None else best[1]


def _doorway(occ: np.ndarray, lanes: dict, pair: tuple, d: tuple[int, int]) -> Doorway:
    cells = np.zeros(occ.shape, bool)
    for k in pair:
        for x, z in lanes[k]["path"]:
            cells[x, FLOOR_Y : FLOOR_Y + DOOR_H, z] = True
    xs, ys, zs = np.nonzero(cells)
    box = [int(xs.min()), int(ys.min()), int(zs.min()), int(xs.max()), int(ys.max()), int(zs.max())]
    return Doorway(cells=cells, facing=FACING[d], box=box)


def find_doorway(occ: np.ndarray, inner: np.ndarray) -> Doorway | None:
    """The doorway into sealed rooms that the model suggests: 2 wide, through the wall where a porch
    or lintel covers the way out, in the middle of the covered stretch. None without such a cue."""
    best = None
    for d in DIRS:
        covered = {k: v for k, v in _lanes(occ, inner, d).items() if v["covered"]}
        pair = _best_pair(covered, d)
        if pair is None:
            continue
        score = (len(covered), -sum(len(covered[k]["path"]) for k in pair))
        if best is None or score > best[0]:
            best = (score, d, covered, pair)
    if best is None:
        return None
    _, d, lanes, pair = best
    return _doorway(occ, lanes, pair, d)


def suggestions(occ: np.ndarray, inner: np.ndarray) -> list[Doorway]:
    """One doorway per side that would open the sealed rooms (shortest cut, middle of the side), for
    the author to pick from when the model shows no entrance."""
    out = []
    for d in DIRS:
        lanes = _lanes(occ, inner, d)
        pair = _best_pair(lanes, d)
        if pair is not None:
            out.append(_doorway(occ, lanes, pair, d))
    return out
