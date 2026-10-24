import json
import re
import shutil
import subprocess

import numpy as np
import pytest
from typer.testing import CliRunner

from conftest import box_txt, landmark_toml, write_cube_obj
from sagas import build, config, legacy, schematic, viewer
from sagas.cli import app
from sagas.errors import ConfigError

runner = CliRunner()


@pytest.fixture
def no_games(tmp_path, monkeypatch):
    """No installed games: the user folders are searched under HOME."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("SAGAS_GAMES", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    return home


def tree_mts(height=6, marker=False) -> bytes:
    """A trunk with a leaf cap; leaves at probability 0 never appear; an optional village marker."""
    names = ["air", "default:tree", "default:leaves", "mcl_villages:no_paths"]
    size = (3, height, 3)
    content = np.zeros(size, np.uint16)
    param1 = np.zeros(size, np.uint8)
    content[1, : height - 1, 1] = 1
    param1[1, : height - 1, 1] = schematic.PROB_ALWAYS
    content[:, height - 1, :] = 2
    param1[:, height - 1, :] = schematic.PROB_ALWAYS
    param1[0, height - 1, 0] = schematic.PROB_NEVER
    if marker:
        content[0, 0, 0] = 3
        param1[0, 0, 0] = schematic.PROB_ALWAYS
    grid = schematic.Grid(names, content, param1, np.zeros(size, np.uint8), np.full(height, 127, np.uint8))
    return schematic.to_mts(grid)


def game(root, folder, title, files):
    d = root / folder
    (d / "mods" / "default" / "schematics").mkdir(parents=True)
    (d / "game.conf").write_text(f"title = {title}\n")
    for name, data in files.items():
        (d / "mods" / "default" / "schematics" / name).write_bytes(data)
    return root


def test_rle_round_trip():
    cells = np.zeros((70, 30, 40), np.uint16)  # 84000 empty cells: one run is split
    cells[3:9, 0:5, 7] = 2
    cells[60, 29, 39] = 300
    assert np.array_equal(viewer.unrle(viewer.rle(cells), cells.shape), cells)


def test_ladder():
    assert viewer.ladder(48) == [12, 16, 24, 32, 48, 64]
    assert viewer.ladder(52) == [12, 16, 24, 32, 48, 52, 64]
    assert viewer.ladder(96) == [12, 16, 24, 32, 48, 64, 96]


def test_schematic_reference_is_cropped_and_rolled():
    v = viewer.from_schematic(tree_mts(marker=True), "t")
    assert v.dims == (3, 6, 3)
    labels = [m[0] for m in v.mats]
    assert "no_paths" not in labels and {"tree", "leaves"} <= set(labels)
    leaves = labels.index("leaves")
    assert v.cells[0, 5, 0] == 0 and v.cells[2, 5, 2] == leaves  # probability 0 never shows
    assert v.mats[labels.index("tree")][1] != v.mats[leaves][1]
    assert np.array_equal(viewer.from_schematic(tree_mts(), "t").cells, v.cells)


def test_references_from_installed_games(tmp_path, no_games):
    roots = game(tmp_path / "games", "minetest_game", "Minetest Game",
                 {"apple_tree.mts": tree_mts(6), "pine_tree.mts": tree_mts(12)})  # fmt: skip
    refs = viewer.references([roots])
    by_key = {r.key: r for r in refs}
    assert refs[0].key == "player" and refs[0].on and refs[0].height == 1.75
    assert by_key["mtg_apple"].group == "Minetest Game" and by_key["mtg_apple"].height == 6
    assert by_key["mtg_apple"].on and by_key["mtg_pine"].on
    assert not any(r.group == "generic" for r in refs)


def test_stand_in_trees_without_games(no_games):
    refs = viewer.references([])
    assert [r.key for r in refs if r.on] == ["player", "generic_small", "generic_pine"]
    assert [r.height for r in refs[1:]] == [8, 16, 37]


def write_boxes_obj(path, boxes):
    """Closed boxes [(x0, y0, z0, x1, y1, z1)] as one OBJ."""
    lines, n = [], 0
    for x0, y0, z0, x1, y1, z1 in boxes:
        lines += [f"v {x} {y} {z}" for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
        quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        for a, b, c, d in quads:
            lines += [f"f {n + a + 1} {n + b + 1} {n + c + 1}", f"f {n + a + 1} {n + c + 1} {n + d + 1}"]
        n += 8
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.mark.parametrize("rotate_y", [0, 90, 180, 270])
@pytest.mark.parametrize("mirror", ["", "x", "z"])
def test_source_model_sits_on_its_nodes(tmp_path, rotate_y, mirror):
    """A small box beside a big one: placed by mesh_affine, it must land among the small box's nodes."""
    from scipy import ndimage

    from sagas import load
    from sagas import voxelize as vz

    mesh = load.load_model(write_boxes_obj(tmp_path / "boxes.obj", [(0, 0, 0, 4, 2, 3), (5, 0, 2, 6, 1, 3)]))
    t = config.Transform(target_size=12, rotate_y=rotate_y, mirror=mirror)
    v = config.Voxel(min_component=1)
    occ = vz.voxelize(mesh, t, v).occ
    labels, n = ndimage.label(occ)
    assert n == 2
    small = np.argmin(np.bincount(labels.ravel())[1:]) + 1
    src = viewer.source_mesh(mesh, t, v, 256)
    aff = viewer.mesh_affine(src, t, src.big / 12)
    unit = (np.array([5.5, 0.5, 2.5]) - 0.0) / src.big  # the small box's centre; the model starts at 0
    grid = np.array(aff["A"]).reshape(3, 3) @ (unit * aff["s"]) + np.array(aff["b"])
    cells = np.argwhere(labels == small)  # a hollow shell: compare with its box
    assert (cells.min(axis=0) <= grid).all() and (grid <= cells.max(axis=0) + 1).all()


