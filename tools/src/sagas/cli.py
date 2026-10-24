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

app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="Turn 3D models into Luanti landmarks, grouped in sagas."
)
state: dict = {"root": None, "json": False}
# what Saga Forge (forge/) expects of `sagas --json`; raise it when a change would break Forge
FORGE_API = 1


def repo() -> Repo:
    return find_root(state["root"])


def selector_of(landmark: config.Landmark) -> str:
    """How commands name one landmark (<saga>/<id>); JSON output uses it so programs can pass it back."""
    return f"{landmark.saga}/{landmark.id}"


def _plain(value):
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):  # numpy scalars
        return value.item()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def emit_json(data: dict) -> None:
    typer.echo(json.dumps(data, indent=2, default=_plain))


class Report:
    """What a command did: lines for people, and with `sagas --json` one JSON object for programs
    (Saga Forge) instead, printed by `done`."""

    def __init__(self) -> None:
        self.results: list[dict] = []

    def line(self, text: str, record: dict | None = None, color: str | None = None, err: bool = False) -> None:
        if record is not None:
            self.results.append(record)
        if text and not state["json"]:
            typer.secho(text, fg=color, err=err)

    def done(self, **extra) -> None:
        if state["json"]:
            emit_json({**extra, "results": self.results})


def guarded(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SagasError as e:
            if state["json"]:
                emit_json({"error": str(e), "exit_code": e.exit_code})
            else:
                typer.secho(f"error: {e}", fg="red", err=True)
            raise typer.Exit(e.exit_code) from None

    return wrapper


@app.callback()
def main_options(
    root: Annotated[Path | None, typer.Option(help="Repository root (default: search upwards)")] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print one JSON object instead of text (for programs like Saga Forge)")
    ] = False,
):
    state["root"] = root
    state["json"] = as_json


@app.command()
def version():
    """Print the version."""
    if state["json"]:
        emit_json({"version": __version__, "forge_api": FORGE_API})
    else:
        typer.echo(f"sagas {__version__}")


