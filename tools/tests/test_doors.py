import numpy as np
import pytest

from conftest import box_txt, landmark_toml
from sagas import build, config, doors, legacy, lint
from sagas.errors import ConfigError
from sagas.interior import interior_mask


def hut(porch=False, size=12, wall=1):
    """A closed hut: floor at layer 0, walls x/z = 2..size-3 up to layer 4, roof at layer 5. With
    porch (size 12), a lintel and porch roof at layers 2-3 in front of the +z wall (x = 4..7, two deep)."""
    occ = np.zeros((size, 8, size), bool)
    occ[:, 0, :] = True
    lo, hi = 2, size - 3
    for t in range(wall):
        occ[lo + t, 1:5, lo : hi + 1] = True
        occ[hi - t, 1:5, lo : hi + 1] = True
        occ[lo : hi + 1, 1:5, lo + t] = True
        occ[lo : hi + 1, 1:5, hi - t] = True
    occ[lo : hi + 1, 5, lo : hi + 1] = True
    if porch:
        occ[4:8, 2:4, 10:12] = True
    return occ


def test_porch_gives_the_doorway():
    occ = hut(porch=True)
    inner = interior_mask(occ, 2)
    assert doors.sealed(occ, inner)
    d = doors.find_doorway(occ, inner)
    assert d is not None and d.facing == "+z"
    assert d.box == [5, 1, 9, 6, 2, 11]  # middle of the porch, through the wall and under the lintel
    assert not doors.sealed(occ & ~d.cells, inner)


def test_no_cue_no_guess_but_suggestions():
    occ = hut()
    inner = interior_mask(occ, 2)
    assert doors.sealed(occ, inner)
    assert doors.find_doorway(occ, inner) is None
    sugg = doors.suggestions(occ, inner)
    assert sorted(s.facing for s in sugg) == ["+x", "+z", "-x", "-z"]
    for s in sugg:
        assert not doors.sealed(occ & ~s.cells, inner), s.facing


def test_a_real_doorway_is_a_way_in():
    occ = hut()
    occ[5:7, 1:3, 9] = False
    assert not doors.sealed(occ, interior_mask(occ, 2))


def test_notches_and_cracks_are_no_way_in():
    occ = hut(size=14, wall=2)  # room 6 x 6 inside walls 2 thick
    occ[5, 1:3, 11] = False  # outer layer of the wall: a notch, not a door
    occ[6, 1, 10] = False  # a 1 high crack in the inner layer
    assert doors.sealed(occ, interior_mask(occ, 2))


def test_hollows_lower_than_a_player_are_no_rooms():
    occ = hut()
    occ[2:10, 2, 2:10] = True  # a slab at layer 2: the hollow below is 1 high
    assert not doors.sealed(occ, interior_mask(occ, 2))


def test_openings_mask():
    m = doors.openings_mask((4, 4, 4), [[2, 1, 3, 1, 2, 3]])
    assert m.sum() == 4 and m[1:3, 1:3, 3].all()


def test_voxel_config(repo):
    p = landmark_toml(repo, "test", "okay", '[voxel]\ndoorway = "none"\nopenings = [[1, 1, 0, 2, 2, 0]]\n')
    v = config.load(p).voxel
    assert v.doorway == "none" and v.openings == [[1, 1, 0, 2, 2, 0]]
    with pytest.raises(ConfigError, match="voxel.openings"):
        config.load(landmark_toml(repo, "test", "bad", "[voxel]\nopenings = [[1, 2]]\n"))
    with pytest.raises(ConfigError, match="voxel.doorway"):
        config.load(landmark_toml(repo, "test", "bad2", '[voxel]\ndoorway = "maybe"\n'))


def _closed_box(repo, tmp_path, extra=""):
    landmark = config.load(landmark_toml(repo, "test", "box", extra))
    # a box with a roof, so its inside is a room; box_txt has no roof, so add one
    model = legacy.read_txt(box_txt(tmp_path / "box.txt", size=(7, 5, 7), door=False))
    model.occ[:, 4, :] = True
    return landmark, model


def test_build_cuts_openings_and_lint_reports_sealed(repo, tmp_path):
    landmark, model = _closed_box(repo, tmp_path)
    res = build.build(landmark, model)
    assert res.sealed and len(res.suggestions) == 4
    codes = [f.code for f in lint.check_saga(landmark, res)]
    assert "L016" in codes

    landmark, model = _closed_box(repo, tmp_path, "[voxel]\nopenings = [[3, 1, 0, 3, 2, 0]]\n")
    res = build.build(landmark, model)
    assert not res.sealed
    g = res.grid
    assert g.content[3, 1, 0] == g.names.index("air") and g.param1[3, 1, 0] & 0x7F  # forced air
    assert "L016" not in [f.code for f in lint.check_saga(landmark, res)]

    landmark, model = _closed_box(repo, tmp_path, '[voxel]\ndoorway = "none"\n')
    assert not build.build(landmark, model).sealed
