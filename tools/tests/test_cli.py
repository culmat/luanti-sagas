from typer.testing import CliRunner

from conftest import box_txt
from sagas.cli import app

runner = CliRunner()


def run(repo, *args):
    return runner.invoke(app, ["--root", str(repo.root), *args])


def test_convert_build_check_lint(repo, tmp_path):
    txt = box_txt(tmp_path / "hut.txt", color=(120, 90, 60))
    r = run(
        repo,
        "convert-txt",
        str(txt),
        "--saga",
        "village",
        "--license",
        "CC0-1.0",
        "--author",
        "Me",
        "--url",
        "https://example.org/hut",
    )
    assert r.exit_code == 0, r.output
    assert (repo.content / "village" / "hut" / "voxels.vx.gz").exists()
    r = run(repo, "build", "village")
    assert r.exit_code == 0, r.output
    assert (repo.mods / "sagas_village" / "schematics" / "hut.mts").exists()
    assert (repo.content / "village" / "hut" / "preview.png").exists()
    assert run(repo, "build", "--check").exit_code == 0
    (repo.mods / "sagas_village" / "schematics" / "hut.mts").write_bytes(b"x")
    assert run(repo, "build", "--check").exit_code == 5
    run(repo, "build")
    r = run(repo, "lint")
    assert r.exit_code == 0, r.output


def test_new_and_lint_failure(repo):
    r = run(repo, "new", "tower", "--saga", "medieval", "--license", "CC-BY-NC-4.0")
    assert r.exit_code == 0, r.output
    r = run(repo, "lint", "medieval")
    assert r.exit_code == 3 and "L002" in r.output


def test_unknown_selector(repo):
    r = run(repo, "build", "nothing")
    assert r.exit_code == 1 and "no saga or landmark" in r.output
