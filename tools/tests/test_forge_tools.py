"""What Saga Forge drives: `sagas add`, `sagas --json`, edited models next to their originals, and the
viewer's original-model comparison."""

import json
import threading
import urllib.request

import pytest
from typer.testing import CliRunner

from conftest import write_cube_obj
from sagas import config, intake, lint, pipeline, registry, viewer
from sagas.cli import FORGE_API, app
from sagas.errors import ConfigError

runner = CliRunner()


@pytest.fixture
def no_games(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGAS_GAMES", str(tmp_path / "no-games"))
    monkeypatch.setattr(viewer, "game_roots", lambda extra=None: [])


def write_box_obj(path, x=8.0, y=2.0, z=2.0):
    """One closed box [0, x] x [0, y] x [0, z]: a flat 'edited' model next to the cube original."""
    v = [(a, b, c) for a in (0, x) for b in (0, y) for c in (0, z)]
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    lines = [f"v {a} {b} {c}" for a, b, c in v]
    for a, b, c, d in quads:
        lines += [f"f {a + 1} {b + 1} {c + 1}", f"f {a + 1} {c + 1} {d + 1}"]
    path.write_text("\n".join(lines) + "\n")
    return path


def edited_landmark(repo, edited="flat.obj"):
    d = repo.content / "test" / "cube"
    d.mkdir(parents=True)
    write_cube_obj(d)
    write_box_obj(d / "flat.obj")
    (d / "landmark.toml").write_text(
        'id = "cube"\nsaga = "test"\ntitle = "Cube"\n\n[source]\nkind = "mesh"\nfile = "cube.obj"\n'
        f'edited = "{edited}"\nmanual = true\nauthor = "Tester"\nlicense = "CC-BY-4.0"\n\n'
        "[transform]\ntarget_size = 8\n"
    )
    return config.load(d / "landmark.toml")


def run(repo, *args):
    return runner.invoke(app, ["--root", str(repo.root), *args])


def test_edited_model_is_voxelized_and_the_original_kept(repo):
    lm = edited_landmark(repo)
    x, y, z = pipeline.voxelize(lm, repo).size
    assert max(x, z) >= 3 * y  # the flat edited box
    ox, oy, oz = pipeline.voxelize(lm, repo, original=True).size
    assert ox == oy == oz  # the cube it was made from
    assert pipeline.voxelize(lm, repo).source_sha256 != ""
    assert not [f for f in lint.check_saga(lm) if f.code in ("L017", "L018")]
    (lm.dir / "cube.obj").unlink()
    assert [f.code for f in lint.check_saga(lm) if f.code in ("L017", "L018")] == ["L017", "L018"]


def test_edited_names_a_plain_file(repo):
    with pytest.raises(ConfigError, match="plain file name"):
        edited_landmark(repo, edited="../flat.obj")


def test_attribution_says_modified(repo):
    from sagas import build

    lm = edited_landmark(repo)
    res = build.build(lm, pipeline.voxelize(lm, repo))
    text = registry.attribution_md(repo.saga("test"), [res])
    assert "`cube.mts`: the source model was modified" in text


def test_add_keeps_a_dropped_model_as_the_original(repo, tmp_path):
    (repo.content / "ruins").mkdir()
    src = tmp_path / "drop"
    src.mkdir()
    model = write_cube_obj(src)
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "title": "Old Tower",
                "url": "https://sketchfab.com/3d-models/old-tower-1",
                "file": str(model),
                "license": "CC-BY-4.0",
                "author": "Jane",
                "saga": "ruins",
                "size": 12,
                "hints": "on sea cliffs, rare",
                "lore": "Nobody remembers who lit its fire.",
            }
        )
    )
    r = run(repo, "--json", "add", str(request))
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["path"] == "content/ruins/old_tower" and out["dims"] == [13, 13, 13]
    assert "content/ruins/old_tower/cube.obj" in out["files"] and "content/ruins/old_tower/preview.png" in out["files"]
    lm = config.load(repo.content / "ruins" / "old_tower" / "landmark.toml")
    assert lm.source.manual and lm.source.file == "cube.obj" and lm.source.url.startswith("https://sketchfab")
    assert lm.placement.site[0] == "cliff+coast" and lm.lore.startswith("Nobody")
    assert not [f for f in lint.check_saga(lm) if f.code == "L017"]
    again = run(repo, "--json", "add", str(request))
    assert again.exit_code == 1 and "exists already" in json.loads(again.output)["error"]


