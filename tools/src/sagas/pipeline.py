"""Orchestration used by the CLI: voxelize sources, build sagas, write packs and previews."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import build as buildmod
from . import legacy, preview, registry, voxels
from .config import Landmark
from .errors import SagasError, SourceMissing
from .repo import Repo


def source_file(landmark: Landmark, repo: Repo, original: bool = False) -> Path:
    """Where the model of a landmark is: `source.edited` next to landmark.toml when set (unless
    `original`), else the original next to landmark.toml or in sources/."""
    from . import fetch

    if landmark.source.edited and not original:
        path = landmark.dir / landmark.source.edited
        if not path.exists():
            raise SourceMissing(f"{landmark.qualified_id}: source.edited {path.name} not found in {landmark.dir}")
        return path
    name = landmark.source.file
    if not name:
        raise SagasError(f"{landmark.qualified_id}: source.file is not set")
    for cand in (landmark.dir / name, fetch.cache_path(landmark, repo.sources), repo.sources / landmark.id / name):
        if cand.exists():
            return cand
    hint = landmark.source.instructions or (f"run: sagas fetch {landmark.qualified_id}" if landmark.source.url else "")
    raise SourceMissing(
        f"{landmark.qualified_id}: {name} not found in {landmark.dir} or {repo.sources / landmark.id}. {hint}"
    )


def uses_edited(landmark: Landmark, original: bool = False) -> bool:
    return bool(landmark.source.edited) and not original


def load_mesh(landmark: Landmark, repo: Repo, original: bool = False):
    """The source mesh of a `kind = "mesh"` landmark, with `voxel.texture` applied."""
    from . import fetch, load

    path = source_file(landmark, repo, original)
    if landmark.source.member and not uses_edited(landmark, original):
        path = fetch.extract_member(path, landmark.source.member, fetch.extract_dir(path, landmark.source.member))
    mesh = load.load_model(path)
    if landmark.voxel.texture or landmark.voxel.alpha == "ignore":
        tex = None
        if landmark.voxel.texture:
            for cand in (
                path.parent / landmark.voxel.texture,
                source_file(landmark, repo, original).parent / landmark.voxel.texture,
                landmark.dir / landmark.voxel.texture,
            ):
                if cand.exists():
                    tex = cand
                    break
            if tex is None:
                raise SourceMissing(
                    f"{landmark.qualified_id}: texture {landmark.voxel.texture} not found (sagas fetch)"
                )
        load.apply_texture(mesh, tex, landmark.voxel.alpha)
    return mesh


def voxelize(landmark: Landmark, repo: Repo, original: bool = False) -> voxels.VoxelModel:
    """Voxelize the landmark's model: the edited one when there is one, else (or with `original`) the
    original."""
    kind = landmark.source.kind
    if kind == "voxels":
        model = legacy.read_txt(source_file(landmark, repo, original))
    elif kind == "handbuilt":
        from . import handbuilt

        model, unknown = handbuilt.read_mts(source_file(landmark, repo, original))
        if unknown:
            import sys

            print(
                f"{landmark.qualified_id}: no class for {', '.join(unknown)} (default class used; add rules)",
                file=sys.stderr,
            )
    elif kind == "vox":
        from . import vox

        model = vox.read_vox(source_file(landmark, repo, original), landmark.transform)
    elif kind == "mesh":
        from . import voxelize as vz

        model = vz.voxelize(load_mesh(landmark, repo, original), landmark.transform, landmark.voxel)
    else:
        raise SagasError(f"{landmark.qualified_id}: source.kind {kind!r} cannot be voxelized")
    if uses_edited(landmark, original):
        from . import fetch

        model.source_sha256 = fetch.sha256_file(source_file(landmark, repo))
    elif landmark.source.sha256:
        model.source_sha256 = landmark.source.sha256
    return model


def same_voxels(a: voxels.VoxelModel, b: voxels.VoxelModel) -> bool:
    import numpy as np

    return (
        a.size == b.size
        and np.array_equal(a.occ, b.occ)
        and np.array_equal(a.rgb[a.occ], b.rgb[b.occ])
        and np.array_equal(a.part[a.occ], b.part[b.occ])
        and a.parts == b.parts
    )


@dataclass
class ThemeBuild:
    saga: str
    results: list[buildmod.BuildResult] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)


def build_saga(repo: Repo, saga: str, check: bool = False) -> ThemeBuild:
    tb = ThemeBuild(saga)
    for landmark in repo.landmarks(saga):
        if not landmark.vx_path.exists():
            continue
        tb.results.append(buildmod.build(landmark, voxels.read(landmark.vx_path)))
    t = repo.saga(saga)
    if check:
        tb.stale = registry.diff_pack(t, tb.results, repo.pack_dir(saga)) if tb.results else []
    elif tb.results:
        tb.written = registry.write_pack(t, tb.results, repo.pack_dir(saga))
    return tb


def write_preview(res: buildmod.BuildResult, size: int = 1024) -> Path:
    """preview.png, rewritten only when the picture changed, so a rebuild on another system doesn't
    touch every file."""
    path = res.landmark.preview_path
    img = preview.render(res, size)
    if preview.same_picture(img, path):
        return path
    with tempfile.NamedTemporaryFile(suffix=".png", dir=path.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    img.save(tmp_path, optimize=True)
    tmp_path.replace(path)
    return path