LANDMARK_TEMPLATE = """schema = 1
id = "{id}"
saga = "{saga}"
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
    saga: Annotated[str, typer.Option(help="Saga (content/<saga>/)")],
    title: Annotated[str, typer.Option()] = "",
    url: Annotated[str, typer.Option(help="Where the model can be found")] = "",
    license: Annotated[str, typer.Option(help="SPDX licence of the model")] = "",
    author: Annotated[str, typer.Option()] = "",
    kind: Annotated[str, typer.Option(help="mesh | vox | voxels | handbuilt")] = "mesh",
    file: Annotated[str, typer.Option(help="Source file name (in sources/<id>/ or next to landmark.toml)")] = "",
    member: Annotated[str, typer.Option(help="File inside the archive to load, e.g. scene.gltf")] = "",
    mode: Annotated[str, typer.Option(help="classes | hybrid | palette")] = "classes",
    target_size: Annotated[int, typer.Option(help="Longest side in nodes")] = 48,
    manual: Annotated[bool, typer.Option(help="The model must be downloaded by hand")] = False,
):
    """Scaffold content/<saga>/<id>/landmark.toml."""
    r = repo()
    d = r.content / saga / id
    if (d / "landmark.toml").exists():
        raise SagasError(f"{d / 'landmark.toml'} already exists")
    d.mkdir(parents=True, exist_ok=True)
    text = LANDMARK_TEMPLATE.format(
        id=id,
        saga=saga,
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
    (d / "landmark.toml").write_text(text)
    config.load(d / "landmark.toml")
    typer.echo(f"created {d / 'landmark.toml'}")


@app.command("convert-txt")
@guarded
def convert_txt(
    file: Path,
    saga: Annotated[str, typer.Option()],
    id: Annotated[str, typer.Option(help="Landmark id (default: file name)")] = "",
    title: Annotated[str, typer.Option()] = "",
    license: Annotated[str, typer.Option()] = "",
    author: Annotated[str, typer.Option()] = "",
    url: Annotated[str, typer.Option()] = "",
    mode: Annotated[str, typer.Option(help="classes | hybrid | palette (default: palette if coloured)")] = "",
    force: Annotated[bool, typer.Option(help="Overwrite an existing landmark.toml")] = False,
):
    """Import a voxel point list (x, y, z[, r, g, b] per line, e.g. drububu.com .txt export)."""
    r = repo()
    sid = id or file.stem.lower().replace(" ", "_").replace("-", "_")
    model = legacy.read_txt(file)
    d = r.content / saga / sid
    d.mkdir(parents=True, exist_ok=True)
    toml = d / "landmark.toml"
    if not toml.exists() or force:
        m = mode or ("palette" if model.has_rgb.any() else "classes")
        toml.write_text(
            LANDMARK_TEMPLATE.format(
                id=sid,
                saga=saga,
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
    landmark = config.load(toml)
    voxels.write(model, landmark.vx_path)
    typer.echo(
        f"{landmark.qualified_id}: {model.size[0]}x{model.size[1]}x{model.size[2]}, {model.count} voxels"
        f" -> {landmark.vx_path}"
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
    rep = Report()
    missing = 0
    for landmark in r.select(selector):
        lid, sid = landmark.qualified_id, selector_of(landmark)
        if landmark.source.kind in ("none", "handbuilt"):
            continue
        try:
            path, digest = fetchmod.fetch(landmark, r.sources, src=from_, force=force)
        except SagasError as e:
            missing += 1
            rep.line(f"{lid}: {e}", {"landmark": sid, "status": "missing", "message": str(e)}, "yellow", err=True)
            continue
        for extra_file, _, extra_digest in fetchmod.fetch_extras(landmark, r.sources, force=force):
            recorded = fetchmod.record_extra_sha256(landmark, extra_file, extra_digest)
            note = "sha256 recorded" if recorded else "sha256 ok"
            rep.line(f"{lid}: {extra_file} ({note})")
        if landmark.source.manual:
            note = "manual download, sha256 not recorded"
        elif not landmark.source.sha256:
            fetchmod.record_sha256(landmark, digest)
            note = "sha256 recorded"
        else:
            note = "sha256 ok"
        rep.line(f"{lid}: {path} ({note})", {"landmark": sid, "status": "ok", "path": path, "sha256": digest})
    rep.done()
    if missing:
        raise typer.Exit(4)


@app.command()
@guarded
def inspect(target: str, as_json: Annotated[bool, typer.Option("--json")] = False):
    """Show parts, materials, textures and size of a model file or a landmark's source."""
    from . import load

    r = None
    p = Path(target)
    if not p.is_file():
        r = repo()
        landmark = r.select(target)[0]
        p = pipeline.source_file(landmark, r)
        if landmark.source.member:
            from . import fetch as fetchmod

            p = fetchmod.extract_member(p, landmark.source.member, fetchmod.extract_dir(p, landmark.source.member))
    info = load.inspect(load.load_model(p))
    if as_json or state["json"]:
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
def voxelize(
    selector: Annotated[str, typer.Argument()] = "all",
    force: Annotated[bool, typer.Option()] = False,
    stale: Annotated[
        bool, typer.Option(help="Only where voxels.vx.gz differs from a fresh voxelize; skip missing sources")
    ] = False,
):
    """Source model -> content/<saga>/<id>/voxels.vx.gz."""
    r = repo()
    rep = Report()
    missing = failed = 0
    for landmark in r.select(selector):
        lid, sid = landmark.qualified_id, selector_of(landmark)
        if stale:
            try:
                fresh = pipeline.voxelize(landmark, r)
            except SagasError as e:
                rep.line(f"{lid}: skipped ({e})", {"landmark": sid, "status": "skipped", "message": str(e)})
                continue
            if landmark.vx_path.exists() and pipeline.same_voxels(fresh, voxels.read(landmark.vx_path)):
                rep.line("", {"landmark": sid, "status": "unchanged"})
                continue
            voxels.write(fresh, landmark.vx_path)
            x, y, z = fresh.size
            rep.line(f"{lid}: re-voxelized, {x}x{y}x{z}", {"landmark": sid, "status": "written", "size": fresh.size})
            continue
        if landmark.vx_path.exists() and not force:
            rep.line(f"{lid}: {landmark.vx_path.name} exists (use --force)", {"landmark": sid, "status": "exists"})
            continue
        try:
            model = pipeline.voxelize(landmark, r)
        except SagasError as e:
            if e.exit_code == 4:
                missing += 1
                rep.line(str(e), {"landmark": sid, "status": "missing", "message": str(e)}, "yellow", err=True)
                continue
            raise
        except (ValueError, OSError, KeyError) as e:
            failed += 1
            rep.line(f"{lid}: {e}", {"landmark": sid, "status": "failed", "message": str(e)}, "red", err=True)
            continue
        voxels.write(model, landmark.vx_path)
        x, y, z = model.size
        record = {"landmark": sid, "status": "written", "size": model.size, "voxels": model.count}
        rep.line(f"{lid}: {x}x{y}x{z}, {model.count} voxels", record)
    rep.done()
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
    """voxels.vx.gz -> mods/sagas_<saga>/ (schematics, registry.lua, licences) and previews."""
    r = repo()
    rep = Report()
    written: list[str] = []
    chosen = r.select(selector)
    sagas = sorted({s.saga for s in chosen})
    ids = {s.qualified_id for s in chosen}
    stale_total = []
    for saga in sagas:
        tb = pipeline.build_saga(r, saga, check=check)
        if check:
            stale_total += [f"mods/sagas_{saga}/{p}" for p in tb.stale]
            continue
        for res in tb.results:
            x, y, z = res.size
            note = f"  ! {'; '.join(res.findings)}" if res.findings else ""
            record = {
                "landmark": selector_of(res.landmark),
                "size": res.size,
                "nodes": res.node_count,
                "findings": res.findings,
                "doorway": res.doorway,
                "sealed": res.sealed,
            }
            rep.line(f"{res.landmark.qualified_id}: {x}x{y}x{z}, {res.node_count} nodes{note}", record)
            if res.doorway:
                rep.line(f"  {res.doorway}")
            if res.sealed:
                rep.line("  ! rooms have no door (sagas lint shows a doorway box per side)")
            if not no_preview and res.landmark.qualified_id in ids:
                pipeline.write_preview(res)
        for p in tb.written:
            written.append(str(p.relative_to(r.root)))
            rep.line(f"  wrote {p.relative_to(r.root)}")
    # the screenshot scene (mods/tools/showcase) always lists every landmark
    from . import showcase

    every = [buildmod.build(s, voxels.read(s.vx_path)) for s in r.landmarks() if s.vx_path.exists()]
    for p in showcase.write(r.mods, every, check=check):
        if check:
            stale_total.append(str(p.relative_to(r.root)))
        else:
            written.append(str(p.relative_to(r.root)))
            rep.line(f"  wrote {p.relative_to(r.root)}")
    # the one ContentDB package: the modpack (docs/releasing.md)
    from . import registry

    by_saga = [(s, [x for x in every if x.landmark.saga == s.name]) for s in r.sagas()]
    cdb = registry.modpack_cdb(by_saga)
    cdb_path = r.mods / ".cdb.json"
    if not cdb_path.exists() or cdb_path.read_bytes() != cdb:
        if check:
            stale_total.append(str(cdb_path.relative_to(r.root)))
        else:
            cdb_path.write_bytes(cdb)
            written.append(str(cdb_path.relative_to(r.root)))
            rep.line(f"  wrote {cdb_path.relative_to(r.root)}")
    rep.done(written=written, stale=stale_total)
    if check:
        if stale_total:
            for p in stale_total:
                rep.line(f"stale: {p}", color="red", err=True)
            raise typer.Exit(EXIT_DRIFT)
        rep.line("packs are up to date")


