"""Download or copy source models (sha256-verified) and extract archive members safely."""

from __future__ import annotations

import hashlib
import re
import shutil
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from .config import Landmark
from .errors import SagasError, SourceMissing

MAX_MEMBERS = 20_000
MAX_TOTAL = 4 * 1024**3
USER_AGENT = "luanti-sagas/0.1 (+https://github.com/culmat/luanti-sagas)"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def target_name(landmark: Landmark) -> str:
    if landmark.source.file:
        return landmark.source.file
    name = Path(unquote(urlparse(landmark.source.url).path)).name
    if not name:
        raise SagasError(f"{landmark.qualified_id}: set source.file (cannot derive a file name from the URL)")
    return name


def cache_path(landmark: Landmark, sources: Path) -> Path:
    """Where a source file lives: shared per URL (several landmarks can use one archive), else per landmark."""
    if landmark.source.url:
        key = hashlib.sha1(landmark.source.url.encode()).hexdigest()[:16]
        return sources / "_url" / key / target_name(landmark)
    return sources / landmark.id / target_name(landmark)


def extract_dir(archive: Path, member: str) -> Path:
    """Per-member extraction folder (textures with equal names in different folders must not collide)."""
    key = hashlib.sha1(str(PurePosixPath(member.replace("\\", "/")).parent).encode()).hexdigest()[:12]
    return archive.parent / "extracted" / key


def fetch(landmark: Landmark, sources: Path, src: Path | None = None, force: bool = False) -> tuple[Path, str]:
    dest = cache_path(landmark, sources)
    dest.parent.mkdir(parents=True, exist_ok=True)
    local = landmark.dir / target_name(landmark)
    if local.exists() and src is None:
        dest = local  # committed next to landmark.toml (small voxel files)
    elif src is not None:
        if not src.is_file():
            raise SagasError(f"{src} is not a file")
        shutil.copyfile(src, dest)
    elif dest.exists() and not force:
        pass
    elif landmark.source.manual or not landmark.source.url:
        msg = landmark.source.instructions or f"download {landmark.source.url or 'the model'} by hand"
        raise SourceMissing(
            f"needs a manual download: {msg}; then run: sagas fetch {landmark.qualified_id} --from FILE"
        )
    else:
        _download(landmark.source.url, dest)
    digest = sha256_file(dest)
    # manual downloads (e.g. Sketchfab zips) differ per download, so their checksum is not verified
    if landmark.source.sha256 and not landmark.source.manual and digest != landmark.source.sha256:
        raise SagasError(f"{dest.name}: sha256 {digest} does not match source.sha256 {landmark.source.sha256}")
    return dest, digest


def fetch_extras(landmark: Landmark, sources: Path, force: bool = False) -> list[tuple[str, Path, str]]:
    """Download source.extra_files next to the main file; verify sha256 when given."""
    out = []
    base = cache_path(landmark, sources).parent
    base.mkdir(parents=True, exist_ok=True)
    for extra in landmark.source.extra_files:
        dest = base.joinpath(*_safe(extra["file"]).parts)  # may contain folders, e.g. textures/x.jpg
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or force:
            if not extra.get("url"):
                raise SourceMissing(
                    f"{landmark.qualified_id}: extra file {extra['file']} has no url; copy it to {dest}"
                )
            _download(extra["url"], dest)
        digest = sha256_file(dest)
        if extra.get("sha256") and digest != extra["sha256"]:
            raise SagasError(f"{dest.name}: sha256 {digest} does not match {extra['sha256']}")
        out.append((extra["file"], dest, digest))
    return out


def _download(url: str, dest: Path) -> None:
    import httpx

    part = dest.with_name(dest.name + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=60, headers={"User-Agent": USER_AGENT}) as r:
        if r.status_code != 200:
            raise SagasError(f"download failed: HTTP {r.status_code} for {url}")
        with open(part, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    part.replace(dest)


def _safe(name: str) -> PurePosixPath:
    p = PurePosixPath(name.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise SagasError(f"unsafe path in archive: {name!r}")
    return p


def _under(p: PurePosixPath, folder: PurePosixPath) -> PurePosixPath | None:
    """Path of p relative to folder, or None if p is not inside folder."""
    if str(folder) in ("", "."):
        return p
    try:
        return p.relative_to(folder)
    except ValueError:
        return None


def extract_member(archive: Path, member: str, dest_dir: Path) -> Path:
    """Extract `member` and every file below its folder (textures, buffers) into dest_dir, keeping
    relative paths; return the extracted member."""
    want = _safe(member)
    folder = want.parent
    dest_dir.mkdir(parents=True, exist_ok=True)

    def write(rel: PurePosixPath, src) -> None:
        out = dest_dir.joinpath(*rel.parts)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "wb") as dst:
            shutil.copyfileobj(src, dst)

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            infos = z.infolist()
            if len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > MAX_TOTAL:
                raise SagasError(f"{archive.name}: archive too large")
            for info in infos:
                if info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000:
                    continue
                rel = _under(_safe(info.filename), folder)
                if rel is not None:
                    with z.open(info) as src:
                        write(rel, src)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as t:
            members = t.getmembers()
            if len(members) > MAX_MEMBERS:
                raise SagasError(f"{archive.name}: archive too large")
            for info in members:
                if not info.isfile():
                    continue
                rel = _under(_safe(info.name), folder)
                f = t.extractfile(info) if rel is not None else None
                if f is not None and rel is not None:
                    write(rel, f)
    else:
        raise SagasError(f"{archive.name} is not a zip or tar archive, but source.member is set")
    out = dest_dir / want.name
    if not out.exists():
        raise SagasError(f"{member!r} not found in {archive.name}")
    return out


def record_extra_sha256(landmark: Landmark, file: str, digest: str) -> bool:
    """Fill sha256 = "" of the extra_files entry for `file` (inline-table form written by sagas new)."""
    text = landmark.path.read_text(encoding="utf-8")
    pat = re.compile(r'(file\s*=\s*"' + re.escape(file) + r'"\s*,\s*sha256\s*=\s*)""')
    new, n = pat.subn(lambda m: m.group(1) + f'"{digest}"', text, count=1)
    if n:
        landmark.path.write_text(new, encoding="utf-8")
    return bool(n)


_SOURCE = re.compile(r"(?ms)^\[source\]\s*$(.*?)(?=^\[|\Z)")


def record_sha256(landmark: Landmark, digest: str) -> None:
    text = landmark.path.read_text(encoding="utf-8")
    m = _SOURCE.search(text)
    if not m:
        text += f'\n[source]\nsha256 = "{digest}"\n'
    else:
        body = m.group(1)
        if re.search(r"(?m)^sha256\s*=", body):
            body = re.sub(r"(?m)^sha256\s*=.*$", f'sha256 = "{digest}"', body, count=1)
        else:
            body = f'\nsha256 = "{digest}"' + body
        text = text[: m.start(1)] + body + text[m.end(1) :]
    landmark.path.write_text(text, encoding="utf-8")
