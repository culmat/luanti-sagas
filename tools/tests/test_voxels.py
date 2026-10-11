import numpy as np
import pytest

from sagas import legacy, voxels
from sagas.config import Transform


def test_legacy_formats(tmp_path):
    p = tmp_path / "m.txt"
    p.write_text("# comment\n3, 4, 5, 10, 20, 30\n4 4 5\n5,6,7\n")
    m = legacy.read_txt(p)
    assert m.size == (3, 3, 3)  # shifted to start at 0
    assert m.count == 3
    assert m.has_rgb[0, 0, 0] and tuple(m.rgb[0, 0, 0]) == (10, 20, 30)
    assert not m.has_rgb[1, 0, 0]


def test_legacy_rejects_garbage(tmp_path):
    p = tmp_path / "m.txt"
    p.write_text("1, 2\n")
    with pytest.raises(ValueError):
        legacy.read_txt(p)


def test_vx_roundtrip_deterministic(tmp_path):
    m = voxels.VoxelModel.empty((3, 4, 5))
    m.occ[1, 2, 3] = m.occ[0, 0, 0] = True
    m.rgb[1, 2, 3] = (1, 2, 3)
    m.has_rgb[1, 2, 3] = True
    m.part[1, 2, 3] = 0
    m.parts = [("wall", "Brick [b.jpg]")]
    m.normal = voxels.compute_normals(m.occ)
    a, b = tmp_path / "a.vx.gz", tmp_path / "b.vx.gz"
    voxels.write(m, a)
    voxels.write(m, b)
    assert a.read_bytes() == b.read_bytes()
    r = voxels.read(a)
    for f in ("occ", "rgb", "has_rgb", "part", "normal"):
        assert np.array_equal(getattr(r, f), getattr(m, f)), f
    assert r.parts == [("wall", "Brick [b.jpg]")]


def test_normals():
    occ = np.zeros((1, 3, 1), bool)
    occ[0, :, 0] = True
    n = voxels.compute_normals(occ)
    assert list(n[0, :, 0]) == [voxels.NORMAL_DOWN, voxels.NORMAL_SIDE, voxels.NORMAL_UP]


def test_orient_flips_x_and_rotates():
    m = voxels.VoxelModel.empty((3, 1, 2))
    m.occ[0, 0, 0] = True
    o = voxels.orient(m, Transform())
    assert o.occ[2, 0, 0]  # x flipped for the left-handed frame
    r = voxels.orient(m, Transform(rotate_y=90))
    assert r.occ.shape == (2, 1, 3)
