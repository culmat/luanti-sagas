"""The fixed 256-colour palette of the `sagas:color` node.

Index layout (stable; changing it changes every colour landmark):
    0..23     neutral greys, L* 0..100 (index 0 = black)
    24..203   CIELCh lattice: 12 hues x 5 lightness x 3 chroma levels (25/55/90 % of the largest
              in-gamut chroma for that hue and lightness, capped at 70)
    204..255  52 hand-picked material anchors (stone, wood, thatch, moss, water, skin, metals)

Quantization is nearest neighbour in CIE Lab (CIE76) on fixed-point values, so results are
identical across platforms. No dithering: noise reads as dirt at node scale.
"""

from __future__ import annotations

import hashlib
import re
from functools import cache
from importlib import resources
from pathlib import Path

import numpy as np

GREYS = 24
HUES = tuple(range(0, 360, 30))
LIGHTNESS = (25, 40, 55, 70, 85)
CHROMA = (0.25, 0.55, 0.9)  # fractions of the largest in-gamut chroma (capped)
MAX_CHROMA = 70.0
ANCHORS = (
    "#d6c39a",
    "#e2c88f",
    "#b8642f",
    "#cfc8b8",
    "#8f6f62",
    "#3c3c3e",
    "#5a6068",
    "#b0603c",
    "#8e3b2c",
    "#a8907a",
    "#a07b4c",
    "#4a3420",
    "#d8cfa8",
    "#6b4e2e",
    "#9a6a4a",
    "#b05c34",
    "#c9ad5d",
    "#e0cc78",
    "#5a6e34",
    "#6aa84a",
    "#2f5a26",
    "#7cb850",
    "#355e3b",
    "#7a7a3a",
    "#e6dcc0",
    "#f2ead6",
    "#8a4a24",
    "#a87a3a",
    "#c06e48",
    "#4a9a84",
    "#e3b83c",
    "#c8ccd0",
    "#9aa0a8",
    "#2a4f8f",
    "#3d7fc4",
    "#b6d4f2",
    "#f4f8fa",
    "#8fc4ea",
    "#e0582a",
    "#1e1a28",
    "#f0c8a8",
    "#d09a70",
    "#a8704a",
    "#6a4430",
    "#8a1a1a",
    "#2a3a9a",
    "#6a3a8a",
    "#3aa070",
    "#40c0c0",
    "#f0a020",
    "#f0e4c0",
    "#2a2a2a",
)
FIXED = 64  # Lab fixed-point scale
_HEX = re.compile(r"^#[0-9a-f]{6}$")

_M = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
_M_INV = np.linalg.inv(_M)
_WHITE = np.array([0.95047, 1.0, 1.08883])
_D = 6.0 / 29.0


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """(n,3) uint8 -> (n,3) float64 Lab."""
    c = np.asarray(rgb, np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = lin @ _M.T / _WHITE
    f = np.where(xyz > _D**3, np.cbrt(xyz), xyz / (3 * _D * _D) + 4.0 / 29.0)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1)


def lab_to_linear(lab: np.ndarray) -> np.ndarray:
    lab = np.atleast_2d(np.asarray(lab, np.float64))
    fy = (lab[:, 0] + 16) / 116
    fx = fy + lab[:, 1] / 500
    fz = fy - lab[:, 2] / 200
    f = np.stack([fx, fy, fz], axis=1)
    xyz = np.where(f > _D, f**3, 3 * _D * _D * (f - 4.0 / 29.0)) * _WHITE
    return xyz @ _M_INV.T


def linear_to_srgb8(lin: np.ndarray) -> np.ndarray:
    lin = np.clip(lin, 0.0, 1.0)
    c = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)
    return np.rint(c * 255).astype(np.uint8)


def _in_gamut(L: float, C: float, h: float) -> bool:
    rad = np.deg2rad(h)
    lin = lab_to_linear([[L, C * np.cos(rad), C * np.sin(rad)]])[0]
    return bool(np.all(lin >= -1e-9) and np.all(lin <= 1 + 1e-9))


