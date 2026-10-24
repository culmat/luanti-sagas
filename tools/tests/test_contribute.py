import json
import re
import shutil
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import write_cube_obj
from sagas import config, edit, hints, intake
from sagas.cli import app
from sagas.errors import ConfigError, SagasError

runner = CliRunner()
FORM = Path(__file__).parents[2] / ".github" / "ISSUE_TEMPLATE" / "model-found.yml"


def issue_body(**answers) -> str:
    """An issue body as GitHub renders the "Add a landmark" form."""
    labels = {
        "url": "Link to the model",
        "file": "Model file (only if the site needs a login to download)",
        "author": "Author (name, and profile link if there is one)",
        "license": "Licence",
        "saga": "Saga (the theme it belongs to)",
        "new_saga": 'New saga (only if you picked "other")',
        "title": "Name of the landmark",
        "size": "How big in the game?",
        "hints": "Where should it appear?",
        "kind": "What is it?",
    }
    return "\n\n".join(f"### {labels[k]}\n\n{v or '_No response_'}" for k, v in answers.items())


def test_form_labels_are_parsed():
    labels = re.findall(r"^\s+label: (.+)$", FORM.read_text(), re.M)
    form_fields = [lab.strip().strip('"') for lab in labels]
    for lab in form_fields:
        assert any(lab.startswith(k) for k in intake.FIELDS), lab
    body = issue_body(url="https://x.org/a.glb", license="CC0", saga="ruins", size="like a house (about 20)")
    form = intake.parse_form(body)
    assert form["url"] == "https://x.org/a.glb" and form["license"] == "CC0" and form["saga"] == "ruins"
    assert intake.size_of(form["size"]) == 20 and intake.size_of("") == intake.DEFAULT_SIZE


def test_hints_from_words():
    p = hints.suggest("On sea cliffs in the cold north, rare, watching over the bay")
    assert p.site[0] == "cliff+coast" and p.exposure == "prominent" and p.rarity == 600
    assert p.biomes == ["tundra", "snow", "taiga"]
    p = hints.suggest("hidden deep in the forest")
    assert p.exposure == "hidden" and "forest" in p.biomes
    p = hints.suggest("in a cave, the halls of the dwarves")
    assert p.site == ["cave_floor"] and p.y_max == -20
    assert hints.suggest("a nice, important season").site == ["plain"]  # no "ice", "port", "sea"


def landmark(repo, extra=""):
    d = repo.content / "test" / "cube"
    d.mkdir(parents=True)
    write_cube_obj(d)
    (d / "landmark.toml").write_text(
        'id = "cube"\nsaga = "test"\ntitle = "Cube"\n\n[source]\nkind = "mesh"\nfile = "cube.obj"\n'
        'url = "https://example.org/cube"\nauthor = "Tester"\nlicense = "CC0-1.0"\n\n'
        "[transform]\ntarget_size = 8  # longest side\n" + extra
    )
    return d / "landmark.toml"


def test_set_values_keeps_comments_and_validates(repo):
    path = landmark(repo)
    lm = edit.set_values(path, {"transform.target_size": 12, "placement.site": ["cliff+coast"]})
    assert lm.transform.target_size == 12 and lm.placement.site == ["cliff+coast"]
    assert "# longest side" in path.read_text()
    before = path.read_text()
    with pytest.raises(ConfigError):
        edit.set_values(path, {"transform.target_size": 1})
    assert path.read_text() == before


def test_comment_commands(repo):
    lm = config.load(landmark(repo))
    assert edit.command(lm, "/size 24")[0]["transform.target_size"] == 24
    assert edit.command(lm, "/bigger")[0]["transform.target_size"] == 10
    assert edit.command(lm, "/site cliff+coast plain")[0] == {"placement.site": ["cliff+coast", "plain"]}
    assert edit.command(lm, "/rarity rare")[0] == {"placement.rarity": "rare"}
    assert edit.command(lm, "/door none")[0] == {"voxel.doorway": "none"}
    for bad in ("/site moon", "/rarity often", "/size big", "/fly", "/door up"):
        with pytest.raises(SagasError):
            edit.command(lm, bad)
    assert edit.door_opening(["+x [1, 1, 2, 1, 2, 3]", "-z [0, 1, 0, 1, 2, 0]"], "-z") == [0, 1, 0, 1, 2, 0]