@app.command()
@guarded
def preview(
    selector: str,
    out: Annotated[Path | None, typer.Option(help="Write here instead of content/<saga>/<id>/preview.png")] = None,
    size: Annotated[int, typer.Option()] = 1024,
):
    """Render the offline preview sheet."""
    from . import preview as previewmod

    r = repo()
    for landmark in r.select(selector):
        res = buildmod.build(landmark, voxels.read(landmark.vx_path))
        if out:
            previewmod.write(res, out, size)
            typer.echo(str(out))
        else:
            typer.echo(str(pipeline.write_preview(res, size)))


@app.command()
@guarded
def view(
    target: Annotated[str, typer.Argument(help="One landmark: <saga>/<id>")],
    sizes: Annotated[
        str, typer.Option(help="Sizes to compare, e.g. 16,24,32 (default: 12 to 64 and the current)")
    ] = "",
    out: Annotated[Path | None, typer.Option(help="Page to write (default: .dev/view/<saga>-<id>.html)")] = None,
    png: Annotated[Path | None, typer.Option(help="Also write a still: all sizes at true scale, for agents")] = None,
    games: Annotated[
        list[Path] | None, typer.Option("--games", help="Folder holding Luanti games (repeatable)")
    ] = None,
    open_page: Annotated[
        bool | None, typer.Option("--open/--no-open", help="Open the page (default: when run in a terminal)")
    ] = None,
    serve: Annotated[
        bool, typer.Option("--serve", help="Live mode: a local server builds any size the page asks for")
    ] = False,
    port: Annotated[int, typer.Option(help="Port for --serve (default: any free port)")] = 0,
    stdin_lifetime: Annotated[
        bool, typer.Option("--stdin-lifetime", help="With --serve: stop when stdin closes (for Saga Forge)")
    ] = False,
):
    """Turn and zoom a landmark at several sizes, next to the player, trees and houses of your games."""
    import webbrowser

    from . import viewer

    r = repo()
    chosen = r.select(target)
    if len(chosen) != 1:
        raise SagasError(f"{target!r} selects {len(chosen)} landmarks; name one as <saga>/<id>")
    landmark = chosen[0]
    try:
        wanted = [int(s) for s in sizes.split(",") if s.strip()]
    except ValueError:
        raise SagasError(f"--sizes: expected numbers like 16,24,32, got {sizes!r}") from None
    if any(not 4 <= s <= 400 for s in wanted):
        raise SagasError("--sizes: every size must be between 4 and 400")

    def show(s: viewer.ModelSize) -> None:
        x, y, z = s.vox.dims
        life = f", x{s.life:.1f} life size" if s.life else ""
        mark = "  (landmark.toml)" if s.current else ""
        typer.echo(f"  {s.target:>3}: {x}x{y}x{z}, {s.nodes} nodes{life}{mark}")

    builder = viewer.SizeBuilder(landmark, r, wanted or None)
    results = []
    for size in builder.wanted:
        entry = builder.build(size)
        if entry is not None:
            results.append(entry)
            if not state["json"]:
                show(entry)
    original = viewer.original_data(builder)
    notes, src = builder.notes, builder.src
    refs = viewer.references(games)
    live = serve and builder.any_size
    if serve and not live:
        notes.append("--serve needs the source mesh (sagas fetch): showing the committed size only")
    html = viewer.page(viewer.page_data(landmark, results, refs, list(notes), src, live=live, original=original))
    path = out or viewer.default_path(r, landmark)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    games_found = sorted({ref.group for ref in refs if ref.group and ref.group != "generic"})
    rep = Report()
    rep.line(f"  compare with: {', '.join(games_found) if games_found else 'stand-in trees (no game found; --games)'}")
    for n in notes:
        rep.line(f"  ! {n}", color="yellow")
    if png:
        rep.line(str(viewer.still(results, refs, png)))
    should_open = open_page if open_page is not None else sys.stdout.isatty() and not state["json"]
    info = {
        "landmark": selector_of(landmark),
        "page": path,
        "sizes": [s.target for s in results],
        "current": builder.current,
        "notes": notes,
        "games": games_found,
        "live": live,
        "original": original is not None,
    }
    if not serve:
        rep.line(str(path))
        rep.done(**info)
        if should_open:
            webbrowser.open(path.resolve().as_uri())
        return

    def ready(url: str) -> None:
        if state["json"]:  # one line, so a parent can read it before the server's first request
            typer.echo(json.dumps({**info, "page": str(path), "url": url}))
            sys.stdout.flush()
        else:
            typer.echo(f"live at {url} (any size on request; Ctrl-C to stop)")
        if should_open:
            webbrowser.open(url)

    viewer.serve(builder, html, port, ready, stdin_lifetime)


