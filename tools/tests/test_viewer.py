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
    assert runner.invoke(app, ["--root", str(repo.root), "view", "test/nothing", "--no-open"]).exit_code != 0


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
