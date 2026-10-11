"""Policy checks for sagas: licences, attribution, size limits, value budget, generated-file drift."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from . import palette, vocab
from .build import BuildResult, fits_chunk
from .config import LICENSE_ALLOWLIST, SHARE_ALIKE, Saga
from .repo import Repo

MAX_FILE_BYTES = 2 * 1024 * 1024
NC_ND = re.compile(r"non[- ]?commercial|\bNC\b|no[- ]?deriv|\bND\b|all rights reserved|editorial", re.IGNORECASE)
SHA_RE = re.compile(r"^[0-9a-f]{64}$")

CODES = {
    "L001": "required field missing",
    "L002": "licence not allowed on ContentDB",
    "L003": "source sha256 missing or malformed",
    "L004": "too large for a mapchunk without large = true",
    "L005": "value budget exceeded",
    "L006": "AI-generated source without the tool named",
    "L007": "share-alike licence makes the whole pack share-alike",
    "L008": "generated files are stale (run sagas build)",
    "L009": "directory does not match id/theme",
    "L010": "preview.png missing (run sagas preview)",
    "L011": "core mod out of sync with the tools (run sagas sync-core)",
    "L012": "voxels.vx.gz missing (run sagas voxelize)",
    "L013": "licence text hints at NC/ND restrictions",
    "L014": "file too large to commit",
    "L015": "very low rarity (more than one per 20 mapchunks)",
}


@dataclass
class Finding:
    code: str
    level: str  # error | warn
    saga: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():5} {self.code} {self.saga}: {self.message}"


def check_saga(saga: Saga, built: BuildResult | None = None, strict: bool = False) -> list[Finding]:
    out: list[Finding] = []
    sid = saga.qualified_id

    def add(code: str, msg: str, level: str = "error") -> None:
        out.append(Finding(code, level, sid, msg))

    src = saga.source
    for name in ("license", "author"):
        if not getattr(src, name):
            add("L001", f"source.{name} is required")
    if src.kind in ("mesh", "vox", "voxels") and not src.url and not src.manual:
        add("L001", "source.url is required (where the model can be found)")
    if src.license and src.license not in LICENSE_ALLOWLIST:
        add("L002", f"{src.license!r} is not one of {', '.join(LICENSE_ALLOWLIST)} (NC/ND licences are never allowed)")
    if src.kind in ("mesh", "vox") and not SHA_RE.match(src.sha256 or ""):
        add(
            "L003",
            "source.sha256 must be the 64-hex sha256 of the downloaded file (sagas fetch fills it)",
            "error" if strict else "warn",
        )
    if src.ai == "generated" and not src.notes.strip():
        add("L006", "source.notes must name the AI tool used to generate the model")
    if src.license in SHARE_ALIKE:
        add("L007", f"{src.license}: the pack sagas_{saga.theme} will be share-alike", "warn")
    for text in (src.notes, src.license_url, src.instructions):
        if text and NC_ND.search(text):
            add("L013", f"check the licence: {text[:80]!r}")
    if saga.dir.name != saga.id:
        add("L009", f"directory {saga.dir.name!r} must be named like the id {saga.id!r}")
    if saga.dir.parent.name != saga.theme:
        add("L009", f"theme directory {saga.dir.parent.name!r} must match theme {saga.theme!r}")
    if not saga.vx_path.exists() and src.kind != "none":
        add("L012", f"{saga.vx_path.name} is missing")
    if not saga.preview_path.exists():
        add("L010", "preview.png is missing", "warn")
    for f in saga.dir.iterdir():
        if f.is_file() and f.stat().st_size > MAX_FILE_BYTES:
            add("L014", f"{f.name} is {f.stat().st_size // 1024} KiB (limit {MAX_FILE_BYTES // 1024} KiB)")
    if saga.placement.rarity < 20:
        add("L015", f"rarity {saga.placement.rarity} means a saga every {saga.placement.rarity} mapchunks", "warn")
    if built is not None:
        if not fits_chunk(built.size) and not saga.placement.large:
            fp, h = vocab.vocabulary()["chunk_limits"].values()
            add(
                "L004",
                f"size {built.size} exceeds {fp}x{h}x{fp}; set placement.large = true or lower transform.target_size",
            )
        for msg in built.findings:
            add("L005", msg)
    return out


def check_core(repo: Repo) -> list[Finding]:
    out = []
    core = repo.core_mod
    voc = core / "vocabulary.json"
    png = core / "textures" / "sagas_palette.png"
    if not voc.exists() or voc.read_bytes() != vocab.vocabulary_bytes():
        out.append(Finding("L011", "error", "sagas", f"{voc.relative_to(repo.root)} differs from the tools' copy"))
    if not png.exists() or not palette.png_matches(png):
        out.append(Finding("L011", "error", "sagas", f"{png.relative_to(repo.root)} differs from palette256.txt"))
    return out


def to_json(findings: list[Finding]) -> str:
    return json.dumps([asdict(f) for f in findings], indent=2)


def errors(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.level == "error"]


def write_report(findings: list[Finding], path: Path) -> None:
    path.write_text("\n".join(str(f) for f in findings) + "\n")
