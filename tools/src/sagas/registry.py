"""Generate a content pack mod (`mods/sagas_<theme>/`) from built sagas."""

from __future__ import annotations

import json
from pathlib import Path

from . import __version__, schematic
from .build import BuildResult
from .config import LICENSE_ALLOWLIST, SHARE_ALIKE
from .repo import Theme

MIN_ENGINE = "5.10"

LICENSE_URLS = {
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC-BY-3.0": "https://creativecommons.org/licenses/by/3.0/",
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-SA-3.0": "https://creativecommons.org/licenses/by-sa/3.0/",
    "CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "MIT": "https://opensource.org/license/mit",
}

MIT_TEXT = """Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def lua_str(s: str) -> str:
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif o < 32 or o == 127:
            out.append(f"\\{o:03d}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def lua_list(items: list[str]) -> str:
    return "{" + ", ".join(lua_str(i) for i in items) + "}"


def pack_media_license(licenses: list[str]) -> str:
    """The single media licence for a pack: the most restrictive of its sagas' licences."""
    for lic in licenses:
        if lic not in LICENSE_ALLOWLIST:
            raise ValueError(f"licence {lic!r} not allowed")
    used = set(licenses)
    sa = used & set(SHARE_ALIKE)
    if sa:  # BY-SA 3.0 adaptations may be licensed under 4.0 (section 4b), so a mix becomes 4.0
        return "CC-BY-SA-3.0" if sa == {"CC-BY-SA-3.0"} else "CC-BY-SA-4.0"
    by = used & {"CC-BY-3.0", "CC-BY-4.0", "MIT"}
    if by == {"MIT"}:
        return "MIT"
    if by:
        return "CC-BY-3.0" if by == {"CC-BY-3.0"} else "CC-BY-4.0"
    return "CC0-1.0"


def registry_entry(res: BuildResult) -> str:
    s, p, m = res.saga, res.saga.placement, res.saga.materials
    x, y, z = res.size
    ax, ay, az = res.anchor
    classes = sorted(res.classified.class_counts())
    over = ", ".join(f"{k} = {lua_str(v)}" for k, v in sorted(m.overrides.items()))
    lines = [
        "sagas.register({",
        f"\tid = {lua_str(s.qualified_id)},",
        f"\ttitle = {lua_str(s.title)},",
        f'\tschematic = P .. "{s.id}.mts",',
        f"\tsize = {{x = {x}, y = {y}, z = {z}}},",
        f"\tanchor = {{x = {ax}, y = {ay}, z = {az}}},",
        f"\tsite = {lua_list(p.site)},",
        f"\texposure = {lua_str(p.exposure)},",
        f"\tbiomes = {lua_list(p.biomes)},",
        f"\trarity = {p.rarity},",
        f"\ty_min = {p.y_min},",
        f"\ty_max = {p.y_max},",
        f"\trotation = {lua_str(p.rotation)},",
        f"\tfoundation = {p.foundation},",
        f"\tclear_above = {str(p.clear_above).lower()},",
        f"\tlarge = {str(p.large).lower()},",
        f"\tmin_distance = {p.min_distance},",
        f"\tmaterials = {{context = {lua_str(m.context)}, overrides = {{{over}}}}},",
        f"\tclasses = {lua_list(classes)},",
        f"\tcolor_nodes = {res.classified.color_count},",
        f"\tnodes = {res.node_count},",
        f"\ttags = {lua_list(s.tags)},",
        f"\tlore = {lua_str(s.lore)},",
        f"\thints = {lua_str(p.hints)},",
        f"\tauthor = {lua_str(s.source.author)},",
        f"\tlicense = {lua_str(s.source.license)},",
        f"\tsource_url = {lua_str(s.source.url)},",
        "})",
    ]
    return "\n".join(lines)


def pack_files(theme: Theme, results: list[BuildResult], owner: str = "culmat") -> dict[str, bytes]:
    """All files of the pack, path relative to the pack dir -> content. Deterministic."""
    results = sorted(results, key=lambda r: r.saga.id)
    licenses = [r.saga.source.license for r in results if r.saga.source.license]
    media = pack_media_license(licenses)
    ai = "GENERATED" if any(r.saga.source.ai == "generated" for r in results) else "ASSISTED"
    files: dict[str, bytes] = {}
    files["mod.conf"] = (
        f"name = {theme.pack}\n"
        f"title = {theme.title}\n"
        f"description = {theme.description}\n"
        "depends = sagas\n"
        f"supported_games = {theme.supported_games}\n"
        f"min_minetest_version = {MIN_ENGINE}\n"
    ).encode()
    files["init.lua"] = (
        f"-- {theme.title}: generated by `sagas build` (luanti-sagas). Edit content/{theme.name}/, not this file.\n"
        'dofile(core.get_modpath(core.get_current_modname()) .. "/registry.lua")\n'
    ).encode()
    body = [
        f"-- Generated by `sagas build` (luanti-sagas {__version__}) from content/{theme.name}/*/saga.toml.",
        "-- Do not edit: change the saga.toml files and rebuild.",
        'local P = core.get_modpath(core.get_current_modname()) .. "/schematics/"',
        "",
    ]
    for r in results:
        body.append(registry_entry(r))
        body.append("")
        files[f"schematics/{r.saga.id}.mts"] = schematic.to_mts(r.grid)
    files["registry.lua"] = "\n".join(body).encode()
    files["ATTRIBUTION.md"] = attribution_md(theme, results).encode()
    files["LICENSE"] = license_text(theme, results, media).encode()
    files["README.md"] = readme(theme, results, media).encode()
    files[".cdb.json"] = (
        json.dumps(
            {
                "type": "MOD",
                "title": theme.title,
                "short_description": theme.description[:200],
                "license": "MIT",
                "media_license": media,
                "ai_disclosure": ai,
                "dev_state": "WIP",
                "tags": ["mapgen", "decorative"],
                "long_description": long_description(theme, results),
                "repo": f"https://github.com/{owner}/luanti-sagas",
                "issue_tracker": f"https://github.com/{owner}/luanti-sagas/issues",
            },
            indent="\t",
        )
        + "\n"
    ).encode()
    return files


