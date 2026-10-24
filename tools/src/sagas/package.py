"""Release zips for ContentDB: one top-level folder named like the package, dev files left out."""

from __future__ import annotations

import fnmatch
import zipfile
from pathlib import Path

DEFAULT_IGNORE = (".git", ".github", "__pycache__", ".DS_Store")
_EPOCH = (2026, 1, 1, 0, 0, 0)


def modpack_name(mods: Path) -> str:
    """The modpack's name from modpack.conf: the ContentDB package and the zip's top-level folder."""
    for line in (mods / "modpack.conf").read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "name" and value.strip():
            return value.strip()
    return mods.name


def export_ignored(mod_dir: Path) -> list[str]:
    """Patterns marked export-ignore in every .gitattributes below mod_dir, relative to mod_dir."""
    out = []
    for attrs in sorted(mod_dir.rglob(".gitattributes")):
        prefix = attrs.parent.relative_to(mod_dir).as_posix()
        prefix = "" if prefix == "." else prefix + "/"
        for line in attrs.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2 and "export-ignore" in parts[1:] and not parts[0].startswith("#"):
                out.append(prefix + parts[0].lstrip("/"))
    return out


def _ignored(rel: str, patterns: list[str]) -> bool:
    if any(part in DEFAULT_IGNORE for part in rel.split("/")):
        return True
    return any(fnmatch.fnmatch(rel, p) or rel.startswith(p.rstrip("/") + "/") for p in patterns)


def build_zip(mod_dir: Path, out: Path, name: str | None = None) -> list[str]:
    """Write a deterministic zip of mod_dir under the folder `name` (default: the directory name)."""
    name = name or mod_dir.name
    patterns = export_ignored(mod_dir)
    files = sorted(p for p in mod_dir.rglob("*") if p.is_file())
    included = []
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            rel = p.relative_to(mod_dir).as_posix()
            if _ignored(rel, patterns):
                continue
            info = zipfile.ZipInfo(f"{name}/{rel}", date_time=_EPOCH)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, p.read_bytes())
            included.append(rel)
    return included