def test_build_shows_carved_air(repo, tmp_path):
    landmark = config.load(landmark_toml(repo, "test", "box"))
    model = legacy.read_txt(box_txt(tmp_path / "box.txt", size=(7, 5, 7)))
    model.occ[:, 4, :] = True  # a roof: the inside is a room
    v = viewer.from_build(build.build(landmark, model))
    assert v.carved and (v.cells == v.carved).any()
    assert dict(v.mats)["carved air"] == viewer.CARVED_RGB


def test_real_size(repo):
    lm = config.load(landmark_toml(repo, "test", "big", "[transform]\nreal_size = 5\n"))
    assert lm.transform.real_size == 5.0
    with pytest.raises(ConfigError, match="real_size"):
        config.load(landmark_toml(repo, "test", "bad", "[transform]\nreal_size = -1\n"))


def page_data(html: str) -> dict:
    m = re.search(r"const DATA = (\{.*?\});\n", html, re.S)
    assert m, "no data in the page"
    return json.loads(m.group(1))


def test_view_command(repo, tmp_path, no_games):
    d = repo.content / "test" / "cube"
    d.mkdir(parents=True)
    write_cube_obj(d)
    (d / "landmark.toml").write_text(
        'id = "cube"\nsaga = "test"\ntitle = "Cube"\n[source]\nkind = "mesh"\nfile = "cube.obj"\n'
        'url = "https://example.org/cube"\nauthor = "Tester"\nlicense = "CC0-1.0"\n'
        "[transform]\ntarget_size = 8\nreal_size = 4.0\n"
    )
    out, png = tmp_path / "view.html", tmp_path / "view.png"
    args = ["--root", str(repo.root), "view", "test/cube", "--sizes", "6,12", "--no-open", "--out", str(out)]
    r = runner.invoke(app, [*args, "--png", str(png)])
    assert r.exit_code == 0, r.output
    assert "stand-in trees" in r.output and png.exists()
    html = out.read_text()
    assert viewer.PLACEHOLDER not in html and "</script>" in html
    data = page_data(html)
    assert [s["target"] for s in data["sizes"]] == [6, 8, 12]
    assert data["current"] == 8 and [s["current"] for s in data["sizes"]] == [False, True, False]
    assert all(s["life"] > 1 for s in data["sizes"]) and data["real_size"] == 4.0
    assert data["refs"][0]["key"] == "player"
    assert data["mesh"]["triangles"] == 12 and all(s["mesh"]["s"] > 0 for s in data["sizes"])
    assert runner.invoke(app, ["--root", str(repo.root), "view", "test/nothing", "--no-open"]).exit_code != 0

    # committed voxels that no longer match landmark.toml are flagged
    assert runner.invoke(app, ["--root", str(repo.root), "voxelize", "test/cube"]).exit_code == 0
    assert runner.invoke(app, args).exit_code == 0
    assert not page_data(out.read_text())["notes"]
    toml = d / "landmark.toml"
    toml.write_text(toml.read_text().replace("target_size = 8", "target_size = 10"))
    assert runner.invoke(app, args).exit_code == 0
    assert any("voxels.vx.gz differs" in n for n in page_data(out.read_text())["notes"])


def test_fixed_size_sources_show_one_size(repo, tmp_path, no_games):
    txt = box_txt(tmp_path / "hut.txt")
    r = runner.invoke(app, ["--root", str(repo.root), "convert-txt", str(txt), "--saga", "village",
                            "--license", "CC0-1.0", "--author", "Me", "--url", "https://example.org/hut"])  # fmt: skip
    assert r.exit_code == 0, r.output
    out = tmp_path / "hut.html"
    r = runner.invoke(app, ["--root", str(repo.root), "view", "village/hut", "--sizes", "16", "--no-open",
                            "--out", str(out)])  # fmt: skip
    assert r.exit_code == 0, r.output
    data = page_data(out.read_text())
    assert len(data["sizes"]) == 1 and data["sizes"][0]["current"]
    assert any("fixed size" in n for n in data["notes"])


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_page_script_parses(tmp_path):
    html = viewer.template()
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert scripts
    js = tmp_path / "page.js"
    js.write_text("\n".join(scripts))
    r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_live_server_builds_any_size(repo, no_games):
    import threading
    import urllib.error
    import urllib.request

    d = repo.content / "test" / "cube"
    d.mkdir(parents=True)
    write_cube_obj(d)
    (d / "landmark.toml").write_text(
        'id = "cube"\nsaga = "test"\ntitle = "Cube"\n[source]\nkind = "mesh"\nfile = "cube.obj"\n'
        'url = "https://example.org/cube"\nauthor = "Tester"\nlicense = "CC0-1.0"\n[transform]\ntarget_size = 8\n'
    )
    builder = viewer.SizeBuilder(config.load(d / "landmark.toml"), repo, [8])
    html = viewer.page(viewer.page_data(builder.landmark, [builder.build(8)], [], [], builder.src, live=True))
    httpd = viewer.server(builder, html, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}/"
    try:
        assert page_data(urllib.request.urlopen(base).read().decode())["live"] is True
        entry = json.loads(urllib.request.urlopen(base + "size?target=11").read())
        assert entry["target"] == 11 and max(entry["vox"]["dims"]) >= 11 and entry["mesh"]["s"] > 0
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + f"size?target={viewer.MAX_SIZE + 1}")
        assert e.value.code == 422
    finally:
        httpd.shutdown()
        httpd.server_close()
