"""Luanti schematic (.mts) writer/reader.

Layout (engine src/mapgen/mg_schematic.cpp serializeToMts, src/mapnode.cpp serializeBulk):

    u32  0x4D54534D ("MTSM")
    u16  version (4)
    s16  size x, y, z
    u8   y-slice probability, one per y (0..127)
    u16  number of names, then per name: u16 length + bytes
    zlib( u16 content id for every node, then u8 param1 for every node, then u8 param2 for every node )

Nodes are ordered z (outer), y, x (inner): index = z*X*Y + y*X + x. param1 holds the
placement probability in bits 0-6 (0 = never, 127 = always) and per-node force placement in bit 7.
Arrays in this module are indexed [x, y, z]; `_flat` converts to engine order.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

import numpy as np

SIGNATURE = 0x4D54534D
VERSION = 4
PROB_NEVER = 0
PROB_ALWAYS = 0x7F
FORCE_PLACE = 0x80


@dataclass
class Grid:
    names: list[str]
    content: np.ndarray  # uint16 [x, y, z], index into names
    param1: np.ndarray  # uint8 [x, y, z]
    param2: np.ndarray  # uint8 [x, y, z]
    yslice: np.ndarray  # uint8 [y]

    @property
    def size(self) -> tuple[int, int, int]:
        x, y, z = self.content.shape
        return int(x), int(y), int(z)

    def counts(self) -> dict[str, int]:
        """Placed nodes per name (probability > 0)."""
        placed = (self.param1 & 0x7F) > 0
        ids, n = np.unique(self.content[placed], return_counts=True)
        return {self.names[int(i)]: int(c) for i, c in zip(ids, n, strict=True)}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Grid):
            return NotImplemented
        return (
            self.names == other.names
            and np.array_equal(self.content, other.content)
            and np.array_equal(self.param1, other.param1)
            and np.array_equal(self.param2, other.param2)
            and np.array_equal(self.yslice, other.yslice)
        )


def _flat(a: np.ndarray) -> np.ndarray:
    return a.transpose(2, 1, 0).ravel()


def _unflat(a: np.ndarray, size: tuple[int, int, int]) -> np.ndarray:
    x, y, z = size
    return a.reshape(z, y, x).transpose(2, 1, 0).copy()


def to_mts(grid: Grid) -> bytes:
    x, y, z = grid.size
    if max(x, y, z) > 32767 or min(x, y, z) < 1:
        raise ValueError(f"invalid schematic size {grid.size}")
    if len(grid.names) > 65535:
        raise ValueError("too many node names")
    if grid.yslice.shape != (y,):
        raise ValueError("yslice must have one entry per y")
    out = bytearray(struct.pack(">IH3h", SIGNATURE, VERSION, x, y, z))
    out += bytes(grid.yslice.astype(np.uint8))
    out += struct.pack(">H", len(grid.names))
    for name in grid.names:
        raw = name.encode("utf-8")
        out += struct.pack(">H", len(raw)) + raw
    body = (
        _flat(grid.content).astype(">u2").tobytes()
        + _flat(grid.param1).astype(np.uint8).tobytes()
        + _flat(grid.param2).astype(np.uint8).tobytes()
    )
    out += zlib.compress(body, 9)
    return bytes(out)


def read_mts(data: bytes) -> Grid:
    sig, version, x, y, z = struct.unpack_from(">IH3h", data, 0)
    if sig != SIGNATURE:
        raise ValueError("not a Luanti schematic (bad signature)")
    if version < 3 or version > 4:
        raise ValueError(f"unsupported schematic version {version}")
    off = 12
    yslice = np.frombuffer(data, np.uint8, y, off).copy()
    off += y
    (count,) = struct.unpack_from(">H", data, off)
    off += 2
    names = []
    for _ in range(count):
        (n,) = struct.unpack_from(">H", data, off)
        off += 2
        names.append(data[off : off + n].decode("utf-8"))
        off += n
    body = zlib.decompress(data[off:])
    total = x * y * z
    if len(body) != total * 4:
        raise ValueError("schematic node data has the wrong length")
    size = (x, y, z)
    content = _unflat(np.frombuffer(body, ">u2", total, 0).astype(np.uint16), size)
    param1 = _unflat(np.frombuffer(body, np.uint8, total, total * 2), size)
    param2 = _unflat(np.frombuffer(body, np.uint8, total, total * 3), size)
    if version < 4:  # v3 used 0..255 probabilities
        param1 = param1 >> 1
        yslice = yslice >> 1
    return Grid(names, content, param1, param2, yslice)


def to_lua(grid: Grid) -> str:
    """Lua table form (as core.serialize_schematic(..., "lua") writes it), for fixtures and debugging."""
    x, y, z = grid.size
    lines = ["schematic = {", f"\tsize = {{x={x}, y={y}, z={z}}},", "\tyslice_prob = {"]
    for i, p in enumerate(grid.yslice):
        lines.append(f"\t\t{{ypos={i}, prob={int(p) * 2}}},")
    lines += ["\t},", "\tdata = {"]
    c, p1, p2 = _flat(grid.content), _flat(grid.param1), _flat(grid.param2)
    for i in range(len(c)):
        prob = int(p1[i] & 0x7F) * 2
        force = ", force_place=true" if p1[i] & FORCE_PLACE else ""
        lines.append(f'\t\t{{name="{grid.names[int(c[i])]}", prob={prob}, param2={int(p2[i])}{force}}},')
    lines += ["\t},", "}", ""]
    return "\n".join(lines)


def empty(size: tuple[int, int, int], names: list[str] | None = None) -> Grid:
    """A grid of `air` with probability 0 everywhere (places nothing)."""
    names = names or ["air"]
    if names[0] != "air":
        raise ValueError("names[0] must be air")
    return Grid(
        names=list(names),
        content=np.zeros(size, np.uint16),
        param1=np.zeros(size, np.uint8),
        param2=np.zeros(size, np.uint8),
        yslice=np.full(size[1], PROB_ALWAYS, np.uint8),
    )
