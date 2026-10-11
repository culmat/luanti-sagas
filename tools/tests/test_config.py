from pathlib import Path

import pytest

from sagas import config
from sagas.errors import ConfigError


def parse(**data):
    base = {"id": "tower", "saga": "medieval", "title": "Tower"}
    base.update(data)
    return config.parse(base, Path("content/medieval/tower/landmark.toml"))


def test_defaults():
    s = parse()
    assert s.qualified_id == "sagas_medieval:tower"
    assert s.placement.site == ["plain"] and s.placement.biomes == ["any"]
    assert s.materials.context == "surroundings" and s.voxel.interior == "carve"


def test_site_expressions():
    s = parse(placement={"site": ["cliff+coast", "waterfall"], "exposure": "prominent"})
    assert s.placement.site == ["cliff+coast", "waterfall"]
    with pytest.raises(ConfigError, match="unknown site"):
        parse(placement={"site": "volcano"})
    with pytest.raises(ConfigError, match="more than one layer"):
        parse(placement={"site": "carve+cave_floor"})


def test_rarity_names_and_foundation_bool():
    s = parse(placement={"rarity": "legendary", "foundation": False})
    assert s.placement.rarity == 5000 and s.placement.foundation == 0


@pytest.mark.parametrize(
    "data,msg",
    [
        ({"colour": 1}, "unknown key"),
        ({"source": {"licence": "x"}}, "unknown key"),
        ({"id": "Bad Id"}, "must match"),
        ({"materials": {"default": "diamond"}}, "not a class"),
        ({"materials": {"rules": [{"match": {"y": [0, 3]}, "class": "brick", "color": True}]}}, "exactly one"),
        ({"materials": {"overrides": {"stone": "obsidian"}}}, "neither"),
        ({"placement": {"biomes": ["moon"]}}, "unknown tag"),
        ({"transform": {"rotate_y": 45}}, "rotate_y"),
        ({"placement": {"clear_above": 1}}, "true/false"),
    ],
)
def test_invalid(data, msg):
    with pytest.raises(ConfigError, match=msg):
        parse(**data)


def test_load_file(tmp_path):
    p = tmp_path / "medieval" / "tower" / "landmark.toml"
    p.parent.mkdir(parents=True)
    p.write_text('id = "tower"\nsaga = "medieval"\ntitle = "T"\n[placement]\nsite = "peak"\n')
    assert config.load(p.parent).placement.site == ["peak"]
