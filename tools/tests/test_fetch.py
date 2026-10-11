import zipfile
from pathlib import Path

import pytest

from sagas import config, fetch
from sagas.errors import SagasError


def test_extract_member_and_siblings(tmp_path):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("pack/models/tower.dae", "<COLLADA/>")
        f.writestr("pack/models/stone.jpg", "jpg")
        f.writestr("pack/models/textures/moss.jpg", "jpg")
        f.writestr("pack/other/x.txt", "x")
    out = fetch.extract_member(z, "pack/models/tower.dae", tmp_path / "x")
    assert out.read_text() == "<COLLADA/>"
    assert (tmp_path / "x" / "stone.jpg").exists() and not (tmp_path / "x" / "x.txt").exists()
    assert (tmp_path / "x" / "textures" / "moss.jpg").exists()


def test_extract_rejects_traversal(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("../evil.dae", "x")
    with pytest.raises(SagasError, match="unsafe"):
        fetch.extract_member(z, "models/a.dae", tmp_path / "x")
    with pytest.raises(SagasError, match="unsafe"):
        fetch.extract_member(z, "../a.dae", tmp_path / "x")


def test_record_sha256(tmp_path):
    p = tmp_path / "tst" / "sss" / "landmark.toml"
    p.parent.mkdir(parents=True)
    p.write_text(
        'id = "sss"\nsaga = "tst"\ntitle = "S"\n\n[source]\nurl = "u"\nsha256 = ""\n\n[placement]\nsite = "plain"\n'
    )
    landmark = config.load(p)
    fetch.record_sha256(landmark, "ab" * 32)
    again = config.load(p)
    assert again.source.sha256 == "ab" * 32 and again.placement.site == ["plain"]


def test_fetch_from_local_copy(tmp_path):
    p = tmp_path / "tst" / "sss" / "landmark.toml"
    p.parent.mkdir(parents=True)
    p.write_text('id = "sss"\nsaga = "tst"\ntitle = "S"\n[source]\nfile = "m.obj"\nmanual = true\n')
    landmark = config.load(p)
    with pytest.raises(SagasError, match="manual"):
        fetch.fetch(landmark, tmp_path / "sources")
    src = tmp_path / "m.obj"
    src.write_text("v 0 0 0\n")
    dest, digest = fetch.fetch(landmark, tmp_path / "sources", src=src)
    assert dest == tmp_path / "sources" / "sss" / "m.obj" and len(digest) == 64
    assert fetch.cache_path(landmark, tmp_path / "sources") == dest
    assert Path(dest).read_text() == "v 0 0 0\n"
