"""Policy checks for sagas: licences, attribution, size limits, value budget, generated-file drift."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from . import palette, vocab
from .build import BuildResult, fits_chunk
from .config import LICENSE_ALLOWLIST, SHARE_ALIKE, Landmark
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
    "L007": "pack mixes share-alike and other licences",
    "L008": "generated files are stale (run sagas build)",
    "L009": "directory does not match id/saga",
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
    landmark: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():5} {self.code} {self.landmark}: {self.message}"


def check_saga(landmark: Landmark, built: BuildResult | None = None, strict: bool = False) -> list[Finding]:
    out: list[Finding] = []
    sid = landmark.qualified_id

    def add(code: str, msg: str, level: str = "error") -> None:
        out.append(Finding(code, level, sid, msg))

    src = landmark.source
    for name in ("license", "author"):
        if not getattr(src, name):
            add("L001", f"source.{name} is required")
    if (
        src.kind in ("mesh", "vox", "voxels")
        and not src.url
        and not src.manual
        and not (landmark.dir / src.file).is_file()
    ):
        add("L001", "source.url is required (where the model can be found)")
    if src.license and src.license not in LICENSE_ALLOWLIST:
        add("L002", f"{src.license!r} is not one of {', '.join(LICENSE_ALLOWLIST)} (NC/ND licences are never allowed)")
    if src.kind in ("mesh", "vox") and not src.manual and not SHA_RE.match(src.sha256 or ""):
        add(
            "L003",
            "source.sha256 must be the 64-hex sha256 of the downloaded file (sagas fetch fills it)",
            "error" if strict else "warn",
        )
    for extra in src.extra_files:
        if not SHA_RE.match(extra.get("sha256", "")):
            add("L003", f"source.extra_files: {extra.get('file')} needs a sha256", "error" if strict else "warn")
    if src.ai == "generated" and not src.notes.strip():
        add("L006", "source.notes must name the AI tool used to generate the model")
    for text in (src.notes, src.license_url, src.instructions):
        if text and NC_ND.search(text):
            add("L013", f"check the licence: {text[:80]!r}")
    if landmark.dir.name != landmark.id:
        add("L009", f"directory {landmark.dir.name!r} must be named like the id {landmark.id!r}")
    if landmark.dir.parent.name != landmark.saga:
        add("L009", f"saga directory {landmark.dir.parent.name!r} must match saga {landmark.saga!r}")
    if not landmark.vx_path.exists() and src.kind != "none":
        add("L012", f"{landmark.vx_path.name} is missing")
    if not landmark.preview_path.exists():
        add("L010", "preview.png is missing", "warn")
    for f in landmark.dir.iterdir():
        if f.is_file() and f.stat().st_size > MAX_FILE_BYTES:
            add("L014", f"{f.name} is {f.stat().st_size // 1024} KiB (limit {MAX_FILE_BYTES // 1024} KiB)")
    if landmark.placement.rarity < 20:
        add(
            "L015",
            f"rarity {landmark.placement.rarity} means a landmark every {landmark.placement.rarity} mapchunks",
            "warn",
        )
    if built is not None:
        if not fits_chunk(built.size) and not landmark.placement.large:
            fp, h = vocab.vocabulary()["chunk_limits"].values()
            add(
                "L004",
                f"size {built.size} exceeds {fp}x{h}x{fp}; set placement.large = true or lower transform.target_size",
            )
        for msg in built.findings:
            add("L005", msg)
    return out


def check_packs(landmarks: list[Landmark]) -> list[Finding]:
    """Pack-level checks: mixing share-alike and other licences makes the whole pack share-alike."""
    out = []
    by_saga: dict[str, set[str]] = {}
    for s in landmarks:
        by_saga.setdefault(s.saga, set()).add(s.source.license)
    for saga, lics in sorted(by_saga.items()):
        sa = lics & set(SHARE_ALIKE)
        if sa and lics - set(SHARE_ALIKE):
            out.append(
                Finding(
                    "L007",
                    "warn",
                    f"sagas_{saga}",
                    f"mixes {', '.join(sorted(sa))} with {', '.join(sorted(lics - sa))}: the whole pack "
                    "becomes share-alike; consider a separate saga",
                )
            )
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
