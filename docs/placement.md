# Placement: how a landmark finds its place

Creators describe where a landmark belongs; the `sagas` mod decides while the map is generated.

```toml
[placement]
site = ["cliff+coast", "cliff+river", "waterfall"]   # alternatives, tried in order
exposure = "prominent"                               # prominent | hidden | any
biomes = ["any"]                                     # tags, see below
rarity = 400                                         # about one per 400 mapchunks where it is tried
hints = "Stone watchtower on sea or river cliffs, or by a waterfall."
```

## Site primitives

Combine primitives with `+` (all must hold); list alternatives in an array.

| Primitive | Holds when |
|---|---|
| `plain` | the footprint is flat (height spread up to 4, little variation) and above water |
| `slope` | the ground rises steadily across the footprint |
| `ridge` | the centre is at least 4 higher than both sides along one axis |
| `peak` | nothing higher within about 12 nodes and at least 8 above the surroundings |
| `cliff` | flat footprint with a drop of 6+ nodes right next to one edge |
| `coast` | land, with the sea within about 12 nodes |
| `river` | river water close by (mapgens with rivers) |
| `lake` | still water above sea level close by |
| `waterfall` | flowing water close by next to a drop |
| `underwater` | the sea floor, deep enough for the landmark |
| `cave_floor`, `cave_ceiling` | the floor or ceiling of an underground cave (set `y_max` below -10) |
| `carve` | solid rock below the surface: the landmark's interior is carved out (dwarven halls) |
| `floatland` | on mgv7 floatlands |
| `against_rock` | an upper corner of the landmark touches natural rock: a wall running into a hillside, a cliff or a cave mouth (ruins may sink up to 3 nodes to reach it) |
| `cave_mouth` | a cave opens into the hill right next to the landmark, at its ground level |
| `any` | anywhere the surface is known |

`against_rock` and `cave_mouth` are contact checks: they test the height another primitive chose
(`slope+against_rock`), or the footprint's median height when used alone.

`exposure = "prominent"` additionally wants nothing higher close by (or the sea on one side);
`hidden` wants a valley, tree cover, or an underground site. Only `hidden` landmarks stand in deep
forest: for `any` and `prominent`, at most 40% of the ground within 8 nodes may lie under tree canopy,
so in forest biomes they end up in clearings and at forest edges instead of buried in leaves.

## Biome tags

