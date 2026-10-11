"""Download or copy source models (sha256-verified) and extract archive members safely."""

from __future__ import annotations

import hashlib
import re
import shutil
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from .config import Saga
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


def target_name(saga: Saga) -> str:
    if saga.source.file:
        return saga.source.file
    name = Path(unquote(urlparse(saga.source.url).path)).name
    if not name:
        raise SagasError(f"{saga.qualified_id}: set source.file (cannot derive a file name from the URL)")
    return name


def fetch(saga: Saga, sources: Path, src: Path | None = None, force: bool = False) -> tuple[Path, str]:
    dest = sources / saga.id / target_name(saga)
    dest.parent.mkdir(parents=True, exist_ok=True)
    local = saga.dir / target_name(saga)
    if local.exists() and src is None:
        dest = local  # committed next to saga.toml (small voxel files)
    elif src is not None:
        if not src.is_file():
            raise SagasError(f"{src} is not a file")
        shutil.copyfile(src, dest)
    elif dest.exists() and not force:
        pass
    elif saga.source.manual or not saga.source.url:
        msg = saga.source.instructions or f"download {saga.source.url or 'the model'} by hand"
        raise SourceMissing(f"needs a manual download: {msg}; then run: sagas fetch {saga.qualified_id} --from FILE")
    else:
        _download(saga.source.url, dest)
    digest = sha256_file(dest)
    if saga.source.sha256 and digest != saga.source.sha256:
        raise SagasError(f"{dest.name}: sha256 {digest} does not match source.sha256 {saga.source.sha256}")
    return dest, digest


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


def extract_member(archive: Path, member: str, dest_dir: Path) -> Path:
    """Extract `member` and the other files of its directory (textures) into dest_dir; return its path."""
    want = _safe(member)
    folder = want.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            infos = z.infolist()
            if len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > MAX_TOTAL:
                raise SagasError(f"{archive.name}: archive too large")
            for info in infos:
                if info.is_dir():
                    continue
                p = _safe(info.filename)
                if p.parent == folder and not (info.external_attr >> 16) & 0o170000 == 0o120000:
                    out = dest_dir / p.name
                    with z.open(info) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as t:
            members = t.getmembers()
            if len(members) > MAX_MEMBERS:
                raise SagasError(f"{archive.name}: archive too large")
            for info in members:
                if not info.isfile():
                    continue
                p = _safe(info.name)
                if p.parent == folder:
                    f = t.extractfile(info)
                    if f is not None:
                        with open(dest_dir / p.name, "wb") as dst:
                            shutil.copyfileobj(f, dst)
    else:
        raise SagasError(f"{archive.name} is not a zip or tar archive, but source.member is set")
    out = dest_dir / want.name
    if not out.exists():
        raise SagasError(f"{member!r} not found in {archive.name}")
    return out


_SOURCE = re.compile(r"(?ms)^\[source\]\s*$(.*?)(?=^\[|\Z)")


def record_sha256(saga: Saga, digest: str) -> None:
    text = saga.path.read_text(encoding="utf-8")
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
    saga.path.write_text(text, encoding="utf-8")
