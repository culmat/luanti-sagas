from conftest import box_txt, saga_toml
from sagas import build, config, legacy, pipeline, registry, schematic, voxels


def test_build_box(repo, tmp_path):
    p = saga_toml(repo, "test", "box", "[ruin]\nenabled = true\ndebris_height = 2\n")
    saga = config.load(p)
    model = legacy.read_txt(box_txt(tmp_path / "box.txt", size=(7, 5, 7)))
    res = build.build(saga, model)
    g = res.grid
    assert g.names == ["air", "sagas:m_debris", "sagas:m_stone"]
    counts = g.counts()
    assert counts["sagas:m_stone"] == model.count
    assert counts["sagas:m_debris"] == 25 + 2  # interior 5x5 at y=1 plus the doorway
    air = g.names.index("air")
    # interior air above the debris is carved (placed), outside air never placed
    assert g.content[3, 3, 3] == air and g.param1[3, 3, 3] == 0xFF
    assert res.anchor == (3, 0, 3)
    assert schematic.read_mts(schematic.to_mts(g)) == g


def test_pack_files_and_check(repo, tmp_path):
    for sid in ("box", "hut"):
        p = saga_toml(repo, "test", sid)
        saga = config.load(p)
        voxels.write(legacy.read_txt(box_txt(tmp_path / f"{sid}.txt")), saga.vx_path)
    tb = pipeline.build_theme(repo, "test")
    pack = repo.pack_dir("test")
    assert (pack / "schematics" / "box.mts").exists() and (pack / "registry.lua").exists()
    reg = (pack / "registry.lua").read_text()
    assert 'id = "sagas_test:box"' in reg and 'schematic = P .. "hut.mts"' in reg
    assert "depends = sagas" in (pack / "mod.conf").read_text()
    assert "CC0-1.0" in (pack / "LICENSE").read_text()
    assert len(tb.results) == 2
    assert pipeline.build_theme(repo, "test", check=True).stale == []
    (pack / "registry.lua").write_text("-- edited")
    assert pipeline.build_theme(repo, "test", check=True).stale == ["registry.lua"]


def test_lua_str_escapes():
    assert registry.lua_str('a"b\\c\nd\x01') == '"a\\"b\\\\c\\nd\\001"'


def test_pack_media_license():
    assert registry.pack_media_license(["CC0-1.0"]) == "CC0-1.0"
    assert registry.pack_media_license(["CC0-1.0", "CC-BY-4.0"]) == "CC-BY-4.0"
    assert registry.pack_media_license(["CC-BY-SA-3.0", "CC0-1.0"]) == "CC-BY-SA-3.0"
    assert registry.pack_media_license(["CC-BY-SA-3.0", "CC-BY-SA-4.0"]) == "CC-BY-SA-4.0"
