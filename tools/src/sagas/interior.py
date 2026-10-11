"""Find the air inside a structure that should replace terrain when it is placed ("carve").

Per horizontal layer, the occupancy is closed with a disk of radius `close` (bridging doors and
windows up to 2*close wide); air that is then not reachable from the layer border is interior.
Layer 0 is never carved, so courtyards and halls keep the natural ground as floor.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage


def _disk(r: int) -> np.ndarray:
    if r <= 0:
        return np.ones((1, 1), bool)
    y, x = np.ogrid[-r : r + 1, -r : r + 1]
    return x * x + y * y <= r * r + r


def interior_mask(occ: np.ndarray, close: int = 2) -> np.ndarray:
    X, Y, Z = occ.shape
    out = np.zeros_like(occ)
    disk = _disk(close)
    pad = close + 1
    for y in range(1, Y):
        layer = occ[:, y, :]
        if not layer.any():
            continue
        padded = np.pad(layer, pad)
        closed = ndimage.binary_closing(padded, structure=disk) | padded
        labels, _ = ndimage.label(~closed)
        border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
        enclosed = ~np.isin(labels, border) & ~closed
        # gap voxels of the closing (doorways) count as interior too
        enclosed |= closed & ~padded & ndimage.binary_dilation(enclosed, iterations=close)
        out[:, y, :] = enclosed[pad:-pad, pad:-pad] & ~layer
    return out
