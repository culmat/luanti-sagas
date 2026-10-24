# Pipeline and landmark.toml reference

```
sagas fetch     download the source (sha256-checked) into sources/        needs network or --from FILE
sagas inspect   parts, materials, textures, size of the source
sagas voxelize  source -> content/<saga>/<id>/voxels.vx.gz               needs the source
sagas build     voxels.vx.gz -> mods/sagas_<saga>/ + preview.png         reproducible, no source needed
sagas view      3D page: the landmark at several sizes next to game trees  --serve: any size, live
sagas lint      licence, attribution, size, value budget, drift checks
sagas catalog   docs/gallery/ (index.md, catalog.json)
```

`voxels.vx.gz` is committed, so anyone (and CI) can rebuild packs without downloading models.
`sagas build --check` exits 5 when committed packs differ from a fresh build.
Exit codes: 0 ok, 1 error, 2 bad config, 3 lint errors, 4 source missing, 5 stale output.

## Stages

1. **Load**: DAE (pycollada, keeps material and texture names), glTF/GLB (also Draco), OBJ+MTL, STL,
   PLY; MagicaVoxel `.vox`; voxel point lists `x, y, z[, r, g, b]`. Archives are unpacked safely
   (no paths outside the target, size caps); nothing from a download is ever executed.
2. **Voxelize**: every triangle is sampled densely; each voxel gets the mean colour of its samples,
   the part/material with most samples and a normal class (up, down, side). Transparent texels are
   holes (`voxel.alpha = "ignore"` turns that off). `mode = "solid"` fills enclosed space.
   Luanti is left-handed, so the X axis is flipped; `transform.mirror` undoes that if needed.
3. **Classify** (build): rules map voxels to material classes or to the palette colour node.
4. **Ruin** (build, optional): erosion, per-placement variation, debris, moss.
5. **Interior** (build): air enclosed by walls (doors and windows are bridged) is carved, so terrain
   and trees never fill a hall. The ground layer stays natural ground.
6. **Doorways** (build): many game models paint the door onto the wall texture, so the voxelized wall
   is closed. When a room a player could stand in has no 2-high way in at ground level, the build cuts
   a doorway 2 wide and 2 high where the model shows an entrance: through the wall under a porch roof
   or lintel. Without such a cue it cuts nothing and `sagas lint` warns (L016), suggesting a doorway
   box per side. `voxel.openings` cuts given boxes instead; `voxel.doorway = "none"` keeps it sealed.
7. **Write**: `.mts` schematics with only `air`, `sagas:color` and `sagas:m_<class>` nodes; outside air
   has probability 0 (keeps terrain), solid nodes and carved air are force-placed.

## landmark.toml

Top level: `schema = 1`, `id`, `saga` (both `^[a-z][a-z0-9_]{2,31}$`, matching the directories),
`title`, `tags`, `lore` (shown in game when a player first enters the landmark).

### [source]

| Key | Meaning |
|---|---|
| `kind` | `mesh`, `vox`, `voxels` (point list), `handbuilt`, `none` |
| `url` | Where the model is published. Required unless `manual`. |
| `manual` | `true` when the site needs a login (Sketchfab). Keep the download next to landmark.toml and commit it (up to 50 MB), so anyone can rebuild and rework it; `sagas lint` warns (L017) when it is missing |
| `instructions` | Shown by `sagas fetch` for manual sources |
| `file` | File name of the original: the download, or a file next to landmark.toml |
| `member` | File inside a zip/tar to load; its folder (textures) is extracted too |
| `sha256` | Checksum of the download; `sagas fetch` records it (not for manual sources) |
| `mirror` | A copy of the exact file for manual sources, e.g. the zip attached to the intake issue; `sagas fetch` uses it, so CI can rebuild |
| `edited` | A hand-tweaked copy of the model next to landmark.toml, voxelized instead of the original. The original stays (`file`, `url`), so rework can start from either and `sagas view` compares both (O key); ATTRIBUTION.md says the model was modified |
| `extra_files` | `[{ url, file, sha256 }]` downloaded next to `file` (e.g. textures defined elsewhere) |
| `author`, `author_url`, `license` (SPDX), `license_url`, `notes` | Attribution; licence must be CC0-1.0, CC-BY-3.0/4.0, CC-BY-SA-3.0/4.0 or MIT |
| `ai` | `none`, `assisted`, `generated` (name the tool in `notes`) |

### [transform]

`up` (`auto` = from the file: DAE up_axis, glTF Y, STL Z, OBJ Y), `rotate_y` (0/90/180/270),
`mirror` (`x`/`z`), `target_size` (longest side in nodes) or `scale` (nodes per model unit),
`real_size` (longest side of the real object in metres, for the life-size factor in `sagas view`),
`anchor` (`bottom-center`, `bottom-min`, `center`), `trim_below`/`trim_above` (fraction of height).

### [voxel]

`mode` (`shell`/`solid`), `supersample` (samples per voxel, default 2), `close_radius` (close small
gaps in scans), `min_component` (drop floating specks smaller than N voxels), `exclude` (globs on part
or material names, e.g. collision meshes or low-detail LODs), `texture` (image for UV-mapped parts
without one), `alpha` (`cutout`/`ignore`), `interior` (`carve`/`keep`), `interior_close` (door width
bridged when finding rooms), `doorway` (`auto`: cut a doorway into sealed rooms under a porch or
lintel; `none`: sealed on purpose, like a tomb), `openings` (boxes `[x1, y1, z1, x2, y2, z2]` in
schematic coordinates cut to air, e.g. `[[16, 1, 29, 17, 2, 29]]`; layer 0 is the ground, layers 1-2
are door height).

### [materials]

`mode`: `classes` (realistic: everything becomes material classes), `hybrid` (rules first, unmatched
coloured voxels keep their colour), `palette` (fantasy: colours everywhere). `default` class,
`context` (`surroundings`: the mod reuses the stone and wood of the site; `fixed`), `overrides`
(`{ roof_red = "fixed", stone = "sandstone" }`), `value_budget` (`{ gold = 12 }`).

Rules, first match wins:

```toml
[[materials.rules]]
match = { material = "*roof*" }            # glob on material name and texture file name
class = "roof_red"

[[materials.rules]]
match = { y_frac = [0.8, 1.0], normal = "up" }   # also: y = [lo, hi], part = "glob", color = "#rrggbb", tol = 20
class = "thatch"

[[materials.rules]]
match = { part = "Statue*" }
color = true                               # keep the colour of these voxels
```

### [ruin]

`enabled`, `erosion` (0-1, more near the top), `variation` (0-1, top nodes may be missing in a given
placement), `debris_height` (fill rooms up to this layer with rubble), `moss` (fraction of up-facing
stone), `seed`.

### [placement]

See [placement.md](placement.md): `site`, `exposure`, `biomes`, `rarity`, `y_min`, `y_max`,
`rotation`, `foundation` (depth or true/false), `clear_above`, `large`, `min_distance`, `hints`.

## Determinism

Builds are byte-for-byte reproducible: names are sorted, zlib level is fixed, random choices are
seeded, gzip timestamps are zero. CI relies on this (`sagas build --check`).
