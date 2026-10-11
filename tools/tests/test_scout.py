import json

import pytest

from sagas import config
from sagas.errors import SagasError
from sagas.scout import base, promote, report, sources


class FakeHttp:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get_json(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        for key, value in self.responses.items():
            if key in url:
                return value
        raise AssertionError(f"unexpected request {url}")


def test_spdx_and_flags():
    assert base.spdx("CC0 Public Domain") == "CC0-1.0"
    assert base.spdx("CC Attribution-ShareAlike") == "CC-BY-SA-4.0"
    assert base.spdx("CC Attribution-NonCommercial") is None
    c = base.Candidate("x", "1", "Smaug", "u")
    base.check_text(c, "Free for non-commercial use", "Dragon Smaug")
    assert c.flags == ["licence-conflict", "trademark"]


SKETCHFAB = {
    "results": [
        {
            "uid": "abc",
            "name": "Renvyle Castle",
            "viewerUrl": "https://sketchfab.com/3d-models/none-abc",
            "user": {"displayName": "galway3d", "profileUrl": "https://sketchfab.com/galway3d"},
            "license": {"label": "CC0 Public Domain"},
            "faceCount": 1000,
            "archives": {"gltf": {"size": 5_000_000}},
            "thumbnails": {"images": [{"url": "t.jpg", "width": 50}]},
            "description": "Castle scan",
        }
    ]
}


def test_token_from_secrets_file(monkeypatch, tmp_path):
    from sagas import secrets

    f = tmp_path / "secrets.env"
    f.write_text("SKETCHFAB_TOKEN=fromfile\nX=$(rm -rf /)\n")
    monkeypatch.setenv("AVANTI_SECRETS", str(f))
    monkeypatch.delenv("SKETCHFAB_TOKEN", raising=False)
    assert secrets.get("SKETCHFAB_TOKEN") == "fromfile"
    monkeypatch.setenv("SKETCHFAB_TOKEN", "env")
    assert secrets.get("SKETCHFAB_TOKEN") == "env"


def test_sketchfab_adapter_uses_token(monkeypatch):
    monkeypatch.setenv("SKETCHFAB_TOKEN", "tok")
    http = FakeHttp({"api.sketchfab.com": SKETCHFAB})
    found = list(sources.sketchfab(http, "medieval", "castle", 5, ["cc0"]))
    assert [c.id for c in found] == ["sketchfab:abc"]
    assert found[0].license == "CC0-1.0" and found[0].download["manual"]
    assert http.calls[0][2] == {"Authorization": "Token tok"}


def test_commons_adapter_drops_unfree():
    http = FakeHttp(
        {
            "list=search": None,
            "commons.wikimedia.org": {
                "query": {
                    "search": [{"title": "File:A.stl"}, {"title": "File:B.stl"}],
                    "pages": {
                        "1": {
                            "title": "File:A.stl",
                            "imageinfo": [
                                {
                                    "url": "https://up/A.stl",
                                    "descriptionurl": "https://c/A",
                                    "size": 10,
                                    "extmetadata": {
                                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                        "Artist": {"value": "<a>Ann</a>"},
                                    },
                                }
                            ],
                        },
                        "2": {
                            "title": "File:B.stl",
                            "imageinfo": [{"url": "u", "extmetadata": {"LicenseShortName": {"value": "CC BY-NC 4.0"}}}],
                        },
                    },
                }
            },
        }
    )
    http.responses.pop("list=search")
    found = list(sources.commons(http, "medieval", "castle", 5, ["cc0", "by", "by-sa"]))
    assert [(c.title, c.license, c.author) for c in found] == [("A", "CC-BY-SA-4.0", "Ann")]


def test_merge_refresh_and_reject(repo):
    a = base.Candidate("polyhaven", "a", "A", "https://p/a", license="CC0-1.0", saga="medieval")
    b = base.Candidate("polyhaven", "b", "B", "https://p/b", license="CC0-1.0", saga="medieval")
    merged = report.merge(repo, [a, b], today="2026-01-01")
    report.write(repo, merged)
    again = report.merge(repo, [a], today="2026-02-01", searched={("polyhaven", "medieval")})
    assert list(again) == ["polyhaven:a"] and again["polyhaven:a"].first_seen == "2026-01-01"
    report.reject(repo, "polyhaven:a", "toy-like")
    assert "polyhaven:a" not in report.merge(repo, [a])
    data = json.loads((repo.root / "docs" / "scouting" / "rejected.json").read_text())
    assert data == {"polyhaven:a": "toy-like"}


def test_promote_polyhaven(repo):
    c = base.Candidate(
        "polyhaven",
        "rock_01",
        "Rock 01",
        "https://polyhaven.com/a/rock_01",
        author="Rob",
        license="CC0-1.0",
        saga="dwarven",
        download={"polyhaven": "rock_01"},
        suggested_site=["carve"],
        suggested_biomes=["any"],
    )
    files = {
        "gltf": {
            "1k": {
                "gltf": {
                    "url": "https://dl/rock_01_1k.gltf",
                    "include": {
                        "rock_01.bin": {"url": "https://dl/rock_01.bin"},
                        "textures/rock_01_diff_1k.jpg": {"url": "https://dl/rock_01_diff_1k.jpg"},
                    },
                }
            }
        }
    }
    path = promote.promote(repo, c, sid="rock_one", http=FakeHttp({"api.polyhaven.com/files/rock_01": files}))
    landmark = config.load(path)
    assert landmark.source.file == "rock_01_1k.gltf" and landmark.source.license == "CC0-1.0"
    assert [e["file"] for e in landmark.source.extra_files] == ["rock_01.bin", "textures/rock_01_diff_1k.jpg"]
    assert landmark.placement.site == ["carve"]


def test_promote_refuses_flagged(repo):
    c = base.Candidate(
        "sketchfab",
        "x",
        "Thing",
        "u",
        license="CC-BY-4.0",
        flags=["licence-conflict"],
        download={"manual": True, "file": "t.zip", "member": "scene.gltf"},
    )
    with pytest.raises(SagasError, match="NC/ND"):
        promote.promote(repo, c, saga="misc", http=FakeHttp({}))
    path = promote.promote(repo, c, saga="misc", sid="thing", force=True, http=FakeHttp({}))
    assert config.load(path).source.manual
