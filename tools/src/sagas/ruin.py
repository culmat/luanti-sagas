"""Make a structure look ruined: erosion, placement variation, debris fill, moss.

Everything is seeded (ruin.seed, or crc32 of the landmark id) so builds are reproducible.
"""

from __future__ import annotations

import zlib

import numpy as np
from scipy import ndimage

from .config import Ruin

_SIX = ndimage.generate_binary_structure(3, 1)
_SIX[1, 1, 1] = False


def rng_for(ruin: Ruin, landmark_id: str) -> np.random.Generator:
    return np.random.default_rng(ruin.seed or zlib.crc32(landmark_id.encode()))


def exposed_faces(occ: np.ndarray) -> np.ndarray:
    filled = ndimage.convolve(occ.astype(np.int8), _SIX.astype(np.int8), mode="constant", cval=0)
    return np.where(occ, 6 - filled, 0)


def remove_small(occ: np.ndarray, min_size: int) -> np.ndarray:
    if min_size <= 1 or not occ.any():
        return occ
    labels, n = ndimage.label(occ, structure=np.ones((3, 3, 3), bool))
    sizes = np.bincount(labels.ravel())
    small = sizes < min_size
    small[0] = False
    return occ & ~small[labels]


def erode(occ: np.ndarray, strength: float, rng: np.random.Generator, min_component: int) -> np.ndarray:
    """Remove exposed voxels, more near the top. Layer 0 (the footing) is kept."""
    if strength <= 0:
        return occ
    occ = occ.copy()
    Y = occ.shape[1]
    h = (np.arange(Y) / max(1, Y - 1)) ** 2
    weight = (0.25 + 0.75 * h)[None, :, None]
    for _ in range(2):
        exp = exposed_faces(occ) / 6.0
        p = np.clip(strength * weight * exp * 2.0, 0, 1)
        drop = (rng.random(occ.shape) < p) & occ
        drop[:, 0, :] = False
        occ &= ~drop
    return remove_small(occ, max(min_component, 4))


def variation_prob(occ: np.ndarray, normal_up: np.ndarray, strength: float) -> np.ndarray:
    """Per-voxel probability (0..127): exposed top voxels may be missing in a given placement."""
    prob = np.full(occ.shape, 127, np.uint8)
    if strength > 0:
        prob[occ & normal_up] = 127 - int(round(strength * 64))
    return prob
