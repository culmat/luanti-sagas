"""A new landmark from a contributor's request: the bot's half of a browser contribution, and
`sagas add` for Saga Forge.

The issue form (.github/ISSUE_TEMPLATE/model-found.yml) asks for the link, licence, saga, size and
the creator's words; `run` reads it into a `Request`. Saga Forge writes the `Request` as JSON.
`create_landmark` turns it into content/<saga>/<id>/ (landmark.toml through the scouting `promote`,
the source fetched from the link or kept from a file, voxels and preview.png) and returns a summary.
A model that needs a login to download (a file attached to the issue or dropped into Forge) is kept
next to landmark.toml, so rework can always start from the original. GitHub work (branch, commit,
PR) is the workflow's or Forge's job (.github/workflows/intake.yml).
"""

from __future__ import annotations

import re
import shutil
import zipfile
from dataclasses import dataclass, field, fields
from pathlib import Path, PurePosixPath

from . import build as buildmod
from . import config, edit, hints, pipeline, voxels
from . import fetch as fetchmod
from .errors import SagasError
from .repo import Repo
from .scout import promote as promotemod
from .scout.base import Candidate
from .scout.sources import slug

# issue form headings -> field ids (the form's labels; tests keep them in sync)
FIELDS = {
    "Link to the model": "url",
    "Model file": "file",
    "Author": "author",
    "Licence": "license",
    "Where is the licence shown?": "evidence",
    "Saga": "saga",
    "New saga": "new_saga",
    "Name of the landmark": "title",
    "How big in the game?": "size",
    "Where should it appear?": "hints",
    "A line of lore": "lore",
    "What is it?": "kind",
    "Checks": "checks",
}
LICENCES = {
    "CC0": "CC0-1.0",
    "CC-BY 4.0": "CC-BY-4.0",
    "CC-BY 3.0": "CC-BY-3.0",
    "CC-BY-SA 4.0": "CC-BY-SA-4.0",
    "CC-BY-SA 3.0": "CC-BY-SA-3.0",
    "MIT": "MIT",
}
MODEL_SUFFIXES = (".glb", ".gltf", ".obj", ".stl", ".dae", ".ply", ".vox", ".zip")
MEMBER_ORDER = (".glb", ".gltf", ".dae", ".obj", ".stl", ".ply")
ATTACHMENT = re.compile(r"https://github\.com/(?:user-attachments/files|[\w.-]+/[\w.-]+/files)/[^\s)\]>]+")
DEFAULT_SIZE = 32


class IntakeError(SagasError):
    """The request cannot become a landmark as it is; the message goes back to the contributor."""


@dataclass
class Request:
    """A new landmark as a contributor describes it (the issue form, or Saga Forge)."""

    title: str
    url: str = ""  # where the model is shown: its page, or a direct link to the file
    file: str = ""  # a local copy of the model (dropped into Forge), kept as the original
    attachment: str = ""  # a file attached to the issue, downloaded and kept as the original
    license: str = ""  # an SPDX id, or the form's label (LICENCES)
    author: str = ""
    saga: str = ""  # an existing saga; empty for a new one
    new_saga: str = ""  # "Vikings: longhouses and ships of the north"
    size: int = DEFAULT_SIZE
    hints: str = ""
    lore: str = ""
    ai: bool = False
    notes: str = ""  # where the request came from, where the licence is shown
    id: str = ""  # default: from the title

    @classmethod
    def from_json(cls, data: dict) -> Request:
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise IntakeError(f"unknown field(s) {', '.join(unknown)}; known: {', '.join(sorted(known))}")
        if not isinstance(data.get("title"), str) or not data["title"].strip():
            raise IntakeError("the landmark needs a title")
        return cls(**data)


@dataclass
class Summary:
    saga: str
    id: str
    title: str
    path: str
    dims: tuple[int, int, int] = (0, 0, 0)
    nodes: int = 0
    placement: dict = field(default_factory=dict)
    matched: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    new_saga: bool = False
    files: list[str] = field(default_factory=list)  # what to commit, relative to the repository root


def parse_form(body: str) -> dict[str, str]:
    """The answers of an issue form, by field id ("_No response_" becomes "")."""
    out: dict[str, str] = {}
    parts = re.split(r"^### +(.+?)\s*$", body or "", flags=re.M)
    for heading, text in zip(parts[1::2], parts[2::2], strict=True):
        key = next((v for k, v in FIELDS.items() if heading.strip().startswith(k)), None)
        if key:
            value = text.strip()
            out[key] = "" if value == "_No response_" else value
    return out


