"""Offline preview: a 2x2 sheet (top, front, side, isometric) rendered with numpy + Pillow (no GL)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import palette, vocab
from .build import BuildResult

BG = (236, 236, 232)
INK = (40, 40, 40)


def voxel_colors(res: BuildResult) -> np.ndarray:
    """uint8 [x, y, z, 3] display colour of every placed voxel (classes use their reference colour)."""
    g = res.grid
    out = np.zeros((*g.size, 3), np.uint8)
    pal = palette.rgb_array()
    classes = vocab.classes()
    for i, name in enumerate(g.names):
        sel = (g.content == i) & ((g.param1 & 0x7F) > 0)
        if name == "sagas:color":
            out[sel] = pal[g.param2[sel]]
        elif name.startswith("sagas:m_"):
            out[sel] = classes[name[len("sagas:m_") :]].rgb
    return out


def _placed(res: BuildResult) -> np.ndarray:
    g = res.grid
    air = g.names.index("air")
    return (g.content != air) & ((g.param1 & 0x7F) > 0)


def _ortho(occ: np.ndarray, col: np.ndarray, axis: int, reverse: bool) -> np.ndarray:
    """First voxel hit along `axis`; returns an RGBA-ish uint8 image [u, v, 3] plus mask via alpha."""
    o = np.flip(occ, axis) if reverse else occ
    c = np.flip(col, axis) if reverse else col
    hit = o.any(axis=axis)
    depth = o.argmax(axis=axis)
    n = occ.shape[axis]
    img = np.take_along_axis(c, np.expand_dims(depth, axis)[..., None].repeat(3, -1), axis=axis).squeeze(axis)
    shade = 1.0 - 0.45 * (depth / max(1, n - 1))
    img = (img.astype(np.float32) * shade[..., None]).clip(0, 255).astype(np.uint8)
    img[~hit] = BG
    return img


def _panel(img: np.ndarray, size: int) -> Image.Image:
    h, w = img.shape[:2]
    scale = max(1, min(size // max(1, w), size // max(1, h)))
    pil = Image.fromarray(img, "RGB").resize((w * scale, h * scale), Image.NEAREST)
    canvas = Image.new("RGB", (size, size), BG)
    canvas.paste(pil, ((size - pil.width) // 2, (size - pil.height) // 2))
    return canvas


def _iso(occ: np.ndarray, col: np.ndarray, size: int) -> Image.Image:
    X, Y, Z = occ.shape
    pad = np.pad(occ, 1)
    up = occ & ~pad[1:-1, 2:, 1:-1]
    px = occ & ~pad[2:, 1:-1, 1:-1]
    pz = occ & ~pad[1:-1, 1:-1, 2:]
    vis = up | px | pz
    idx = np.argwhere(vis)
    if len(idx) == 0:
        return Image.new("RGB", (size, size), BG)
    order = np.argsort(idx.sum(axis=1), kind="stable")
    idx = idx[order]
    cos30, sin30 = 0.8660254, 0.5
    span_x = (X + Z) * cos30
    span_y = (X + Z) * sin30 + Y
    s = 0.92 * size / max(span_x, span_y)
    ox = Z * cos30 * s + (size - span_x * s) / 2
    oy = Y * s + (size - span_y * s) / 2

    def p(x, y, z):
        return (ox + (x - z) * cos30 * s, oy + ((x + z) * sin30 - y) * s)

    img = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(img)
    for x, y, z in idx:
        c = col[x, y, z].astype(np.float32)
        if pz[x, y, z]:
            d.polygon(
                [p(x, y, z + 1), p(x + 1, y, z + 1), p(x + 1, y + 1, z + 1), p(x, y + 1, z + 1)],
                fill=tuple(int(v) for v in c * 0.62),
            )
        if px[x, y, z]:
            d.polygon(
                [p(x + 1, y, z), p(x + 1, y + 1, z), p(x + 1, y + 1, z + 1), p(x + 1, y, z + 1)],
                fill=tuple(int(v) for v in c * 0.8),
            )
        if up[x, y, z]:
            d.polygon(
                [p(x, y + 1, z), p(x + 1, y + 1, z), p(x + 1, y + 1, z + 1), p(x, y + 1, z + 1)],
                fill=tuple(int(v) for v in c),
            )
    return img


def render(res: BuildResult, size: int = 1024) -> Image.Image:
    occ = _placed(res)
    col = voxel_colors(res)
    half = size // 2
    # arrays are [x, y, z]; images are [row, col]
    top = _ortho(occ, col, axis=1, reverse=True).transpose(1, 0, 2)  # rows = z, cols = x
    front = np.flip(_ortho(occ, col, axis=2, reverse=False).transpose(1, 0, 2), 0)  # rows = y (top first)
    side = np.flip(_ortho(occ, col, axis=0, reverse=True), 0)  # rows = y (top first), cols = z
    sheet = Image.new("RGB", (size, size + 28), BG)
    sheet.paste(_panel(top, half), (0, 0))
    sheet.paste(_panel(front, half), (half, 0))
    sheet.paste(_panel(side, half), (0, half))
    sheet.paste(_iso(occ, col, half), (half, half))
    d = ImageDraw.Draw(sheet)
    x, y, z = res.size
    label = (
        f"{res.landmark.qualified_id}  {x}x{y}x{z}  {res.node_count} nodes  "
        f"materials: {res.landmark.materials.mode}  site: {', '.join(res.landmark.placement.site)}"
    )
    d.text((8, size + 8), label, fill=INK)
    d.text((8, 6), "top", fill=INK)
    d.text((half + 8, 6), "front", fill=INK)
    d.text((8, half + 6), "side", fill=INK)
    return sheet


def write(res: BuildResult, path: Path, size: int = 1024) -> None:
    render(res, size).save(path, optimize=True)
