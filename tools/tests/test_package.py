import zipfile

from sagas import package


def test_zip_layout_and_export_ignore(tmp_path):
    mods = tmp_path / "mods"
    core = mods / "sagas"
    (core / "test").mkdir(parents=True)
    (core / "init.lua").write_text("-- x")
    (core / "test" / "mtt.lua").write_text("-- t")
    (core / ".luacheckrc").write_text("")
    (core / ".gitattributes").write_text("/test export-ignore\n/.luacheckrc export-ignore\n")
    (mods / "sagas_ruins").mkdir()
    (mods / "sagas_ruins" / "mod.conf").write_text("name = sagas_ruins\n")
    (mods / "modpack.conf").write_text("name = sagas_pack\n")

    out = tmp_path / "a.zip"
    package.build_zip(core, out)
    assert sorted(zipfile.ZipFile(out).namelist()) == ["sagas/.gitattributes", "sagas/init.lua"]

    pack = tmp_path / "pack.zip"
    package.build_zip(mods, pack, "sagas_pack")
    names = sorted(zipfile.ZipFile(pack).namelist())
    assert "sagas_pack/sagas/test/mtt.lua" not in names and "sagas_pack/sagas/init.lua" in names
    assert "sagas_pack/sagas_ruins/mod.conf" in names and "sagas_pack/modpack.conf" in names

    again = tmp_path / "b.zip"
    package.build_zip(core, again)
    assert out.read_bytes() == again.read_bytes()