def size_of(answer: str) -> int:
    m = re.search(r"about (\d+)", answer or "")
    return int(m.group(1)) if m else DEFAULT_SIZE


def new_saga_of(answer: str) -> tuple[str, str, str]:
    """("vikings", "Vikings", "Longhouses and ships of the north") from "Vikings: longhouses ..."."""
    name, _, description = (answer or "").partition(":")
    name = name.strip()
    sid = slug(name)[:24]
    if not name or not re.match(r"^[a-z][a-z0-9_]{2,23}$", sid):
        raise IntakeError('a new saga needs a name, e.g. "Vikings: longhouses and ships of the north"')
    return sid, name, description.strip()


def landmark_id(title: str) -> str:
    sid = slug(title)[:32].strip("_")
    return sid if re.match(r"^[a-z][a-z0-9_]{2,31}$", sid) else ("landmark_" + sid)[:32].strip("_")


def original_name(name: str) -> str:
    """The file name a kept original gets next to landmark.toml."""
    name = PurePosixPath(name.replace("\\", "/").split("?")[0]).name or "model"
    return f"original-{name}" if name in config.RESERVED_FILES else name


def download_section(url: str, original: str = "", mirror: str = "") -> dict:
    """How promote fills [source]. `original` is the name of a model file kept next to landmark.toml
    (a manual source); `mirror` the attachment it came from."""
    if original:
        where = "the file next to landmark.toml" + (" or the one attached to the issue" if mirror else "")
        section = {"manual": True, "file": original, "instructions": f"download {url or 'the model'}, or use {where}"}
        return {**section, "mirror": mirror} if mirror else section
    m = re.search(r"polyhaven\.com/a/([\w-]+)", url)
    if m:
        return {"polyhaven": m.group(1)}
    if PurePosixPath(url.split("?")[0]).suffix.lower() in MODEL_SUFFIXES:
        return {"url": url, "file": PurePosixPath(url.split("?")[0]).name}
    raise IntakeError(
        "the bot can't download this model from the link (most sites need a login). Download it yourself "
        'and drag the zip into the issue\'s "Model file" field.'
    )


def pick_member(archive: Path) -> str:
    """The model file inside a downloaded zip (scene.gltf from Sketchfab, else the first model)."""
    with zipfile.ZipFile(archive) as z:
        names = [n for n in z.namelist() if not n.endswith("/") and not PurePosixPath(n).name.startswith(".")]
    for suffix in MEMBER_ORDER:
        hits = sorted((n for n in names if n.lower().endswith(suffix)), key=lambda n: (n.count("/"), n))
        if hits:
            return hits[0]
    raise IntakeError(f"{archive.name} holds no model file ({', '.join(MEMBER_ORDER)})")


def _get(url: str, dest: Path) -> None:
    fetchmod._download(url, dest)


def licence_of(answer: str) -> str:
    """The SPDX id for a form label or an SPDX id; "" when it is not one we accept."""
    answer = (answer or "").strip()
    return LICENCES.get(answer) or (answer if answer in LICENCES.values() else "")


def run(repo: Repo, number: int, title: str, body: str, author: str = "", get=_get) -> Summary:
    """Create the landmark of issue `number`. `get(url, dest)` downloads attachments (tests stub it)."""
    form = parse_form(body)
    saga = form.get("saga", "").strip()
    notes = f"Suggested in issue #{number}" + (f" by @{author}" if author else "") + "."
    if form.get("evidence"):
        notes += f" Licence shown: {form['evidence']}."
    attachments = ATTACHMENT.findall(form.get("file", ""))
    req = Request(
        title=form.get("title") or re.sub(r"^\s*model\s*:\s*", "", title, flags=re.I).strip() or f"landmark {number}",
        url=form.get("url", "").strip(),
        attachment=attachments[0] if attachments else "",
        license=form.get("license", ""),
        author=form.get("author", ""),
        saga="" if saga.startswith("other") else saga,
        new_saga=form.get("new_saga", ""),
        size=size_of(form.get("size", "")),
        hints=form.get("hints", ""),
        lore=form.get("lore", ""),
        ai=form.get("kind", "").startswith("AI"),
        notes=notes,
    )
    if not req.url:
        raise IntakeError("the link to the model is missing")
    return create_landmark(repo, req, get=get, source=("issue", str(number)))


