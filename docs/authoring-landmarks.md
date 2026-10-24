# Authoring a landmark (guide for people and coding agents)

A landmark is a free 3D model turned into a Luanti schematic. Creators describe **where** it belongs and
**what** it is made of; the `sagas` mod places it and picks the game's materials. Reference:
`docs/pipeline.md` (all landmark.toml fields), `docs/placement.md`, `docs/materials.md`, `docs/sources.md`.

Every landmark belongs to a **saga**, a theme such as *ruins*, *antiquity* or *vikings*
(see [glossary.md](glossary.md)). Pick the saga with the creator; a new saga is a folder
`content/<saga>/` with a `saga.toml` holding its `title` and `description`, and becomes the pack
`sagas_<saga>`.

Run the CLI as `uv run --project tools sagas ...` from the repository root.

## 1. The model and its licence

- Accept only CC0, CC-BY, CC-BY-SA or MIT. Never NC or ND, never film or game characters, never
  marketplace or 3D Warehouse models. If the licence is unclear, stop and tell the user why.
- Candidates: `docs/scouting/<saga>.md`; `sagas scout promote <id> --saga <saga> --id <id>` writes the
  landmark.toml. Otherwise `sagas new <id> --saga <saga> --url ... --license ... --author ...`.
- Sketchfab needs a login: `manual = true`, `member = "scene.gltf"`, the user downloads the glTF zip and
  runs `sagas fetch <saga>/<id> --from <zip>`.
- CC-BY-SA sources belong in a share-alike saga (like `antiquity`); `sagas lint` warns when a saga mixes.

## 2. From the creator's words to [placement]