def _max_chroma(L: float, h: float) -> float:
    lo, hi = 0.0, MAX_CHROMA
    if _in_gamut(L, hi, h):
        return hi
    for _ in range(40):
        mid = (lo + hi) / 2
        if _in_gamut(L, mid, h):
            lo = mid
        else:
            hi = mid
    return lo


def _lch_to_hex(L: float, C: float, h: float) -> str:
    rad = np.deg2rad(h)
    rgb = linear_to_srgb8(lab_to_linear([[L, C * np.cos(rad), C * np.sin(rad)]]))[0]
    return "#{:02x}{:02x}{:02x}".format(*(int(v) for v in rgb))


def generate() -> list[str]:
    cols: list[str] = []
    for i in range(GREYS):
        cols.append(_lch_to_hex(100.0 * i / (GREYS - 1), 0.0, 0.0))
    for h in HUES:
        for L in LIGHTNESS:
            cmax = _max_chroma(float(L), float(h))
            for f in CHROMA:
                cols.append(_lch_to_hex(float(L), f * cmax, float(h)))
    cols.extend(ANCHORS)
    if len(cols) != 256:
        raise AssertionError(f"palette has {len(cols)} entries")
    if len(set(cols)) != 256:
        raise AssertionError("palette entries are not unique")
    return cols


@cache
def load() -> tuple[str, ...]:
    text = resources.files("sagas").joinpath("data/palette256.txt").read_text()
    cols = tuple(line.strip() for line in text.splitlines() if _HEX.match(line.strip()))
    if len(cols) != 256:
        raise ValueError("palette256.txt must contain 256 colours")
    return cols


def rgb_array() -> np.ndarray:
    return np.array([[int(c[i : i + 2], 16) for i in (1, 3, 5)] for c in load()], np.uint8)


@cache
def _lab_fixed() -> np.ndarray:
    return np.rint(srgb_to_lab(rgb_array()) * FIXED).astype(np.int64)


def quantize(rgb: np.ndarray) -> np.ndarray:
    """(n,3) uint8 colours -> (n,) uint8 palette indices (nearest in Lab, first index wins ties)."""
    rgb = np.asarray(rgb, np.uint8).reshape(-1, 3)
    if len(rgb) == 0:
        return np.zeros(0, np.uint8)
    uniq, inverse = np.unique(rgb, axis=0, return_inverse=True)
    lab = np.rint(srgb_to_lab(uniq) * FIXED).astype(np.int64)
    pal = _lab_fixed()
    best = np.empty(len(uniq), np.uint8)
    for start in range(0, len(uniq), 4096):
        chunk = lab[start : start + 4096]
        d = ((chunk[:, None, :] - pal[None, :, :]) ** 2).sum(axis=2)
        best[start : start + 4096] = d.argmin(axis=1)
    return best[inverse.ravel()]


def lab_distance(a: tuple[int, int, int], b: np.ndarray) -> np.ndarray:
    """Lab (CIE76) distance between one colour and (n,3) colours."""
    la = srgb_to_lab(np.array([a], np.uint8))[0]
    lb = srgb_to_lab(np.asarray(b, np.uint8).reshape(-1, 3))
    return np.sqrt(((lb - la) ** 2).sum(axis=1))


def write_text(path: Path) -> None:
    lines = ["# sagas:color palette, generated by `sagas palette --write`. Index = line number - 2.", *generate()]
    path.write_text("\n".join(lines) + "\n")


def write_png(path: Path) -> None:
    """16x16 PNG, read by the engine left-to-right, top-to-bottom (256 pixels)."""
    from PIL import Image

    img = Image.fromarray(rgb_array().reshape(16, 16, 3), "RGB")
    img.save(path, optimize=False, compress_level=9)


def png_matches(path: Path) -> bool:
    from PIL import Image

    with Image.open(path) as img:
        px = np.asarray(img.convert("RGB")).reshape(-1, 3)
    return px.shape == (256, 3) and np.array_equal(px, rgb_array())


def sha256() -> str:
    return hashlib.sha256("\n".join(load()).encode()).hexdigest()
