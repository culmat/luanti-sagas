"""docs/scouting/: scouting.json (all candidates), <saga>.md tables, rejected.json."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from ..repo import Repo
from .base import Candidate


def scouting_dir(repo: Repo) -> Path:
    return repo.root / "docs" / "scouting"


def load(repo: Repo) -> dict[str, Candidate]:
    p = scouting_dir(repo) / "scouting.json"
    if not p.exists():
        return {}
    return {d["id"]: Candidate.from_dict(d) for d in json.loads(p.read_text())}


def rejected(repo: Repo) -> dict[str, str]:
    p = scouting_dir(repo) / "rejected.json"
    return json.loads(p.read_text()) if p.exists() else {}


def known_urls(repo: Repo) -> set[str]:
    out = set()
    for s in repo.landmarks():
        out.add(s.source.url)
        out.add(s.source.author_url)
    out.discard("")
    return out


def merge(
    repo: Repo, found: list[Candidate], today: str | None = None, searched: set[tuple[str, str]] | None = None
) -> dict[str, Candidate]:
    """Merge a run into the report. Candidates of a (source, saga) that was searched again but not
    found any more are dropped; first_seen dates survive."""
    today = today or dt.date.today().isoformat()
    existing = load(repo)
    if searched:
        found_ids = {c.id for c in found}
        existing = {cid: c for cid, c in existing.items() if (c.source, c.saga) not in searched or cid in found_ids} | {
            cid: c for cid, c in existing.items() if cid in found_ids
        }
    skip = set(rejected(repo))
    urls = known_urls(repo)
    for c in found:
        if c.id in skip or c.url in urls:
            continue
        old = existing.get(c.id)
        c.first_seen = old.first_seen if old else today
        existing[c.id] = c
    for cid in list(existing):
        if cid in skip or existing[cid].url in urls:
            del existing[cid]
    return existing


def _size(n: int | None) -> str:
    if not n:
        return ""
    return f"{n / 1e6:.0f} MB" if n >= 1e6 else f"{n / 1e3:.0f} kB"


def write(repo: Repo, cands: dict[str, Candidate]) -> list[Path]:
    d = scouting_dir(repo)
    d.mkdir(parents=True, exist_ok=True)
    ordered = sorted(cands.values(), key=lambda c: (c.saga, c.source, c.id))
    (d / "scouting.json").write_text(json.dumps([c.to_dict() for c in ordered], indent=1, ensure_ascii=False) + "\n")
    written = [d / "scouting.json"]
    by_saga: dict[str, list[Candidate]] = {}
    for c in ordered:
        by_saga.setdefault(c.saga or "other", []).append(c)
    for saga, items in by_saga.items():
        lines = [
            f"# Scouting: {saga}",
            "",
            "Found by `sagas scout`; licences as reported by the source. Check the model page before promoting.",
            "Flags: licence-conflict = the description mentions NC/ND; trademark = possible protected character.",
            "",
            "| Model | Author | Licence | Faces | Size | Site | Flags | Promote |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for c in items:
            title = c.title.replace("|", "/")
            lines.append(
                f"| [{title}]({c.url}) | {c.author.replace('|', '/')} | {c.license} | {c.faces or ''} | "
                f"{_size(c.download_size)} | {' or '.join(c.suggested_site)} | {', '.join(c.flags)} | "
                f"`sagas scout promote {c.id}` |"
            )
        p = d / f"{saga}.md"
        p.write_text("\n".join(lines) + "\n")
        written.append(p)
    readme = d / "README.md"
    readme.write_text(
        "# Scouting reports\n\n"
        "Candidate models per saga, refreshed by `sagas scout` (weekly in CI as a pull request).\n"
        "Promote one with `sagas scout promote <id> --saga <saga> --id <landmark_id>`, or reject it with\n"
        '`sagas scout reject <id> --reason "..."` so it does not come back.\n\n'
        + "\n".join(f"- [{t}]({t}.md): {len(v)} candidates" for t, v in sorted(by_saga.items()))
        + "\n"
    )
    written.append(readme)
    return written


def reject(repo: Repo, cid: str, reason: str) -> None:
    d = scouting_dir(repo)
    d.mkdir(parents=True, exist_ok=True)
    r = rejected(repo)
    r[cid] = reason
    (d / "rejected.json").write_text(json.dumps(dict(sorted(r.items())), indent=1, ensure_ascii=False) + "\n")
