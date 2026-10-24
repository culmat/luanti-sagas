# Contributing with the tools on your computer

For people who like a terminal, want to try a landmark in the game before sharing it, or work with a
coding agent. The browser route in [CONTRIBUTING.md](../CONTRIBUTING.md) needs none of this.

## Set up

You need git, Python 3.12 or newer and [uv](https://docs.astral.sh/uv/). No Blender.

```sh
git clone https://github.com/culmat/luanti-sagas
cd luanti-sagas
uv sync --project tools
alias sagas="uv run --project tools sagas"     # or prefix every command below with it
```

To try landmarks in the game, install [avanti-luanti](https://github.com/culmat/avanti-luanti)
(it starts Luanti with your working copy) and the games you want to test (Minetest Game, Mineclonia,
VoxeLibre).

## Add a landmark

1. **Start it**, from a link:
   ```sh
   sagas new watchtower --saga medieval --url https://sketchfab.com/3d-models/... \
       --license CC-BY-4.0 --author "Jane Doe" --file watchtower.zip --member scene.gltf --manual
   ```
   or from a candidate in [scouting/](scouting/): `sagas scout promote <id>`. A new saga is a new
   folder `content/<saga>/` with a `saga.toml` (`title`, `description`).
2. **Get the model**: `sagas fetch medieval/watchtower` downloads it into `sources/`, which is never
   committed; `source.url` and `source.sha256` keep the original reachable. For sites that need a
   login, download it yourself and copy it next to `landmark.toml`: the original stays in the
   repository (up to 50 MB), so the landmark can always be rebuilt and reworked.
3. **Look inside**: `sagas inspect medieval/watchtower` shows parts, materials, textures and size.
4. **Voxelize and look**: `sagas voxelize medieval/watchtower --force`, then
   `sagas view medieval/watchtower --serve` opens the landmark in 3D next to a player and your games'
   trees. Try sizes with -/+ and press M to compare with the model.
5. **Tune `landmark.toml`**: size, up axis, material rules, placement. The guide that explains every
   decision is [authoring-landmarks.md](authoring-landmarks.md); all fields are in
   [pipeline.md](pipeline.md). `sagas hints "on sea cliffs in the cold north, rare"` suggests placement
   fields for your words, and `sagas set medieval/watchtower transform.target_size=24` changes a field.
6. **Check**: `sagas lint medieval/watchtower`.
7. **Share it**: commit `landmark.toml`, `voxels.vx.gz`, `preview.png` and a kept original, push to your fork and open a
   pull request. You don't need to commit the packs in `mods/`: CI rebuilds them, posts pictures in the
   pull request, and after a maintainer's approval it is merged and released by itself
   ([releasing.md](releasing.md)).

Fixing the model itself (closing a hole, removing a stand) is fine: save the result next to
`landmark.toml` under a new name and set `source.edited` to it. The original stays as it is, `sagas
view` shows both (press O), and the attribution notes the change.

## For programs

`sagas --json <command>` prints one JSON object instead of text (fetch, voxelize, build, set, command,
hints, lint, catalog, view, version); errors come as `{"error": ..., "exit_code": ...}`.
`sagas add request.json` creates a landmark in one step from the fields of `sagas.intake.Request`
(title, url, file, license, author, saga or new_saga, size, hints, lore), the same way the issue bot
does. `sagas view --serve --stdin-lifetime` stops when its stdin closes. [Saga Forge](saga-forge.md)
uses these; `sagaforge --folder .` runs it on your clone.

## Try it in the game

```sh
avanti play mods --game minetest        # or mineclonia, mineclone2
```

This opens Luanti in a creative world that loads `mods/` from your checkout, with every privilege.
Point at the ground and run `/saga place watchtower`. `/saga find watchtower` generates fresh map
around you until map generation places it, then takes you there; `/saga tour watchtower` circles it.
Luanti has no hot reload: after `sagas build` or a code change, quit and run the command again.

## Build in the game

Build it in a creative world, mark it with `/saga mark` and export it with `/saga export <name>`.
Copy the `.mts` from `<world>/sagas/` next to a new `landmark.toml` with `kind = "handbuilt"` and
`file = "<name>.mts"`, and license it yourself (CC0 or CC-BY-SA-4.0). The tools map the game's nodes
back to material classes, so the build adapts to every game; `sagas voxelize` lists nodes it could not
map, and a rule such as `match = { part = "mymod:roof_tile" }` with `class = "roof_red"` fixes them.

Voxel files work too: a MagicaVoxel `.vox` (`kind = "vox"`) or a point list `x, y, z[, r, g, b]`
(`kind = "voxels"`, e.g. from drububu.com: `sagas convert-txt`).

## With a coding agent

The repository is set up for coding agents ([AGENTS.md](../AGENTS.md)). Say "add this model as a
landmark: <link>" and describe where it belongs; the agent follows
[authoring-landmarks.md](authoring-landmarks.md), shows you the `sagas view` page to decide the size,
and prepares the pull request. You decide; it types.

## Code

- Tools: `cd tools && uv run pytest && uv run ruff check . && uv run ruff format --check .`
- Mod: `luacheck mods`, `stylua --check mods/sagas`, and `avanti test mods` for the headless game tests.
- Balance: `avanti survey mods --game minetest --set sagas_survey=true --keep` reports how often each
  landmark appears and where; `/saga tour` in the kept world shows them
  ([placement.md](placement.md#testing-a-placement)).
- The vocabulary (classes, sites, biome tags) lives in `tools/src/sagas/data/vocabulary.json`; run
  `sagas sync-core` after changing it.
- Workflows: [releasing.md](releasing.md) describes how pull requests become releases.
