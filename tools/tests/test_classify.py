import numpy as np

from sagas import interior
from sagas.classify import budget_findings, classify
from sagas.config import Materials, Rule
from sagas.voxels import VoxelModel, compute_normals


def model():
    m = VoxelModel.empty((2, 4, 1))
    m.occ[:] = True
    m.rgb[0, :, 0] = (128, 128, 128)
    m.has_rgb[0, :, 0] = True
    m.part[:] = 0
    m.part[1, :, 0] = 1
    m.parts = [("wall", "Stone [s.jpg]"), ("roof", "Tiles [roof_red.png]")]
    m.normal = compute_normals(m.occ)
    return m


def test_rules_first_match_wins():
    mats = Materials(
        mode="classes",
        rules=[Rule(match={"material": "*roof*"}, cls="roof_red"), Rule(match={"y": [0, 3]}, cls="brick")],
    )
    c = classify(model(), mats)
    assert c.class_counts() == {"roof_red": 4, "brick": 4}


def test_hybrid_and_palette_modes():
    c = classify(model(), Materials(mode="hybrid"))
    assert c.color_count == 4 and c.class_counts() == {"stone": 4}
    c = classify(model(), Materials(mode="palette"))
    assert c.color_count == 8


def test_normal_and_y_frac_rules():
    mats = Materials(mode="classes", rules=[Rule(match={"y_frac": [0.9, 1.0], "normal": "up"}, cls="thatch")])
    c = classify(model(), mats)
    assert c.class_counts() == {"thatch": 2, "stone": 6}


def test_color_rule():
    mats = Materials(mode="classes", rules=[Rule(match={"color": "#808080", "tol": 5}, cls="cobble")])
    assert classify(model(), mats).class_counts() == {"cobble": 4, "stone": 4}


def test_value_budget():
    mats = Materials(mode="classes", default="gold")
    msgs = budget_findings(classify(model(), mats), mats)
    assert msgs and "gold" in msgs[0]
    mats = Materials(mode="classes", default="gold", value_budget={"gold": 8})
    assert budget_findings(classify(model(), mats), mats) == []
    mats = Materials(mode="classes", default="gold", value_budget={"gold": 1000})
    assert "hard cap" in budget_findings(classify(model(), mats), mats)[0]


def test_interior_with_door():
    occ = np.zeros((7, 4, 7), bool)
    occ[:, 0, :] = True
    occ[0, :, :] = occ[-1, :, :] = occ[:, :, 0] = occ[:, :, -1] = True
    occ[3, 1:3, 0] = False  # door
    inner = interior.interior_mask(occ, close=1)
    assert not inner[:, 0, :].any()  # ground floor stays natural ground
    assert inner[3, 1, 3] and inner[1, 2, 5]
    assert inner[3, 1, 0]  # the doorway is carved too
    assert not inner[occ].any()
