"""`sagas` command line."""

from __future__ import annotations

import functools
import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from . import __version__, catalog, config, legacy, lint, palette, pipeline, vocab, voxels
from . import build as buildmod
from .errors import EXIT_DRIFT, EXIT_LINT, EXIT_USAGE, SagasError
from .repo import Repo, find_root

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Turn 3D models into Luanti landmarks (sagas).")
state: dict = {"root": None}


def repo() -> Repo:
    return find_root(state["root"])


def guarded(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SagasError as e:
            typer.secho(f"error: {e}", fg="red", err=True)
            raise typer.Exit(e.exit_code) from None

    return wrapper


@app.callback()
def main_options(
    root: Annotated[Path | None, typer.Option(help="Repository root (default: search upwards)")] = None,
):
    state["root"] = root


@app.command()
def version():
    """Print the version."""
    typer.echo(f"sagas {__version__}")


SAGA_TEMPLATE = """schema = 1
id = "{id}"
theme = "{theme}"
title = "{title}"
tags = []
lore = ""

[source]
kind = "{kind}"
url = "{url}"
manual = {manual}
instructions = ""
file = "{file}"
member = ""
sha256 = ""
author = "{author}"
author_url = ""
license = "{license}"
ai = "none"
notes = ""

[transform]
up = "auto"
rotate_y = 0
target_size = {target_size}
anchor = "bottom-center"

[voxel]
mode = "shell"

[materials]
mode = "{mode}"          # classes (realistic) | hybrid | palette (fantasy, colours)
default = "stone"
context = "surroundings"  # the mod reuses the stone/wood around the site
# [[materials.rules]]
# match = {{ material = "*roof*" }}
# class = "roof_red"

[placement]
site = ["plain"]          # alternatives; combine primitives with +, e.g. "cliff+coast"
exposure = "any"          # prominent | hidden | any
biomes = ["any"]
rarity = 400              # about one per N mapchunks
hints = ""                # placement and material hints in your own words
"""


@app.command()
@guarded
def new(
    id: str,
    theme: Annotated[str, typer.Option(help="Theme (content/<theme>/)")],
    title: Annotated[str, typer.Option()] = "",
    url: Annotated[str, typer.Option(help="Where the model can be found")] = "",
    license: Annotated[str, typer.Option(help="SPDX licence of the model")] = "",
    author: Annotated[str, typer.Option()] = "",
    kind: Annotated[str, typer.Option(help="mesh | vox | voxels")] = "mesh",
    file: Annotated[str, typer.Option(help="Source file name (in sources/<id>/ or next to saga.toml)")] = "",
    mode: Annotated[str, typer.Option(help="classes | hybrid | palette")] = "classes",
    target_size: Annotated[int, typer.Option(help="Longest side in nodes")] = 48,
    manual: Annotated[bool, typer.Option(help="The model must be downloaded by hand")] = False,
):
    """Scaffold content/<theme>/<id>/saga.toml."""
    r = repo()
    d = r.content / theme / id
    if (d / "saga.toml").exists():
        raise SagasError(f"{d / 'saga.toml'} already exists")
    d.mkdir(parents=True, exist_ok=True)
    text = SAGA_TEMPLATE.format(
        id=id,
        theme=theme,
        title=title or id.replace("_", " ").title(),
        kind=kind,
        url=url,
        manual=str(manual).lower(),
        file=file,
        author=author,
        license=license,
        target_size=target_size,
        mode=mode,
    )
    (d / "saga.toml").write_text(text)
    config.load(d / "saga.toml")
    typer.echo(f"created {d / 'saga.toml'}")


@app.command("convert-txt")
@guarded
def convert_txt(
    file: Path,
    theme: Annotated[str, typer.Option()],
    id: Annotated[str, typer.Option(help="Saga id (default: file name)")] = "",
    title: Annotated[str, typer.Option()] = "",
    license: Annotated[str, typer.Option()] = "",
    author: Annotated[str, typer.Option()] = "",
    url: Annotated[str, typer.Option()] = "",
    mode: Annotated[str, typer.Option(help="classes | hybrid | palette (default: palette if coloured)")] = "",
    force: Annotated[bool, typer.Option(help="Overwrite an existing saga.toml")] = False,
):
    """Import a voxel point list (x, y, z[, r, g, b] per line, e.g. drububu.com .txt export)."""
    r = repo()
    sid = id or file.stem.lower().replace(" ", "_").replace("-", "_")
    model = legacy.read_txt(file)
    d = r.content / theme / sid
    d.mkdir(parents=True, exist_ok=True)
    toml = d / "saga.toml"
    if not toml.exists() or force:
        m = mode or ("palette" if model.has_rgb.any() else "classes")
        toml.write_text(
            SAGA_TEMPLATE.format(
                id=sid,
                theme=theme,
                title=title or sid.replace("_", " ").title(),
                kind="voxels",
                url=url,
                manual="false",
                file=file.name,
                author=author,
                license=license,
                target_size=max(model.size),
                mode=m,
            )
        )
    saga = config.load(toml)
    voxels.write(model, saga.vx_path)
    typer.echo(
        f"{saga.qualified_id}: {model.size[0]}x{model.size[1]}x{model.size[2]}, {model.count} voxels -> {saga.vx_path}"
    )


@app.command()
@guarded
def fetch(
    selector: Annotated[str, typer.Argument()] = "all",
    from_: Annotated[Path | None, typer.Option("--from", help="Copy this local file instead of downloading")] = None,
    force: Annotated[bool, typer.Option()] = False,
):
    """Download (or copy) source models into sources/<id>/ and record their sha256."""
    from . import fetch as fetchmod

    r = repo()
    missing = 0
    for saga in r.select(selector):
        if saga.source.kind in ("none", "handbuilt"):
            continue
        try:
            path, digest = fetchmod.fetch(saga, r.sources, src=from_, force=force)
        except SagasError as e:
            missing += 1
            typer.secho(f"{saga.qualified_id}: {e}", fg="yellow", err=True)
            continue
        for extra_file, _, extra_digest in fetchmod.fetch_extras(saga, r.sources, force=force):
            recorded = fetchmod.record_extra_sha256(saga, extra_file, extra_digest)
            note = "sha256 recorded" if recorded else "sha256 ok"
            typer.echo(f"{saga.qualified_id}: {extra_file} ({note})")
        if saga.source.manual:
            typer.echo(f"{saga.qualified_id}: {path} (manual download, sha256 not recorded)")
        elif not saga.source.sha256:
            fetchmod.record_sha256(saga, digest)
            typer.echo(f"{saga.qualified_id}: {path} (sha256 recorded)")
        else:
            typer.echo(f"{saga.qualified_id}: {path} (sha256 ok)")
    if missing:
        raise typer.Exit(4)


@app.command()
@guarded
def inspect(target: str, as_json: Annotated[bool, typer.Option("--json")] = False):
    """Show parts, materials, textures and size of a model file or a saga's source."""
    from . import load

    r = None
    p = Path(target)
    if not p.is_file():
        r = repo()
        saga = r.select(target)[0]
        p = pipeline.source_file(saga, r)
        if saga.source.member:
            from . import fetch as fetchmod

            p = fetchmod.extract_member(p, saga.source.member, fetchmod.extract_dir(p, saga.source.member))
    info = load.inspect(load.load_model(p))
    if as_json:
        typer.echo(json.dumps(info, indent=2))
        return
    for k, v in info.items():
        if k == "parts":
            typer.echo("parts:")
            for part in v:
                typer.echo(
                    f"  {part['name']:<32} material={part['material']!r:<24} tris={part['tris']:<8} "
                    f"texture={part['texture']}"
                )
        else:
            typer.echo(f"{k}: {v}")


@app.command()
@guarded
def voxelize(selector: Annotated[str, typer.Argument()] = "all", force: Annotated[bool, typer.Option()] = False):
    """Source model -> content/<theme>/<id>/voxels.vx.gz."""
    r = repo()
    missing = failed = 0
    for saga in r.select(selector):
        if saga.vx_path.exists() and not force:
            typer.echo(f"{saga.qualified_id}: {saga.vx_path.name} exists (use --force)")
            continue
        try:
            model = pipeline.voxelize(saga, r)
        except SagasError as e:
            if e.exit_code == 4:
                missing += 1
                typer.secho(str(e), fg="yellow", err=True)
                continue
            raise
        except (ValueError, OSError, KeyError) as e:
            failed += 1
            typer.secho(f"{saga.qualified_id}: {e}", fg="red", err=True)
            continue
        voxels.write(model, saga.vx_path)
        x, y, z = model.size
        typer.echo(f"{saga.qualified_id}: {x}x{y}x{z}, {model.count} voxels")
    if failed:
        raise typer.Exit(1)
    if missing:
        raise typer.Exit(4)


@app.command()
@guarded
def build(
    selector: Annotated[str, typer.Argument()] = "all",
    check: Annotated[bool, typer.Option(help="Write nothing; exit 5 if committed packs are stale")] = False,
    no_preview: Annotated[bool, typer.Option("--no-preview")] = False,
):
    """voxels.vx.gz -> mods/sagas_<theme>/ (schematics, registry.lua, licences) and previews."""
    r = repo()
    chosen = r.select(selector)
    themes = sorted({s.theme for s in chosen})
    ids = {s.qualified_id for s in chosen}
    stale_total = []
    for theme in themes:
        tb = pipeline.build_theme(r, theme, check=check)
        if check:
            stale_total += [f"mods/sagas_{theme}/{p}" for p in tb.stale]
            continue
        for res in tb.results:
            x, y, z = res.size
            note = f"  ! {'; '.join(res.findings)}" if res.findings else ""
            typer.echo(f"{res.saga.qualified_id}: {x}x{y}x{z}, {res.node_count} nodes{note}")
            if not no_preview and res.saga.qualified_id in ids:
                pipeline.write_preview(res)
        for p in tb.written:
            typer.echo(f"  wrote {p.relative_to(r.root)}")
    if check:
        if stale_total:
            for p in stale_total:
                typer.secho(f"stale: {p}", fg="red", err=True)
            raise typer.Exit(EXIT_DRIFT)
        typer.echo("packs are up to date")


@app.command()
@guarded
def preview(
    selector: str,
    out: Annotated[Path | None, typer.Option(help="Write here instead of content/<theme>/<id>/preview.png")] = None,
    size: Annotated[int, typer.Option()] = 1024,
):
    """Render the offline preview sheet."""
    from . import preview as previewmod

    r = repo()
    for saga in r.select(selector):
        res = buildmod.build(saga, voxels.read(saga.vx_path))
        if out:
            previewmod.write(res, out, size)
            typer.echo(str(out))
        else:
            typer.echo(str(pipeline.write_preview(res, size)))


@app.command("lint")
@guarded
def lint_cmd(
    selector: Annotated[str, typer.Argument()] = "all",
    strict: Annotated[bool, typer.Option(help="Warnings about sources become errors")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
):
    """Check licences, attribution, size limits, value budget and core sync."""
    r = repo()
    findings: list[lint.Finding] = []
    chosen = r.select(selector)
    for saga in chosen:
        built = buildmod.build(saga, voxels.read(saga.vx_path)) if saga.vx_path.exists() else None
        findings += lint.check_saga(saga, built, strict=strict)
    findings += lint.check_packs(chosen)
    if selector == "all":
        findings += lint.check_core(r)
    if as_json:
        typer.echo(lint.to_json(findings))
    else:
        for f in findings:
            typer.secho(str(f), fg="red" if f.level == "error" else "yellow")
        typer.echo(f"{len(lint.errors(findings))} error(s), {len(findings) - len(lint.errors(findings))} warning(s)")
    if lint.errors(findings):
        raise typer.Exit(EXIT_LINT)


@app.command("catalog")
@guarded
def catalog_cmd(
    cdb: Annotated[str, typer.Option(help="Print the ContentDB long description of this theme")] = "",
    site: Annotated[Path | None, typer.Option(help="Also write a static gallery site into this folder")] = None,
):
    """Write docs/gallery/ (index.md, catalog.json) and optionally a static site."""
    r = repo()
    results = [buildmod.build(s, voxels.read(s.vx_path)) for s in r.sagas() if s.vx_path.exists()]
    if cdb:
        typer.echo(catalog.cdb_long_description(r.theme(cdb), [x for x in results if x.saga.theme == cdb]))
        return
    if site:
        typer.echo(f"wrote {catalog.write_site(r, results, site)}")
    for p in catalog.write(r, results):
        typer.echo(f"wrote {p.relative_to(r.root)}")


@app.command("package")
@guarded
def package_cmd(
    name: Annotated[str, typer.Argument(help="Mod folder in mods/ (sagas, sagas_ruins, ...) or 'pack' for all")],
    version: Annotated[str, typer.Option(help="Version, used in the zip name")] = "dev",
    out: Annotated[Path, typer.Option(help="Output folder")] = Path("dist"),
):
    """Build a ContentDB release zip (one top-level folder, export-ignore files left out)."""
    from . import package

    r = repo()
    if name == "pack":
        src, folder = r.mods, "sagas_pack"
    else:
        src, folder = r.mods / name, name
        if not (src / "mod.conf").exists():
            raise SagasError(f"no mod named {name} in {r.mods}")
    target = out / f"{folder}-{version}.zip"
    files = package.build_zip(src, target, folder)
    typer.echo(f"{target} ({len(files)} files)")


@app.command("sync-core")
@guarded
def sync_core(check: Annotated[bool, typer.Option(help="Only report differences")] = False):
    """Copy the vocabulary and palette texture into mods/sagas."""
    r = repo()
    if check:
        problems = lint.check_core(r)
        for f in problems:
            typer.secho(str(f), fg="red", err=True)
        raise typer.Exit(EXIT_DRIFT if problems else 0)
    from . import textures

    (r.core_mod / "textures").mkdir(parents=True, exist_ok=True)
    (r.core_mod / "vocabulary.json").write_bytes(vocab.vocabulary_bytes())
    palette.write_png(r.core_mod / "textures" / "sagas_palette.png")
    textures.write_all(r.core_mod / "textures")
    typer.echo("mods/sagas: vocabulary.json, textures/sagas_palette.png and base textures updated")


@app.command("palette")
@guarded
def palette_cmd(
    write: Annotated[bool, typer.Option(help="Regenerate data/palette256.txt (changes every colour saga!)")] = False,
):
    """Check (or regenerate) the 256-colour palette."""
    gen = palette.generate()
    if write:
        from importlib import resources

        target = Path(str(resources.files("sagas").joinpath("data/palette256.txt")))
        palette.write_text(target)
        typer.echo(f"wrote {target}")
        return
    if list(palette.load()) != gen:
        typer.secho("palette256.txt differs from the generator", fg="red", err=True)
        raise typer.Exit(EXIT_DRIFT)
    typer.echo(f"palette ok ({len(gen)} colours, sha256 {palette.sha256()[:12]})")


@app.command()
@guarded
def check(selector: Annotated[str, typer.Argument()] = "all"):
    """Validate saga.toml files (schema only)."""
    r = repo()
    sagas = r.select(selector)
    typer.echo(f"{len(sagas)} saga(s) ok")


scout_app = typer.Typer(help="Find free 3D models for sagas (metadata only; nothing is downloaded).")
app.add_typer(scout_app, name="scout")


@scout_app.callback(invoke_without_command=True)
@guarded
def scout_run(
    ctx: typer.Context,
    theme: Annotated[list[str] | None, typer.Option(help="Theme(s); default all in scout/themes.py")] = None,
    source: Annotated[list[str] | None, typer.Option(help="sketchfab, commons, polyhaven, smithsonian, zeroad")] = None,
    limit: Annotated[int, typer.Option(help="Results per source, theme and search term")] = 6,
    licence: Annotated[str, typer.Option(help="Comma list of cc0, by, by-sa")] = "cc0,by,by-sa",
    refresh: Annotated[bool, typer.Option(help="Ignore the one-day HTTP cache")] = False,
    write: Annotated[bool, typer.Option(help="Write docs/scouting/")] = True,
):
    """Search the sources for every theme and write docs/scouting/."""
    if ctx.invoked_subcommand:
        return
    from .scout import base, report, sources, themes

    r = repo()
    http = base.Http(refresh=refresh)
    lics = [x.strip() for x in licence.split(",") if x.strip()]
    chosen = source or list(sources.SOURCES)
    found: list = []
    for t in theme or list(themes.THEMES):
        terms = themes.THEMES.get(t, [t])
        for src in chosen:
            fn = sources.SOURCES.get(src)
            if not fn:
                raise SagasError(f"unknown source {src}")
            for term in terms if src != "zeroad" else [""]:
                try:
                    for c in fn(http, t, term, limit, lics):
                        c.suggested_site, c.suggested_biomes = themes.suggest(c.title, t)
                        found.append(c)
                except Exception as e:  # one failing source must not stop the others
                    typer.secho(f"{src} '{term}': {e}", fg="yellow", err=True)
    searched = {(src, t) for t in (theme or list(themes.THEMES)) for src in chosen}
    merged = report.merge(r, found, searched=searched)
    typer.echo(f"{len(found)} result(s), {len(merged)} candidate(s) after dedup")
    if write:
        for p in report.write(r, merged):
            typer.echo(f"wrote {p.relative_to(r.root)}")


@scout_app.command("promote")
@guarded
def scout_promote(
    candidate: str,
    theme: Annotated[str, typer.Option(help="Theme (default: the candidate's)")] = "",
    id: Annotated[str, typer.Option(help="Saga id (default: from the title)")] = "",
    force: Annotated[
        bool, typer.Option(help="Promote despite licence-conflict/trademark flags (after checking)")
    ] = False,
):
    """Create content/<theme>/<id>/saga.toml from a scouting candidate."""
    from .scout import promote, report

    r = repo()
    cands = report.load(r)
    if candidate not in cands:
        raise SagasError(f"unknown candidate {candidate} (see docs/scouting/scouting.json)")
    path = promote.promote(r, cands[candidate], theme or None, id or None, force=force)
    config.load(path)
    typer.echo(f"created {path.relative_to(r.root)}: now sagas fetch, voxelize, build")


@scout_app.command("reject")
@guarded
def scout_reject(candidate: str, reason: Annotated[str, typer.Option()]):
    """Hide a candidate from future reports."""
    from .scout import report

    r = repo()
    report.reject(r, candidate, reason)
    report.write(r, report.merge(r, []))
    typer.echo(f"rejected {candidate}")


def main() -> None:
    try:
        app()
    except SagasError as e:  # pragma: no cover
        typer.secho(f"error: {e}", fg="red", err=True)
        sys.exit(e.exit_code if e.exit_code else EXIT_USAGE)
