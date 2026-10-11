---
name: saga-author
description: Create or improve a saga in luanti-sagas - find a free model, write saga.toml from the contributor's own words (where it belongs, what it is made of), fetch, voxelize, build, read the preview, tune material rules and pass sagas lint. Use for "add this model as a saga", "make a saga from ...", "where should this castle appear", "the preview looks wrong", or any edit of content/<theme>/<id>/saga.toml.
---

# Authoring a saga

A saga is a free 3D model turned into a Luanti schematic. Creators describe **where** it belongs and
**what** it is made of; the `sagas` mod places it and picks the game's materials. Reference:
`docs/pipeline.md` (all saga.toml fields), `docs/placement.md`, `docs/materials.md`, `docs/sources.md`.

Run the CLI as `uv run --project tools sagas ...` from the repository root.

## 1. The model and its licence

- Accept only CC0, CC-BY, CC-BY-SA or MIT. Never NC or ND, never film or game characters, never
  marketplace or 3D Warehouse models. If the licence is unclear, stop and tell the user why.
- Candidates: `docs/scouting/<theme>.md`; `sagas scout promote <id> --theme <theme> --id <id>` writes the
  saga.toml. Otherwise `sagas new <id> --theme <theme> --url ... --license ... --author ...`.
- Sketchfab needs a login: `manual = true`, `member = "scene.gltf"`, the user downloads the glTF zip and
  runs `sagas fetch <theme>/<id> --from <zip>`.
- CC-BY-SA sources belong in a share-alike theme (like `antiquity`); `sagas lint` warns when a theme mixes.

## 2. From the creator's words to [placement]

| They say | Field |
|---|---|
| hilltop, summit, overlooking the land | `site = ["peak"]` (or `"ridge"`) |
| on a cliff, at the edge of a drop | `"cliff"`; sea cliff: `"cliff+coast"` |
| by the sea, harbour, shore | `"coast"`, biomes may include `"beach"` |
| by a river, bridge, ford | `"plain+river"` or `"river"` |
| lake, pond | `"lake"`; near a waterfall: `"waterfall"` |
| flat field, meadow, village | `"plain"`; hillside: `"slope"` |
| sunken, wreck, sea floor | `"underwater"` |
| in a cave, on the cave floor | `"cave_floor"`, hanging from it: `"cave_ceiling"`; set `y_max = -20` |
| carved into the mountain, dwarven halls | `"carve"`, `y_max` below the surface (e.g. -20) |
| on floating islands | `"floatland"` |
| a landmark, visible from afar, watching over | `exposure = "prominent"` |
| hidden, secret, deep in the forest, in a valley | `exposure = "hidden"` |
| common / rare / very rare, unique | `rarity` about 120 / 600 / 3000+ |
| deserts, jungles, cold north, mountains | `biomes = ["desert"]`, `["jungle"]`, `["tundra", "snow", "taiga"]`, `["mountain"]` |

List alternatives in order of preference: `site = ["cliff+coast", "cliff+river", "waterfall"]`.
Always copy the creator's sentence into `hints`.

## 3. What it is made of: [materials]

- Buildings, ships, anything a player would mine: `mode = "classes"`, `context = "surroundings"`
  (stone and wood follow the site). Statues, creatures, painted things: `mode = "palette"` or `"hybrid"`.
- "always white marble", "red roofs everywhere": `overrides = { stone = "marble" }`, `{ roof_red = "fixed" }`.
- Rules, first match wins (`match` keys: `material` and `part` globs, `color` + `tol`, `y`, `y_frac`, `normal`):
  - Textured kits (DAE, glTF with named textures): match texture names, e.g. `material = "*brick*"` -> `stone`,
    `"*mossy*"` -> `moss`, `"*wood*"` -> `wood`, `"*vine*"` -> `leaves`. `sagas inspect` lists the names.
  - Scans and atlases: structure first (`y_frac = [0.7, 1.0], normal = "up"` -> roof; `y = [0, 1]` -> plinth),
    then a few colour rules with small tolerances (10-25).
  - STL (no colour): height and normal rules only.
  - 0 A.D. art: `extra_files` with the actor's baseTex, `voxel.texture`, `voxel.alpha = "ignore"`.
- Gold and emerald need `value_budget = { gold = N }` with N at most 64; keep it to details like eyes.

## 4. Build and look

```sh
sagas fetch <theme>/<id>
sagas inspect <theme>/<id>          # parts, materials, textures, extents, up axis
sagas voxelize <theme>/<id> --force
sagas build <theme>                 # writes mods/sagas_<theme>/ and content/<theme>/<id>/preview.png
```

Read `preview.png` (top, front, side, isometric) and fix:

| Looks like | Fix |
|---|---|
| lying on its side | `transform.up = "z"` (or `"y"`); `"auto"` reads DAE up_axis, glTF Y, STL Z |
| too small to read, thin parts missing | raise `target_size` (keep within 72 x 96 x 72, else `placement.large = true`) |
| ghost copies, boxes around it | `voxel.exclude = ["*collision*", "*LOD1*"]` (names from `sagas inspect`) |
| holes in a scan | `voxel.close_radius = 1` |
| everything one class | add rules; check `material` names with `sagas inspect` |
| a blob instead of the object | wrong file or package: check the source really is that object |

## 5. Check and hand over

- `sagas lint <theme>/<id>` must pass; `sagas build --check` must report packs up to date.
- Commit `saga.toml`, `voxels.vx.gz`, `preview.png` and `mods/sagas_<theme>/`. Never commit `sources/`.
- In game (optional): `avanti test mods`, or a creative world with `/saga place <id>` and `/saga sites <id>`.
- Never publish (ContentDB, forums, upstream issues) without the maintainer's explicit approval.
