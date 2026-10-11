from sagas import build, config, handbuilt, schematic


def test_classify_nodes():
    assert handbuilt.classify_node("default:stonebrick") == ("stone", None)
    assert handbuilt.classify_node("stairs:stair_stonebrick") == ("stone", None)
    assert handbuilt.classify_node("mcl_stairs:slab_wood") == ("wood", None)
    assert handbuilt.classify_node("mcl_trees:tree_spruce") == ("log", None)
    assert handbuilt.classify_node("wool:red") == ("color", (147, 34, 34))
    assert handbuilt.classify_node("mcl_colorblocks:concrete_light_blue")[0] == "color"
    assert handbuilt.classify_node("mymod:mystery") == ("", None)


def test_exported_schematic_becomes_saga(tmp_path):
    g = schematic.empty((3, 2, 1), ["air", "default:stonebrick", "mymod:mystery", "wool:blue"])
    g.content[0, 0, 0], g.content[1, 0, 0], g.content[2, 0, 0] = 1, 2, 3
    g.content[0, 1, 0] = 1
    g.param1[:] = 0x7F  # create_schematic exports everything with probability "always"
    g.content[1:, 1, 0] = 0  # air
    p = tmp_path / "hut.mts"
    p.write_bytes(schematic.to_mts(g))
    model, unknown = handbuilt.read_mts(p)
    assert unknown == ["mymod:mystery"]
    assert model.count == 4
    saga = config.parse({"id": "hut", "theme": "village", "title": "Hut", "source": {"kind": "handbuilt"},
                         "materials": {"default": "planks"}}, tmp_path / "village" / "hut" / "saga.toml")
    res = build.build(saga, model)
    assert res.grid.counts() == {"sagas:m_stone": 2, "sagas:m_planks": 1, "sagas:color": 1}