def _one(r: Repo, target: str) -> config.Landmark:
    chosen = r.select(target)
    if len(chosen) != 1:
        raise SagasError(f"{target!r} selects {len(chosen)} landmarks; name one as <saga>/<id>")
    return chosen[0]


def _rebuild(r: Repo, landmark: config.Landmark) -> buildmod.BuildResult:
    model = pipeline.voxelize(landmark, r)
    voxels.write(model, landmark.vx_path)
    res = buildmod.build(landmark, model)
    pipeline.write_preview(res)
    return res


@app.command("set")
@guarded
def set_cmd(
    target: Annotated[str, typer.Argument(help="One landmark: <saga>/<id>")],
    assignments: Annotated[list[str], typer.Argument(help="key=value, e.g. transform.target_size=24")],
):
    """Change landmark.toml fields (comments are kept); the result is validated, or nothing changes."""
    from . import edit

    landmark = _one(repo(), target)
    values = {}
    for a in assignments:
        key, sep, value = a.partition("=")
        if not sep:
            raise SagasError(f"expected key=value, got {a!r}")
        values[key.strip()] = edit.parse_value(value.strip())
    edit.set_values(landmark.path, values)
    if state["json"]:
        emit_json({"landmark": selector_of(landmark), "path": landmark.path, "values": values})
    else:
        typer.echo(f"{landmark.path}: " + ", ".join(f"{k} = {v!r}" for k, v in values.items()))


