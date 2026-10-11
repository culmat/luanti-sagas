import struct
import zlib

import numpy as np
import pytest

from sagas import schematic


def tiny_grid():
    g = schematic.empty((2, 1, 3), ["air", "sagas:color", "sagas:m_stone"])
    g.content[1, 0, 0] = 2
    g.param1[1, 0, 0] = 0x7F | 0x80
    g.content[0, 0, 2] = 1
    g.param1[0, 0, 2] = 0x7F
    g.param2[0, 0, 2] = 42
    return g


def test_layout_matches_engine_format():
    g = tiny_grid()
    data = schematic.to_mts(g)
    # header written independently of the writer, following src/mapgen/mg_schematic.cpp
    head = struct.pack(">IH3h", 0x4D54534D, 4, 2, 1, 3) + bytes([0x7F])
    head += struct.pack(">H", 3)
    for n in (b"air", b"sagas:color", b"sagas:m_stone"):
        head += struct.pack(">H", len(n)) + n
    assert data.startswith(head)
    body = zlib.decompress(data[len(head) :])
    # nodes in z, y, x order (x fastest): (0,0,0) (1,0,0) (0,0,1) (1,0,1) (0,0,2) (1,0,2)
    ids = struct.unpack(">6H", body[:12])
    assert ids == (0, 2, 0, 0, 1, 0)
    assert list(body[12:18]) == [0, 0xFF, 0, 0, 0x7F, 0]
    assert list(body[18:24]) == [0, 0, 0, 0, 42, 0]


def test_roundtrip():
    g = tiny_grid()
    assert schematic.read_mts(schematic.to_mts(g)) == g


def test_random_roundtrip(rng):
    size = (5, 7, 3)
    g = schematic.empty(size, ["air", "a:b", "c:d"])
    g.content[:] = rng.integers(0, 3, size)
    g.param1[:] = rng.integers(0, 256, size)
    g.param2[:] = rng.integers(0, 256, size)
    assert schematic.read_mts(schematic.to_mts(g)) == g


def test_counts_ignore_never_placed():
    assert tiny_grid().counts() == {"sagas:m_stone": 1, "sagas:color": 1}


def test_lua_form():
    lua = schematic.to_lua(tiny_grid())
    assert "size = {x=2, y=1, z=3}" in lua
    assert '{name="sagas:m_stone", prob=254, param2=0, force_place=true}' in lua
    assert '{name="sagas:color", prob=254, param2=42}' in lua


def test_rejects_bad_signature():
    with pytest.raises(ValueError):
        schematic.read_mts(b"XXXX" + bytes(20))


def test_deterministic():
    assert schematic.to_mts(tiny_grid()) == schematic.to_mts(tiny_grid())
    assert np.array_equal(schematic.read_mts(schematic.to_mts(tiny_grid())).yslice, [0x7F])
