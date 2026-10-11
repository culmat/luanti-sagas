"""Base textures of the core mod, generated so they stay reproducible (CC0, see mods/sagas/LICENSE)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


def white() -> Image.Image:
    return Image.new("RGB", (16, 16), (255, 255, 255))


def placeholder() -> Image.Image:
    """Light tile with diagonal stripes: tinted per class, it is obviously a stand-in."""
    a = np.full((16, 16, 3), 235, np.uint8)
    yy, xx = np.mgrid[0:16, 0:16]
    a[((xx + yy) % 8) < 2] = 170
    a[[0, -1], :] = 120
    a[:, [0, -1]] = 120
    return Image.fromarray(a, "RGB")


def water() -> Image.Image:
    rng = np.random.default_rng(7)
    a = np.zeros((16, 16, 4), np.uint8)
    base = np.array([46, 92, 180], np.int16)
    noise = rng.integers(-14, 15, (16, 16, 1))
    a[..., :3] = np.clip(base + noise, 0, 255).astype(np.uint8)
    a[..., 3] = 170
    return Image.fromarray(a, "RGBA")


TEXTURES = {"sagas_white.png": white, "sagas_placeholder.png": placeholder, "sagas_water.png": water}


def write_all(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    out = []
    for name, fn in TEXTURES.items():
        p = directory / name
        fn().save(p, optimize=False, compress_level=9)
        out.append(p)
    return out