def long_description(theme: Theme, results: list[BuildResult]) -> str:
    lines = [
        theme.description,
        "",
        "Requires the **sagas** mod, which places these landmarks during map generation",
        "where their site fits and builds them from the materials of the game and the site.",
        "",
        "| Saga | Size | Where |",
        "|---|---|---|",
    ]
    for r in results:
        x, y, z = r.size
        lines.append(f"| {r.saga.title} | {x} x {y} x {z} | {' or '.join(r.saga.placement.site)} |")
    lines += ["", "Every schematic is an adaptation of a freely licensed model; see ATTRIBUTION.md for sources."]
    return "\n".join(lines)


def attribution_md(theme: Theme, results: list[BuildResult]) -> str:
    lines = [
        f"# Attribution: {theme.title}",
        "",
        "Every schematic in `schematics/` is a voxelized adaptation of the source listed here, made with",
        "luanti-sagas (scaled, voxelized, colours mapped to a 256-colour palette or to material classes).",
        "",
        "| Schematic | Title | Author | Source | Licence |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        s = r.saga.source
        src = f"[link]({s.url})" if s.url else "-"
        author = f"[{s.author}]({s.author_url})" if s.author_url else (s.author or "-")
        lic = f"[{s.license}]({LICENSE_URLS.get(s.license, '')})" if s.license else "-"
        lines.append(f"| `{r.saga.id}.mts` | {r.saga.title} | {author} | {src} | {lic} |")
    if any(r.saga.source.ai != "none" for r in results):
        lines += ["", "## AI disclosure", ""]
        for r in results:
            if r.saga.source.ai != "none":
                src = r.saga.source
                lines.append(f"- `{r.saga.id}.mts`: source model is {src.ai} with AI ({src.notes}).")
    return "\n".join(lines) + "\n"


def license_text(theme: Theme, results: list[BuildResult], media: str) -> str:
    year = int(theme.extra.get("copyright_year", 2026))  # fixed, so builds are reproducible
    lines = [
        theme.title,
        f"Copyright (C) {year} Matthias Cullmann and contributors",
        "",
        "== Code (init.lua, registry.lua) ==",
        "",
        "SPDX-License-Identifier: MIT",
        "",
        MIT_TEXT,
        "== Media (schematics/*.mts) ==",
        "",
        f"SPDX-License-Identifier: {media}",
        "Each schematic is an adaptation of the work listed below and is licensed under that work's",
        f"licence; the pack as a whole is distributed under {media} ({LICENSE_URLS.get(media, '')}).",
        "",
        "Attribution (file, title, author, licence, source):",
    ]
    for r in results:
        s = r.saga.source
        lines.append(
            f'- schematics/{r.saga.id}.mts: "{r.saga.title}" by {s.author or "unknown"}, '
            f"{s.license}, {s.url or 'no URL'}. Changes: voxelized and recoloured with luanti-sagas."
        )
    lines += ["", "== AI-generated assets ==", ""]
    ai = [r for r in results if r.saga.source.ai == "generated"]
    if ai:
        lines += [f"- schematics/{r.saga.id}.mts: source model generated with {r.saga.source.notes}" for r in ai]
    else:
        lines.append("None. The tooling and this pack's code were written with AI assistance.")
    return "\n".join(lines) + "\n"


def readme(theme: Theme, results: list[BuildResult], media: str) -> str:
    lines = [
        f"# {theme.title}",
        "",
        theme.description,
        "",
        "A content pack for the [sagas](../sagas) mod. Generated by `sagas build`; edit",
        f"`content/{theme.name}/` in the [luanti-sagas](https://github.com/culmat/luanti-sagas) repository instead.",
        "",
        "| Saga | Size | Site | Biomes | Rarity |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        x, y, z = r.size
        p = r.saga.placement
        lines.append(
            f"| {r.saga.title} (`{r.saga.qualified_id}`) | {x}x{y}x{z} | {', '.join(p.site)} | "
            f"{', '.join(p.biomes)} | 1 per {p.rarity} chunks |"
        )
    lines += ["", f"Code: MIT. Media: {media}. See [LICENSE](LICENSE) and [ATTRIBUTION.md](ATTRIBUTION.md)."]
    return "\n".join(lines) + "\n"


def write_pack(theme: Theme, results: list[BuildResult], out: Path) -> list[Path]:
    files = pack_files(theme, results)
    written = []
    if (out / "schematics").is_dir():
        keep = {Path(k).name for k in files if k.startswith("schematics/")}
        for old in (out / "schematics").glob("*.mts"):
            if old.name not in keep:
                old.unlink()
    for rel, data in files.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists() or p.read_bytes() != data:
            p.write_bytes(data)
            written.append(p)
    return written


def diff_pack(theme: Theme, results: list[BuildResult], out: Path) -> list[str]:
    """Paths (relative) whose committed content differs from a fresh build."""
    files = pack_files(theme, results)
    stale = [rel for rel, data in files.items() if not (out / rel).exists() or (out / rel).read_bytes() != data]
    if (out / "schematics").is_dir():
        keep = {k for k in files if k.startswith("schematics/")}
        stale += [
            f"schematics/{p.name} (orphan)"
            for p in (out / "schematics").glob("*.mts")
            if f"schematics/{p.name}" not in keep
        ]
    return sorted(stale)
