"""Turn a scouting candidate into content/<saga>/<id>/landmark.toml."""

from __future__ import annotations

import re
from pathlib import Path

from ..errors import SagasError
from ..repo import Repo
from .base import Candidate, Http
from .sources import ZEROAD_SHA, slug


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {_toml_value(x)}" for k, x in v.items()) + " }"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{s}"'


def _table(name: str, items: dict) -> str:
    return f"[{name}]\n" + "".join(f"{k} = {_toml_value(v)}\n" for k, v in items.items())


def _polyhaven(http: Http, slug_: str, source: dict) -> None:
    files = http.get_json(f"https://api.polyhaven.com/files/{slug_}")
    gl = files["gltf"]["1k"]["gltf"]
    source["url"] = gl["url"]
    source["file"] = Path(gl["url"]).name
    source["extra_files"] = [
        {"url": inc["url"], "file": rel, "sha256": ""} for rel, inc in sorted(gl["include"].items())
    ]


def _voyager(http: Http, package: str, source: dict, transform: dict) -> None:
    doc = f"https://3d-api.si.edu/content/document/{package}/"
    svx = http.get_json(doc + "scene.svx.json")
    best = None
    for model in svx.get("models", []):
        for der in model.get("derivatives", []):
            if der.get("usage") != "Web3D":
                continue
            rank = {"Medium": 0, "Low": 1, "High": 2}.get(der.get("quality", ""), 9)
            for a in der.get("assets", []):
                if a.get("uri", "").endswith(".glb") and (best is None or rank < best[0]):
                    best = (rank, a["uri"])
    if not best:
        raise SagasError(f"{package}: no Web3D GLB in the Voyager package")
    source["url"] = doc + best[1]
    source["file"] = best[1]
    transform["up"] = "auto"  # Voyager GLBs are often Z-up: check the preview and set up = "z" if lying down


def _zeroad(http: Http, actor: str, source: dict, voxel: dict) -> None:
    import httpx

    raw = f"https://raw.githubusercontent.com/0ad/0ad/{ZEROAD_SHA}/binaries/data/mods/public/"
    xml = httpx.get(raw + actor, timeout=30, headers={"User-Agent": "luanti-sagas-scout"}).text
    mesh = re.search(r"<mesh>([^<]+)</mesh>", xml)
    tex = re.search(r'file="([^"]+)"\s+name="baseTex"', xml)
    if not mesh:
        raise SagasError(f"{actor}: no <mesh> in the actor")
    source["url"] = raw + "art/meshes/" + mesh.group(1)
    source["file"] = Path(mesh.group(1)).name
    if tex:
        tfile = Path(tex.group(1)).name
        source["extra_files"] = [{"url": raw + "art/textures/skins/" + tex.group(1), "file": tfile, "sha256": ""}]
        voxel["texture"] = tfile
    voxel["alpha"] = "ignore"


def promote(
    repo: Repo,
    c: Candidate,
    saga: str | None = None,
    sid: str | None = None,
    force: bool = False,
    http: Http | None = None,
    overrides: dict[str, dict] | None = None,
) -> Path:
    """Write content/<saga>/<id>/landmark.toml. `overrides` replaces fields per section (`top` for
    title, lore and tags; `source`, `transform`, `voxel`, `placement`)."""
    if c.license not in ("CC0-1.0", "CC-BY-3.0", "CC-BY-4.0", "CC-BY-SA-3.0", "CC-BY-SA-4.0", "MIT"):
        raise SagasError(f"{c.id}: licence {c.license!r} is not allowed")
    if "licence-conflict" in c.flags and not force:
        raise SagasError(f"{c.id}: the description mentions NC/ND terms; check the page, then use --force")
    if "trademark" in c.flags and not force:
        raise SagasError(f"{c.id}: possibly a protected character or brand; check, then use --force")
    saga = saga or c.saga or "misc"
    sid = sid or slug(c.title)
    if not re.match(r"^[a-z][a-z0-9_]{2,31}$", sid):
        sid = ("landmark_" + sid)[:32]
    d = repo.content / saga / sid
    if (d / "landmark.toml").exists():
        raise SagasError(f"{d / 'landmark.toml'} already exists")
    http = http or Http()
    source: dict = {
        "kind": "mesh",
        "url": c.url,
        "manual": False,
        "instructions": "",
        "file": "",
        "member": "",
        "sha256": "",
        "author": c.author,
        "author_url": c.author_url,
        "license": c.license,
        "license_url": "",
        "ai": "none",
        "notes": f"Found by sagas scout ({c.source}). {c.notes}".strip(),
    }
    transform: dict = {"up": "auto", "rotate_y": 0, "target_size": 48, "anchor": "bottom-center"}
    voxel: dict = {"mode": "shell"}
    dl = c.download
    if dl.get("manual"):
        source.update(
            {
                "manual": True,
                "instructions": dl.get("instructions", ""),
                "file": dl.get("file", ""),
                "member": dl.get("member", ""),
            }
        )
        if dl.get("mirror"):
            source["mirror"] = dl["mirror"]
    elif "polyhaven" in dl:
        _polyhaven(http, dl["polyhaven"], source)
    elif "voyager" in dl:
        _voyager(http, dl["voyager"], source, transform)
    elif "zeroad_actor" in dl:
        _zeroad(http, dl["zeroad_actor"], source, voxel)
    else:
        source["url"] = dl.get("url", c.url)
        source["file"] = dl.get("file", "")
        if c.url and c.url != source["url"]:
            source["author_url"] = source["author_url"] or c.url
    placement: dict = {
        "site": c.suggested_site or ["plain"],
        "exposure": "any",
        "biomes": c.suggested_biomes or ["any"],
        "rarity": 600,
        "hints": "",
    }
    top: dict = {"title": c.title, "tags": [], "lore": ""}
    for name, section in (("top", top), ("source", source), ("transform", transform), ("voxel", voxel)):
        section.update((overrides or {}).get(name, {}))
    placement.update((overrides or {}).get("placement", {}))
    extra = source.pop("extra_files", None)
    text = (
        f'schema = 1\nid = "{sid}"\nsaga = "{saga}"\n'
        + "".join(f"{k} = {_toml_value(v)}\n" for k, v in top.items())
        + "\n"
        + _table("source", source)
        + (f"extra_files = {_toml_value(extra)}\n" if extra else "")
        + "\n"
        + _table("transform", transform)
        + "\n"
        + _table("voxel", voxel)
        + "\n"
        + _table("materials", {"mode": "classes", "default": "stone", "context": "surroundings"})
        + "\n"
        + _table("placement", placement)
    )
    d.mkdir(parents=True, exist_ok=True)
    (d / "landmark.toml").write_text(text)
    return d / "landmark.toml"