def test_command_cli_rebuilds(repo):
    landmark(repo)
    r = runner.invoke(app, ["--root", str(repo.root), "command", "test/cube", "/size 12", "/rarity rare"])
    assert r.exit_code == 0, r.output
    lm = config.load(repo.content / "test" / "cube" / "landmark.toml")
    assert lm.transform.target_size == 12 and lm.placement.rarity == 400
    assert lm.vx_path.exists() and lm.preview_path.exists() and "now 13x13x13" in r.output


def test_intake_from_an_attached_zip(repo, tmp_path):
    src = tmp_path / "model"
    src.mkdir()
    write_cube_obj(src)
    archive = tmp_path / "tower.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for f in src.iterdir():
            z.write(f, f"source/{f.name}")
    body = issue_body(
        url="https://sketchfab.com/3d-models/tower-123",
        file=f"[tower.zip](https://github.com/user-attachments/files/42/{archive.name})",
        author="Jane",
        license="CC-BY 4.0",
        saga="other (name it below)",
        new_saga="Vikings: longhouses and ships",
        title="",
        size="small, like a hut (about 12 nodes long)",
        hints="on sea cliffs in the cold north, rare",
        kind="modelled",
    )
    got = []
    s = intake.run(
        repo, 7, "Model: Old Tower", body, "jane", get=lambda url, dest: (got.append(url), shutil.copy(archive, dest))
    )
    assert got == [f"https://github.com/user-attachments/files/42/{archive.name}"]
    assert (s.saga, s.id, s.new_saga) == ("vikings", "old_tower", True)
    lm = config.load(repo.content / "vikings" / "old_tower" / "landmark.toml")
    assert lm.source.manual and lm.source.member == "source/cube.obj" and lm.source.license == "CC-BY-4.0"
    assert lm.source.mirror == got[0] and (lm.dir / "tower.zip").is_file()  # the original stays in the repo
    assert "content/vikings/old_tower/tower.zip" in s.files and "content/vikings/saga.toml" in s.files
    assert lm.transform.target_size == 12 and lm.placement.site[0] == "cliff+coast"
    assert "issue #7 by @jane" in lm.source.notes and lm.vx_path.exists() and lm.preview_path.exists()
    assert (repo.content / "vikings" / "saga.toml").exists()


def test_intake_refusals(repo):
    (repo.content / "ruins").mkdir()
    with pytest.raises(intake.IntakeError, match="licence"):
        intake.run(repo, 1, "Model: x", issue_body(url="https://a.org/x.glb", license="not sure", saga="ruins"))
    with pytest.raises(intake.IntakeError, match="drag the zip"):
        intake.run(repo, 2, "Model: x", issue_body(url="https://sketchfab.com/x", license="CC0", saga="ruins"))
    with pytest.raises(intake.IntakeError, match="no saga 'castles'"):
        intake.run(repo, 3, "Model: x", issue_body(url="https://a.org/x.glb", license="CC0", saga="castles"))


def test_intake_cli_writes_a_summary(repo, tmp_path, monkeypatch):
    issue = tmp_path / "issue.json"
    issue.write_text(json.dumps({"number": 3, "title": "Model: x", "body": "", "author": {"login": "a"}}))
    r = runner.invoke(app, ["--root", str(repo.root), "intake", str(issue)])
    assert r.exit_code != 0 and "link to the model is missing" in r.output


def test_voxelize_stale(repo):
    landmark(repo)
    root = ["--root", str(repo.root)]
    assert "re-voxelized" in runner.invoke(app, [*root, "voxelize", "test/cube", "--stale"]).output
    assert "re-voxelized" not in runner.invoke(app, [*root, "voxelize", "test/cube", "--stale"]).output
    runner.invoke(app, [*root, "set", "test/cube", "transform.target_size=10"])
    assert "re-voxelized, 11x11x11" in runner.invoke(app, [*root, "voxelize", "test/cube", "--stale"]).output
