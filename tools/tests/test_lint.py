from conftest import box_txt, landmark_toml
from sagas import build, config, legacy, lint, voxels


def codes(findings):
    return sorted({f.code for f in findings if f.level == "error"})


def test_clean_saga(repo, tmp_path):
    landmark = config.load(landmark_toml(repo, "test", "box"))
    model = legacy.read_txt(box_txt(tmp_path / "b.txt"))
    voxels.write(model, landmark.vx_path)
    assert codes(lint.check_saga(landmark, build.build(landmark, model))) == []
    assert lint.check_core(repo) == []


def test_nc_licence_and_missing_author(repo):
    p = landmark_toml(repo, "test", "bad")
    text = p.read_text().replace('license = "CC0-1.0"', 'license = "CC-BY-NC-4.0"')
    p.write_text(text.replace('author = "Tester"\n', ""))
    landmark = config.load(p)
    assert {"L001", "L002", "L012"} <= set(codes(lint.check_saga(landmark)))


def test_nc_hint_in_notes(repo):
    p = landmark_toml(repo, "test", "hint")
    p.write_text(p.read_text() + 'notes = "free for non-commercial use"\n')
    assert "L013" in codes(lint.check_saga(config.load(p)))


def test_too_large_without_large(repo, tmp_path):
    landmark = config.load(landmark_toml(repo, "test", "big"))
    model = legacy.read_txt(box_txt(tmp_path / "b.txt", size=(80, 3, 10)))
    assert "L004" in codes(lint.check_saga(landmark, build.build(landmark, model)))


def test_core_out_of_sync(repo):
    (repo.core_mod / "vocabulary.json").write_text("{}")
    assert [f.code for f in lint.check_core(repo)] == ["L011"]