@app.command("command")
@guarded
def command_cmd(
    target: Annotated[str, typer.Argument(help="One landmark: <saga>/<id>")],
    lines: Annotated[list[str], typer.Argument(help='Commands like "/size 24" "/site cliff+coast"')],
    rebuild: Annotated[bool, typer.Option(help="Voxelize, build and write preview.png afterwards")] = True,
):
    """Apply the contribution bot's comment commands to a landmark (see `sagas command x /help`)."""
    from . import edit

    r = repo()
    landmark = _one(r, target)
    if any(line.strip() in ("/help", "help") for line in lines):
        emit_json({"help": edit.HELP}) if state["json"] else typer.echo(edit.HELP)
        return
    done = []
    for line in lines:
        values, what = edit.command(landmark, line)
        if values:
            landmark = edit.set_values(landmark.path, values)
        facing = line.split()[1] if line.startswith("/door") and len(line.split()) > 1 else ""
        if facing in edit.FACINGS:
            res = buildmod.build(landmark, pipeline.voxelize(landmark, r))
            box = edit.door_opening(res.suggestions, facing)
            landmark = edit.set_values(landmark.path, {"voxel.openings": [*landmark.voxel.openings, box]})
        done.append(what)
    result: dict = {"landmark": selector_of(landmark), "done": list(done)}
    if rebuild:
        res = _rebuild(r, landmark)
        x, y, z = res.size
        done.append(f"now {x}x{y}x{z}, {res.node_count} nodes" + (", rooms still without a door" if res.sealed else ""))
        result.update(size=res.size, nodes=res.node_count, sealed=res.sealed)
    emit_json(result) if state["json"] else typer.echo("; ".join(done))


