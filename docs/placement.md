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
| `any` | anywhere the surface is known |

`exposure = "prominent"` additionally wants nothing higher close by (or the sea on one side);
`hidden` wants a valley, tree cover, or an underground site.

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
2. Places the schematic (walls replace terrain, outside air keeps it, rooms are carved).
3. Builds a foundation of the site's rock under every column that starts on the landmark's bottom layer,
   down to the ground (at most `foundation` nodes).
4. Replaces material placeholders with the nodes of the site (see [materials.md](materials.md)).
5. Records the placement (for `/saga here`, lore messages and spacing) and calls
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

- `/saga sites <id> [radius]` marks every spot around you where the site expression holds.
- `/saga place <id> [rotation]` places at the node you point at; `/saga undo` reverts.
- `sagas_debug = true` logs every automatic placement.