def test_add_refusals(repo, tmp_path):
    request = tmp_path / "r.json"
    request.write_text(json.dumps({"title": "X", "colour": "red"}))
    assert "unknown field(s) colour" in run(repo, "add", str(request)).output
    with pytest.raises(intake.IntakeError, match="link to the model"):
        intake.create_landmark(repo, intake.Request(title="X", license="CC0-1.0", saga="ruins"))
    with pytest.raises(intake.IntakeError, match="licence"):
        intake.create_landmark(repo, intake.Request(title="X", url="https://a.org/x.glb", license="GPL"))
    assert intake.original_name("preview.png") == "original-preview.png"
    assert intake.original_name("https://x/y/scene.zip?dl=1") == "scene.zip"


def test_json_output(repo):
    edited_landmark(repo)
    v = json.loads(run(repo, "--json", "version").output)
    assert v["forge_api"] == FORGE_API
    h = json.loads(run(repo, "--json", "hints", "in a cave, rare").output)
    assert h["fields"]["site"] == ["cave_floor"] and h["matched"]
    s = json.loads(run(repo, "--json", "set", "test/cube", "transform.target_size=10").output)
    assert s["values"] == {"transform.target_size": 10}
    vx = json.loads(run(repo, "--json", "voxelize", "test/cube", "--force").output)
    assert vx["results"][0]["status"] == "written"
    b = json.loads(run(repo, "--json", "build", "test/cube").output)
    assert b["results"][0]["landmark"] == "test/cube" and "mods/sagas_test/registry.lua" in b["written"]
    c = json.loads(run(repo, "--json", "catalog").output)
    assert [x["selector"] for x in c["landmarks"]] == ["test/cube"]
    assert c["landmarks"][0]["preview"] == "content/test/cube/preview.png"
    assert not (repo.root / "docs" / "gallery").exists()  # read only
    cmd = json.loads(run(repo, "--json", "command", "test/cube", "/size 12").output)
    assert cmd["size"][0] >= 12 and cmd["done"]
    err = run(repo, "--json", "set", "test/cube", "transform.target_size=1")
    assert err.exit_code == 2 and "target_size" in json.loads(err.output)["error"]


def test_viewer_compares_with_the_original(repo, no_games):
    lm = edited_landmark(repo)
    builder = viewer.SizeBuilder(lm, repo, [8])
    assert builder.original is not None
    original = viewer.original_data(builder)
    dims = original["sizes"][0]["vox"]["dims"]
    assert dims[0] == dims[1] == dims[2] and original["mesh"]
    html = viewer.page(viewer.page_data(lm, [builder.build(8)], [], [], builder.src, live=True, original=original))
    httpd = viewer.server(builder, html, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}/"
    try:
        flat = json.loads(urllib.request.urlopen(base + "size?target=10").read())["vox"]["dims"]
        cube = json.loads(urllib.request.urlopen(base + "size?target=10&original=1").read())["vox"]["dims"]
        assert flat[1] < flat[0] and cube[0] == cube[1]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_view_json_reports_the_page(repo, no_games, tmp_path):
    edited_landmark(repo)
    r = run(repo, "--json", "view", "test/cube", "--sizes", "8", "--out", str(tmp_path / "v.html"), "--no-open")
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["original"] is True and out["page"] == str(tmp_path / "v.html") and 8 in out["sizes"]