@app.command()
@guarded
def intake(
    issue: Annotated[Path, typer.Argument(help="Issue as JSON (gh issue view N --json number,title,body,author)")],
    summary: Annotated[Path | None, typer.Option(help="Write the result as JSON here")] = None,
):
    """Turn a "Model found" issue into content/<saga>/<id>/ (landmark.toml, voxels, preview)."""
    from . import intake as intakemod

    data = json.loads(issue.read_text(encoding="utf-8"))
    author = (data.get("author") or {}).get("login", "")
    result = intakemod.run(repo(), int(data["number"]), data.get("title", ""), data.get("body", ""), author)
    out = json.dumps(result.__dict__, indent=2)
    if summary:
        summary.write_text(out + "\n", encoding="utf-8")
    typer.echo(out)


@app.command()
@guarded
def add(
    request: Annotated[Path, typer.Argument(help="The new landmark as JSON (fields: sagas.intake.Request)")],
):
    """Create a landmark from a request (Saga Forge): landmark.toml, the kept original, voxels, preview."""
    from . import intake as intakemod

    try:
        data = json.loads(request.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SagasError(f"{request}: {e}") from None
    if not isinstance(data, dict):
        raise SagasError(f"{request}: expected a JSON object")
    result = intakemod.create_landmark(repo(), intakemod.Request.from_json(data))
    if state["json"]:
        emit_json(result.__dict__)
        return
    x, y, z = result.dims
    typer.echo(f"created {result.path}: {x}x{y}x{z}, {result.nodes} nodes")
    for f in result.files:
        typer.echo(f"  {f}")
    for n in result.notes:
        typer.secho(f"  ! {n}", fg="yellow")


@app.command("hints")
def hints_cmd(text: Annotated[str, typer.Argument(help='e.g. "on sea cliffs in the cold north, rare"')]):
    """Placement fields for a description in your own words."""
    from . import hints

    p = hints.suggest(text)
    if state["json"]:
        emit_json({"fields": p.fields(), "matched": p.matched})
        return
    for k, v in p.fields().items():
        typer.echo(f"{k} = {json.dumps(v)}")
    if p.matched:
        typer.echo(f"# from: {', '.join(p.matched)}")


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
    for landmark in chosen:
        built = buildmod.build(landmark, voxels.read(landmark.vx_path)) if landmark.vx_path.exists() else None
        findings += lint.check_saga(landmark, built, strict=strict)
    findings += lint.check_packs(chosen)
    if selector == "all":
        findings += lint.check_core(r)
    if as_json or state["json"]:
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
    cdb: Annotated[str, typer.Option(help="Print the ContentDB long description of this saga")] = "",
    site: Annotated[Path | None, typer.Option(help="Also write a static gallery site into this folder")] = None,
):
    """Write docs/gallery/ (index.md, catalog.json) and optionally a static site."""
    r = repo()
    results = [buildmod.build(s, voxels.read(s.vx_path)) for s in r.landmarks() if s.vx_path.exists()]
    if cdb:
        typer.echo(catalog.cdb_long_description(r.saga(cdb), [x for x in results if x.landmark.saga == cdb]))
        return
    if state["json"]:  # read only: the sagas and their landmarks, paths relative to the repository root
        sagas = [
            {"id": t.name, "title": t.title, "description": t.description, "supported_games": t.supported_games}
            for t in r.sagas()
        ]
        ordered = sorted(results, key=lambda x: x.landmark.qualified_id)
        cards = [
            {
                **catalog.card(x, r, r.root),
                "selector": selector_of(x.landmark),
                "target_size": x.landmark.transform.target_size,
                "real_size": x.landmark.transform.real_size,
                "edited": x.landmark.source.edited,
                "manual": x.landmark.source.manual,
            }
            for x in ordered
        ]
        unbuilt = [selector_of(s) for s in r.landmarks() if not s.vx_path.exists()]
        emit_json({"sagas": sagas, "landmarks": cards, "unbuilt": unbuilt})
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
        src, folder = r.mods, package.modpack_name(r.mods)
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
    write: Annotated[
        bool, typer.Option(help="Regenerate data/palette256.txt (changes every colour landmark!)")
    ] = False,
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
    """Validate landmark.toml files (schema only)."""
    r = repo()
    chosen = r.select(selector)
    typer.echo(f"{len(chosen)} landmark(s) ok")