`desert savanna grassland forest jungle taiga snow tundra mountain swamp beach ocean mushroom any`.
The mod maps tags to the biomes of the running game (explicit tables for Minetest Game, Mineclonia
and VoxeLibre, then name keywords, then the biome's heat and humidity).

## Rarity

`rarity` is roughly how many generated mapchunks (80 x 80 x 80 nodes) each landmark gets one attempt in:
60 is common, 400 rare, 5000 legendary. An attempt tries six positions and rotations; when the site
does not fit, nothing is placed, so sites that are hard to satisfy are rarer in practice. The server
setting `sagas_rarity_scale` multiplies all rarities.

Landmarks never overlap, and rare landmarks (rarity 400+) keep a distance from copies of themselves
(`min_distance`, default three times their width).

## What the mod does on placement

1. Clears trees and plants in the footprint and up to 16 nodes above.
2. Checks that every foot stands on the ground. A landmark's feet are the connected parts of its
   bottom layer (a skeleton's four feet, a house's walls, a temple's columns). No foot may hang over
   the natural ground further than its foundation fills (`foundation`, so a skeleton with 3 never
   spans a canyon), or sink deeper than a third of the landmark's height. Sites that want contact
   with the hill (`against_rock`, `cave_mouth`) may bury a foot completely: a wall runs into the
   hillside. Trees are not ground: a landmark never stands on a forest canopy. Mods that register
   landmarks themselves can set `support = "free"` for things that float.
3. On uneven ground, sets the landmark a little into the ground: half the drop from the chosen height
   to the lowest point of the footprint, at most 2 nodes and a sixth of its height. The uphill side is
   buried slightly, the downhill side hangs less.
4. Places the schematic (walls replace terrain, outside air keeps it, rooms are carved).
5. Builds a foundation of the site's rock under every column that starts on the landmark's bottom layer
   and under the floor of every ground-level room, down to the ground (at most `foundation` nodes).
   A node that would hang exactly one node above the ground gets a support node; higher overhangs
   such as eaves, porches and lintels stay as they are.
6. Replaces material placeholders with the nodes of the site (see [materials.md](materials.md)).
7. In biomes that dust their terrain (snow in cold biomes), covers the landmark's top surfaces with
   the same node, as the mapgen does for terrain.
8. Records the placement (for `/saga here`, lore messages and spacing) and calls
   `sagas.register_on_placed` callbacks, which other mods can use to add loot or mobs.

## Large landmarks

Landmarks wider than 72 nodes or taller than 96 need `large = true`. The world is split into
512 x 512 cells with at most one deterministic candidate per cell and landmark. When the mapchunk with
that column's surface is generated, the landmark's area is emerged, the site is checked on the real
terrain, and the landmark is placed. Pending placements survive a server restart.

## Games and mapgens

Placement uses the engine API only (heightmap, biome map, VoxelManip), so the same code runs in
Minetest Game, Mineclonia and VoxeLibre. With `mg_name = singlenode` or Mineclonia's own Lua
level generator, automatic placement is off; `/saga place` still works.

## Testing a placement

One landmark, by hand:

- `/saga sites <id> [radius]` marks every spot around you where the site expression holds.
- `/saga place <id> [rotation]` places at the node you point at; `/saga undo` reverts.
- `sagas_debug = true` logs every automatic placement.

What map generation really does: run a survey, then visit the result.

```sh
avanti survey mods --game minetest --set sagas_survey=true --keep
avanti play mods --game minetest --world ~/.avanti/worlds/survey-luanti-sagas-minetest-avanti/world --lite
```

`--lite` renders the 3D world at half resolution; use it on integrated graphics or 4K screens, where
the tour otherwise stutters. `avanti play` starts you flying fast, with every privilege.

`avanti survey` ([avanti-luanti](https://github.com/culmat/avanti-luanti)) generates about 6 km2
headlessly with a fixed seed and prints the surface biomes, every landmark's count, density and
distance to its nearest copy, and balance findings from the `sagas_survey` tool mod
(`mods/tools/survey`, never released). `sagas_survey = true` also tests every landmark's site in every
chunk without placing it, so even rare landmarks show how often and in which biomes they would fit.

| Finding | Meaning |
|---|---|
| SV001 | Copies of a landmark are closer than its target (large builds 2 km, medium 1 km) |
| SV002 | The landmark fits in under 1% of surface chunks, although its biomes were there |
| SV003 | None of the landmark's biomes were in the surveyed area: survey another seed or `--spacing 2000` |
| SV004 | Most rolls in surface chunks find no site, so the landmark is much rarer than `rarity` says |
| SV005 | More than 0.5 lit landmarks per km2: lamps take the darkness out of survival nights |
| SV006 | A landmark with the `lamp` class has no light-emitting node after material mapping |
| SV010 | Automatic placement is off in this world (singlenode, Mineclonia levelgen) |
| SV011 | Placement was boosted for testing (`sagas_only`, `sagas_rarity_scale`): repeat findings skipped |

In game (privilege `sagas`, which singleplayer has):

| Command | Does |
|---|---|
| `/saga placed [id] [radius]` | Recorded landmarks, nearest first, with distance, direction, biome and site |
| `/saga tp <n>` or `/saga tp <id>` | Go to entry n of that list, or to the next copy of a landmark, facing it |
| `/saga tour [n or id] [--times 0.5,0]` | Fly around each landmark in turn, from entry n of `/saga placed` or only copies of one landmark |
| `/saga waypoints [radius]` | HUD markers on landmarks within radius (default 400); `off` |
| `/saga find <id> [km] [--new]` | Generate fresh map around you until map generation places that landmark, then take you there (see below) |
| `/saga stats [id]` | Placement attempts this session: rolls, placements, why candidates failed, survey fit rates |

### Seeing one landmark placed by map generation

`/saga find <id>` generates fresh map in rings around you (up to 3 km, `[km]` up to 16) until map
generation places that landmark, then takes you to a viewpoint facing it. While it searches, the
engine places only this landmark and rolls it in every new mapchunk; its site, biomes, spacing,
anchoring and snow work exactly as in normal map generation. Tiles without its biomes are skipped
without generating them, so cold-climate landmarks are found kilometres away. If a copy is already
recorded, `find` points to it; `--new` searches fresh land anyway. `/saga find stop` ends a search.

Headless, for many placements at once (all in one fresh world, kept to visit):

```sh
avanti survey mods --game minetest --set sagas_only=mammoth_skeleton --set sagas_rarity_scale=0.001 --keep
```

The report says how many fitted and in which biomes; `avanti play ... --world <kept world> --lite`
and `/saga tour mammoth_skeleton` show them. `sagas_only` takes ids separated by commas.

The tour attaches you to an invisible camera that circles each landmark once (30 s, `--period`) and
then moves on. If a game does not keep players attached, it switches to fixed viewpoints by itself
(`--static` forces them). The keys are shown at the top of the screen:

| Key | During the tour |
|---|---|
| A / D | previous / next landmark |
| W / S (hold) | closer / farther |
| Space | time of day: noon, dusk, midnight, dawn (to check lamps) |
| E | pause: fly around freely (K toggles flying); E again resumes from where you are |
| Shift | end the tour and go back to where it started |

`/saga tour pause`, `resume`, `next`, `prev` and `stop` do the same from chat; stopping while paused
leaves you where you flew to. The tour restores your HUD and the time of day.