| They say | Field |
|---|---|
| hilltop, summit, overlooking the land | `site = ["peak"]` (or `"ridge"`) |
| on a cliff, at the edge of a drop | `"cliff"`; sea cliff: `"cliff+coast"` |
| by the sea, harbour, shore | `"coast"`, biomes may include `"beach"` |
| by a river, bridge, ford | `"plain+river"` or `"river"` |
| lake, pond | `"lake"`; near a waterfall: `"waterfall"` |
| flat field, meadow, village | `"plain"`; hillside: `"slope"` |
| built against the rock, leaning on a hillside, propped up by stone | `"slope+against_rock"`, `"cliff+against_rock"` |
| at a cave entrance, guarding a cave | `"cave_mouth"` (with `"against_rock"` to touch the rock too) |
| sunken, wreck, sea floor | `"underwater"` |
| in a cave, on the cave floor | `"cave_floor"`, hanging from it: `"cave_ceiling"`; set `y_max = -20` |
| carved into the mountain, dwarven halls | `"carve"`, `y_max` below the surface (e.g. -20) |
| on floating islands | `"floatland"` |
| a landmark, visible from afar, watching over | `exposure = "prominent"` |
| hidden, secret, deep in the forest, in a valley | `exposure = "hidden"` (the only way into dense forest) |
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
sagas fetch <saga>/<id>
sagas inspect <saga>/<id>          # parts, materials, textures, extents, up axis
sagas voxelize <saga>/<id> --force
sagas build <saga>                 # writes mods/sagas_<saga>/ and content/<saga>/<id>/preview.png
```

Read `preview.png` (top, front, side, isometric) and fix:

| Looks like | Fix |
|---|---|
| lying on its side | `transform.up = "z"` (or `"y"`); `"auto"` reads DAE up_axis, glTF Y, STL Z |
| too small to read, thin parts missing | raise `target_size` after comparing sizes (section 5); keep within 72 x 96 x 72, else `placement.large = true` |
| towers over the trees, dwarfs the houses | lower `target_size` (section 5) |
| ghost copies, boxes around it | `voxel.exclude = ["*collision*", "*LOD1*"]` (names from `sagas inspect`) |
| holes in a scan | `voxel.close_radius = 1` |
| everything one class | add rules; check `material` names with `sagas inspect` |
| a blob instead of the object | wrong file or package: check the source really is that object |
| a house, temple or tower with no door | see "Doors" below |

### Doors

Game models often paint the door onto the wall, so the voxelized building is closed. The build
cuts a doorway (2 wide, 2 high) into sealed rooms where the model shows an entrance, under a porch
roof or lintel, and `sagas build` prints `doorway cut facing ...`. Check that it is where the door
belongs. When the model shows no entrance, `sagas lint` warns with L016 and lists one doorway box per
side. Pick the side the building faces (columns, steps, a forecourt, a path), or look up a photo of
the real building, and add it:

```toml
[voxel]
openings = [[16, 1, 29, 17, 2, 29]]   # [x1, y1, z1, x2, y2, z2]; several boxes for a gate and a door
```

A tomb or vault may stay closed: `doorway = "none"`. Players break in, so put something worth it
inside (a treasure mod via `sagas.register_on_placed`).

## 5. Size and detail

Too small and the detail is gone; too big and the landmark towers over the forest and dwarfs every
house. Decide the size on purpose, with the creator:

```sh
sagas view <saga>/<id>                          # 3D page in the browser (.dev/view/<saga>-<id>.html)
sagas view <saga>/<id> --serve                  # live: any size via -/+, the number field or the slider
sagas view <saga>/<id> --sizes 16,24,32 --png sizes.png --no-open   # plus a still of all sizes
```

The page shows the landmark as `sagas build` makes it, at several sizes (• marks the one in
landmark.toml), next to a player and the trees and village houses of the games installed on your
machine. Drag to turn it, zoom in to judge the detail, press M to swap in the source model and see
what the nodes keep, cut it open layer by layer, show the carved air of rooms and doorways, and
click a node for its coordinates (shift-click a second node for a `voxel.openings` box). With `--serve`, a local server (this machine only, Ctrl-C stops it)
builds any size you ask for in a second or two, exactly as `sagas build` would; without it the
page has the preset sizes. Other sizes need the source (`sagas fetch`). Settings and the camera are
remembered per landmark. The page embeds the games'
schematics, so it stays on your machine: `.dev/` is never committed. Coding agents cannot turn the
page: they read the `--png` still and give the person the page's path.

1. **Note the real size**: `real_size` in `[transform]`, the longest side of the real object in
   metres, from the source (a museum record, the building's dimensions). `sagas inspect` shows the
   model's extents; 5081 with no unit is usually millimetres. The view then says "x N life size".
2. **Pick the scale** with the creator:

| Scale | For | Rule of thumb |
|---|---|---|
| life size (1 node is about 1 m) | buildings, ships, anything players enter | doors 2 high, storeys 3 to 4 |
| enlarged (2 to 5 times) | skeletons, statues, small objects whose detail vanishes at life size | no taller than the trees around it |
| giant (more) | only when title and lore say so ("Giant ...", a titan's bones) | the lore explains the size |

3. **Keep the parts that matter**: tusks, legs, columns and spires need at least one node. If they
   only survive at giant size, make it a giant on purpose, or show it another way (half buried, as a
   ruin).

Heights in nodes, from the games' own schematics: player 1.75, doors 2; Minetest Game trees 8 (apple)
to 17 (jungle), the emergent jungle tree 37; Mineclonia trees 7 to 15, huge spruce and jungle trees
19 to 30, village houses 7 to 10, the village church 13; a map chunk is 80.

Set the chosen size as `target_size`, then `sagas voxelize <saga>/<id> --force` and `sagas build <saga>`.

## 6. Check and hand over

- `sagas lint <saga>/<id>` must pass without warnings (L016: rooms without a door).
- Commit `landmark.toml`, `voxels.vx.gz` and `preview.png`; CI rebuilds the packs in `mods/` and
  releases them after the merge ([releasing.md](releasing.md)). Never commit `sources/`.
- In game (optional): `avanti play mods`, then `/saga find <id>`: fresh map is generated around you
  until map generation places your landmark, and you are taken to it (`/saga tour <id>` circles it,
  Space switches the time of day). `/saga place <id>` places it where you point, `/saga sites <id>`
  marks where its site fits. For many placements at once: `avanti survey mods --set sagas_only=<id>
  --set sagas_rarity_scale=0.001 --keep` (see [placement.md](placement.md)).
- Never publish (ContentDB, forums, upstream issues) yourself: a maintainer's approval of the pull
  request releases it.
