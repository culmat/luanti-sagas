"""Orchestration used by the CLI: voxelize sources, build themes, write packs and previews."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import build as buildmod
from . import legacy, preview, registry, voxels
from .config import Saga
from .errors import SagasError, SourceMissing
from .repo import Repo


def source_file(saga: Saga, repo: Repo) -> Path:
    """Where the source file of a saga is: next to saga.toml, or in sources/<id>/."""
    name = saga.source.file
    if not name:
        raise SagasError(f"{saga.qualified_id}: source.file is not set")
    for cand in (saga.dir / name, repo.sources / saga.id / name):
        if cand.exists():
            return cand
    hint = saga.source.instructions or (f"run: sagas fetch {saga.qualified_id}" if saga.source.url else "")
    raise SourceMissing(f"{saga.qualified_id}: {name} not found in {saga.dir} or {repo.sources / saga.id}. {hint}")


def voxelize(saga: Saga, repo: Repo) -> voxels.VoxelModel:
    kind = saga.source.kind
    if kind == "voxels":
        model = legacy.read_txt(source_file(saga, repo))
    elif kind == "vox":
        from . import vox

        model = vox.read_vox(source_file(saga, repo), saga.transform)
    elif kind == "mesh":
        from . import fetch, load
        from . import voxelize as vz

        path = source_file(saga, repo)
        if saga.source.member:
            path = fetch.extract_member(path, saga.source.member, repo.sources / saga.id / "extracted")
        mesh = load.load_model(path)
        model = vz.voxelize(mesh, saga.transform, saga.voxel)
    else:
        raise SagasError(f"{saga.qualified_id}: source.kind {kind!r} cannot be voxelized")
    if saga.source.sha256:
        model.source_sha256 = saga.source.sha256
    return model


@dataclass
class ThemeBuild:
    theme: str
    results: list[buildmod.BuildResult] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)


def build_theme(repo: Repo, theme: str, check: bool = False) -> ThemeBuild:
    tb = ThemeBuild(theme)
    for saga in repo.sagas(theme):
        if not saga.vx_path.exists():
            continue
        tb.results.append(buildmod.build(saga, voxels.read(saga.vx_path)))
    t = repo.theme(theme)
    if check:
        tb.stale = registry.diff_pack(t, tb.results, repo.pack_dir(theme)) if tb.results else []
    elif tb.results:
        tb.written = registry.write_pack(t, tb.results, repo.pack_dir(theme))
    return tb


def write_preview(res: buildmod.BuildResult, size: int = 1024) -> Path:
    path = res.saga.preview_path
    with tempfile.NamedTemporaryFile(suffix=".png", dir=path.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    preview.write(res, tmp_path, size)
    tmp_path.replace(path)
    return path