scout_app = typer.Typer(help="Find free 3D models for landmarks (metadata only; nothing is downloaded).")
app.add_typer(scout_app, name="scout")


@scout_app.callback(invoke_without_command=True)
@guarded
def scout_run(
    ctx: typer.Context,
    saga: Annotated[list[str] | None, typer.Option(help="Saga(s); default all in scout/sagas.py")] = None,
    source: Annotated[list[str] | None, typer.Option(help="sketchfab, commons, polyhaven, smithsonian, zeroad")] = None,
    limit: Annotated[int, typer.Option(help="Results per source, saga and search term")] = 6,
    licence: Annotated[str, typer.Option(help="Comma list of cc0, by, by-sa")] = "cc0,by,by-sa",
    refresh: Annotated[bool, typer.Option(help="Ignore the one-day HTTP cache")] = False,
    write: Annotated[bool, typer.Option(help="Write docs/scouting/")] = True,
):
    """Search the sources for every saga and write docs/scouting/."""
    if ctx.invoked_subcommand:
        return
    from .scout import base, report, sagas, sources

    r = repo()
    http = base.Http(refresh=refresh)
    lics = [x.strip() for x in licence.split(",") if x.strip()]
    chosen = source or list(sources.SOURCES)
    found: list = []
    for t in saga or list(sagas.SAGAS):
        terms = sagas.SAGAS.get(t, [t])
        for src in chosen:
            fn = sources.SOURCES.get(src)
            if not fn:
                raise SagasError(f"unknown source {src}")
            for term in terms if src != "zeroad" else [""]:
                try:
                    for c in fn(http, t, term, limit, lics):
                        c.suggested_site, c.suggested_biomes = sagas.suggest(c.title, t)
                        found.append(c)
                except Exception as e:  # one failing source must not stop the others
                    typer.secho(f"{src} '{term}': {e}", fg="yellow", err=True)
    searched = {(src, t) for t in (saga or list(sagas.SAGAS)) for src in chosen}
    merged = report.merge(r, found, searched=searched)
    typer.echo(f"{len(found)} result(s), {len(merged)} candidate(s) after dedup")
    if write:
        for p in report.write(r, merged):
            typer.echo(f"wrote {p.relative_to(r.root)}")


@scout_app.command("promote")
@guarded
def scout_promote(
    candidate: str,
    saga: Annotated[str, typer.Option(help="Saga (default: the candidate's)")] = "",
    id: Annotated[str, typer.Option(help="Landmark id (default: from the title)")] = "",
    force: Annotated[
        bool, typer.Option(help="Promote despite licence-conflict/trademark flags (after checking)")
    ] = False,
):
    """Create content/<saga>/<id>/landmark.toml from a scouting candidate."""
    from .scout import promote, report

    r = repo()
    cands = report.load(r)
    if candidate not in cands:
        raise SagasError(f"unknown candidate {candidate} (see docs/scouting/scouting.json)")
    path = promote.promote(r, cands[candidate], saga or None, id or None, force=force)
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