def create_landmark(repo: Repo, req: Request, get=_get, source: tuple[str, str] = ("forge", "")) -> Summary:
    """content/<saga>/<id>/ from a request: landmark.toml, the original model when it can't be
    downloaded again, voxels.vx.gz and preview.png. `source` names the request for the scouting
    record (kind, id)."""
    if not (req.url or req.file or req.attachment):
        raise IntakeError("a link to the model, or the model file, is needed")
    license = licence_of(req.license)
    if not license:
        raise IntakeError(f"licence {req.license!r} needs a closer look by a maintainer (licence-review)")
    if req.file and not Path(req.file).is_file():
        raise IntakeError(f"{req.file} is not a file")
    if not 4 <= int(req.size) <= 400:
        raise IntakeError("the size must be between 4 and 400 nodes")
    notes = []
    files: list[Path] = []
    saga = req.saga.strip()
    new_saga = False
    if not saga:
        saga, saga_title, saga_description = new_saga_of(req.new_saga)
        saga_toml = repo.content / saga / "saga.toml"
        if not saga_toml.exists():
            new_saga = True
            saga_toml.parent.mkdir(parents=True, exist_ok=True)
            saga_toml.write_text(
                f'title = "Sagas: {saga_title}"\ndescription = "{saga_description.replace(chr(34), chr(39))}"\n'
                'supported_games = "minetest_game, mineclonia, mineclone2"\n'
            )
            files.append(saga_toml)
            notes.append(f"new saga {saga}")
    elif not (repo.content / saga).is_dir():
        raise IntakeError(f"there is no saga {saga!r}; name a new one instead")
    name = req.title.strip()
    sid = req.id or landmark_id(name)
    if (repo.content / saga / sid / "landmark.toml").exists():
        raise IntakeError(f"{saga}/{sid} exists already; choose another name")
    kept = req.file or req.attachment
    original = original_name(kept) if kept else ""
    download = download_section(req.url, original, req.attachment)
    place = hints.suggest(req.hints)
    cand = Candidate(
        source=source[0], source_id=source[1] or sid, title=name, url=req.url, license=license, download=download
    )
    overrides = {
        "top": {"title": name, "lore": req.lore},
        "source": {"author": req.author, "ai": "generated" if req.ai else "none", "notes": req.notes},
        "transform": {"target_size": int(req.size)},
        "placement": {**place.fields(), "hints": req.hints},
    }
    path = promotemod.promote(repo, cand, saga, sid, overrides=overrides)
    files.append(path)
    landmark = config.load(path)
    if kept:
        dest = landmark.dir / original
        if req.file:
            shutil.copyfile(req.file, dest)
        else:
            get(req.attachment, dest)
        if dest.stat().st_size > config.ORIGINAL_MAX_BYTES:
            mb = dest.stat().st_size // 2**20
            shutil.rmtree(landmark.dir)
            raise IntakeError(
                f"{original} is {mb} MB; the limit is {config.ORIGINAL_MAX_BYTES // 2**20} MB."
                " A glb download is usually much smaller."
            )
        files.append(dest)
        if dest.suffix.lower() == ".zip" and not landmark.source.member:
            landmark = edit.set_values(path, {"source.member": pick_member(dest)})
        fetchmod.fetch(landmark, repo.sources)
    else:
        _, digest = fetchmod.fetch(landmark, repo.sources)
        for extra_file, _, extra_digest in fetchmod.fetch_extras(landmark, repo.sources):
            fetchmod.record_extra_sha256(landmark, extra_file, extra_digest)
        fetchmod.record_sha256(landmark, digest)
        landmark = config.load(path)
    model = pipeline.voxelize(landmark, repo)
    voxels.write(model, landmark.vx_path)
    res = buildmod.build(landmark, model)
    pipeline.write_preview(res)
    files += [landmark.vx_path, landmark.preview_path]
    if res.sealed:
        notes.append("the rooms have no door yet: comment /door +z (or -z, +x, -x) to cut one")
    return Summary(
        saga=saga,
        id=sid,
        title=name,
        path=str(path.parent.relative_to(repo.root)),
        dims=res.size,
        nodes=int(res.node_count),
        placement=place.fields(),
        matched=place.matched,
        notes=notes,
        new_saga=new_saga,
        files=[str(f.relative_to(repo.root)) for f in files],
    )
