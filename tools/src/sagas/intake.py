"""From a "Model found" issue to a landmark: the bot's half of a browser contribution.

The issue form (.github/ISSUE_TEMPLATE/model-found.yml) asks for the link, licence, saga, size and
the creator's words. `run` turns that into content/<saga>/<id>/ (landmark.toml through the scouting
`promote`, the source fetched from the link or from a zip attached to the issue, voxels and
preview.png) and returns a summary for the pull request. GitHub work (branch, commit, PR) is the
workflow's job (.github/workflows/intake.yml).
"""

from __future__ import annotations

import re
import tempfile
import zipfile
from dataclasses import dataclass, field
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
    """The issue cannot become a landmark as it is; the message goes back to the contributor."""


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


def download_section(url: str, attachments: list[str]) -> tuple[dict, str]:
    """How promote fills [source], and the attachment to fetch from (or "")."""
    if attachments:
        name = PurePosixPath(attachments[0].split("?")[0]).name
        instructions = f"download {url} (or the file attached to the issue) and run sagas fetch --from"
        return {"manual": True, "file": name, "instructions": instructions, "mirror": attachments[0]}, attachments[0]
    m = re.search(r"polyhaven\.com/a/([\w-]+)", url)
    if m:
        return {"polyhaven": m.group(1)}, ""
    if PurePosixPath(url.split("?")[0]).suffix.lower() in MODEL_SUFFIXES:
        return {"url": url, "file": PurePosixPath(url.split("?")[0]).name}, ""
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


def run(repo: Repo, number: int, title: str, body: str, author: str = "", get=_get) -> Summary:
    """Create the landmark of issue `number`. `get(url, dest)` downloads attachments (tests stub it)."""
    form = parse_form(body)
    url = form.get("url", "").strip()
    if not url:
        raise IntakeError("the link to the model is missing")
    license = LICENCES.get(form.get("license", ""))
    if not license:
        raise IntakeError(f"licence {form.get('license')!r} needs a closer look by a maintainer (licence-review)")
    notes = []
    saga = form.get("saga", "").strip()
    new_saga = False
    if not saga or saga.startswith("other"):
        saga, saga_title, saga_description = new_saga_of(form.get("new_saga", ""))
        if not (repo.content / saga / "saga.toml").exists():
            new_saga = True
            (repo.content / saga).mkdir(parents=True, exist_ok=True)
            (repo.content / saga / "saga.toml").write_text(
                f'title = "Sagas: {saga_title}"\ndescription = "{saga_description.replace(chr(34), chr(39))}"\n'
                'supported_games = "minetest_game, mineclonia, mineclone2"\n'
            )
            notes.append(f"new saga {saga}")
    name = form.get("title") or re.sub(r"^\s*model\s*:\s*", "", title, flags=re.I).strip() or f"landmark {number}"
    sid = landmark_id(name)
    attachments = ATTACHMENT.findall(form.get("file", ""))
    download, attachment = download_section(url, attachments)
    place = hints.suggest(form.get("hints", ""))
    kind = form.get("kind", "")
    source_notes = f"Suggested in issue #{number}" + (f" by @{author}" if author else "") + "."
    if form.get("evidence"):
        source_notes += f" Licence shown: {form['evidence']}."
    cand = Candidate(source="issue", source_id=str(number), title=name, url=url, license=license, download=download)
    overrides = {
        "top": {"title": name, "lore": form.get("lore", "")},
        "source": {
            "author": form.get("author", ""),
            "ai": "generated" if kind.startswith("AI") else "none",
            "notes": source_notes,
        },
        "transform": {"target_size": size_of(form.get("size", ""))},
        "placement": {**place.fields(), "hints": form.get("hints", "")},
    }
    path = promotemod.promote(repo, cand, saga, sid, overrides=overrides)
    landmark = config.load(path)
    if attachment:
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / landmark.source.file
            get(attachment, local)
            if local.suffix.lower() == ".zip" and not landmark.source.member:
                landmark = edit.set_values(path, {"source.member": pick_member(local)})
            fetchmod.fetch(landmark, repo.sources, src=local)
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
    )
