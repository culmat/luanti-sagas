# luanti-sagas: notes for coding agents

Read by any coding agent working in this repository (Claude Code reads it through CLAUDE.md).

Landmarks from free 3D models for Luanti, grouped in sagas (themes). Python tools turn models into
schematics; the `sagas` mod places them. Terms: `docs/glossary.md` (a saga is a theme such as ruins
or vikings; a landmark is one structure). To create or change a landmark, follow
`docs/authoring-landmarks.md`.

## Layout

| Path | What |
|---|---|
| `tools/` | Python package `sagas` (uv). CLI: `uv run --project tools sagas ...` |
| `tools/src/sagas/data/vocabulary.json` | Classes, site primitives, biome tags: the contract with the mod |
| `content/<saga>/<id>/` | `landmark.toml` (source of truth), `voxels.vx.gz`, `preview.png` |
| `mods/sagas/` | Core mod (Lua): materials, sites, engine, large landmarks, commands, tour |
| `mods/sagas_<saga>/` | Generated packs: never edit by hand, run `sagas build` |
| `mods/tools/` | Development-only mods, export-ignored from releases: `showcase` (screenshots), `survey` (bridge to `avanti survey`) |
| `forge/` | Saga Forge, the contributor app (Go); its own notes in `forge/AGENTS.md` |
| `docs/` | Pipeline, placement, materials, sources, scouting reports, gallery |

## Conventions

- Builds are deterministic. Contributors commit `landmark.toml`, voxels and previews; CI rebuilds the
  packs and `deliver.yml` commits and releases them after each merge (`docs/releasing.md`). Browser
  contributions go issue form -> `sagas intake` -> PR -> comment commands (`sagas command`).
- After editing `vocabulary.json` or the palette: `sagas sync-core` (CI checks it).
- Lua: luacheck clean (`luacheck mods`), stylua formatted (`stylua mods/sagas`), engine API only, every game
  node name inside the guarded tables in `mods/sagas/materials/`. Verify API names in
  `~/.avanti/corpus/engine/doc/lua_api.md`.
- Python: `uv run ruff check . && uv run ruff format --check . && uv run pytest` in `tools/`.
- In-engine tests: `avanti test mods` (Minetest Game, Mineclonia, VoxeLibre).
- Placement balance: `avanti survey mods --game minetest --set sagas_survey=true` (headless, about
  4 minutes for the default 1800 mapchunks). Check SV findings after changing rarity, sites, biomes or
  the engine. `mods/tools/survey` is the bridge; like `mods/tools/showcase` it is never released.
- Visiting placements needs the Luanti window (`avanti play ... --world <kept survey world>`, then
  `/saga tour`): ask the maintainer first, it takes over their screen.
- Size and detail: `sagas view <saga>/<id> --no-open --png <file>` writes the 3D page for the person and
  a still for you (all sizes at true scale next to the games' trees). Opening the page is the person's call.
- Test fixtures for the mod are generated: `SAGAS_WRITE_FIXTURES=1 uv run pytest tests/test_core_fixtures.py`.

## Rules

- Only free licences (CC0, CC-BY, CC-BY-SA, MIT); `sagas lint` enforces the rest.
- Never commit downloaded models (`sources/` is ignored).
- Never publish anything (ContentDB, forum, upstream issues or PRs, tags that trigger releases) without the
  maintainer's explicit approval. Releases go through the `contentdb` environment approval.
- AI-generated models must be declared (`source.ai`).
