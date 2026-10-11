import numpy as np

from conftest import CUBE_COLORS, write_cube_obj, write_vox
from sagas import load, vox
from sagas import voxelize as vz
from sagas.config import Transform, Voxel


def test_cube_faces_get_their_colours(tmp_path):
    m = load.load_model(write_cube_obj(tmp_path))
    assert len(m.parts) == 6
    v = vz.voxelize(m, Transform(target_size=8, up="y"), Voxel())
    X, Y, Z = v.size
    assert v.size == (9, 9, 9)
    # top face (+y) is blue, bottom yellow; interior is empty (shell)
    top = v.rgb[1:-1, Y - 1, 1:-1].reshape(-1, 3)
    assert np.all(np.abs(top.astype(int) - CUBE_COLORS["py"]).max(axis=1) <= 2)
    bottom = v.rgb[1:-1, 0, 1:-1].reshape(-1, 3)
    assert np.all(np.abs(bottom.astype(int) - CUBE_COLORS["ny"]).max(axis=1) <= 2)
    assert not v.occ[4, 4, 4]
    # normals: top face up, bottom face down
    assert (v.normal[1:-1, Y - 1, 1:-1] == 1).all() and (v.normal[1:-1, 0, 1:-1] == 2).all()
    # parts carry the material names
    assert sorted(mat for _, mat in v.parts) == sorted(CUBE_COLORS)


def test_solid_fill(tmp_path):
    m = load.load_model(write_cube_obj(tmp_path))
    v = vz.voxelize(m, Transform(target_size=8, up="y"), Voxel(mode="solid"))
    assert v.occ.all()


def test_z_up_and_handedness(tmp_path):
    m = load.load_model(write_cube_obj(tmp_path))
    v = vz.voxelize(m, Transform(target_size=8, up="z"), Voxel())
    # source +z face (magenta) becomes the top
    top = v.rgb[1:-1, -1, 1:-1].reshape(-1, 3)
    assert np.all(np.abs(top.astype(int) - CUBE_COLORS["pz"]).max(axis=1) <= 2)
    # source +x face ends up at low x after the left-handed flip
    side = v.rgb[0, 1:-1, 1:-1].reshape(-1, 3)
    assert np.all(np.abs(side.astype(int) - CUBE_COLORS["px"]).max(axis=1) <= 2)


def test_exclude(tmp_path):
    m = load.load_model(write_cube_obj(tmp_path))
    v = vz.voxelize(m, Transform(target_size=8, up="y"), Voxel(exclude=["py", "ny"]))
    assert not v.occ[1:-1, :, 1:-1][:, [0, -1], :].any() or v.size[1] < 9


def test_vox_reader(tmp_path):
    p = tmp_path / "t.vox"
    write_vox(p, (3, 2, 4), [(0, 0, 0, 1), (2, 1, 3, 2)], {1: (255, 0, 0), 2: (0, 0, 255)})
    v = vox.read_vox(p)
    assert v.count == 2
    assert v.size == (3, 4, 2)  # z (4) becomes y
    # vox z=3 is the top; vox (2, 1, 3) -> y 3, z = sy-1-1 = 0, x flipped -> 0
    assert v.occ[0, 3, 0] and tuple(v.rgb[0, 3, 0]) == (0, 0, 255)
    assert v.occ[2, 0, 1] and tuple(v.rgb[2, 0, 1]) == (255, 0, 0)
