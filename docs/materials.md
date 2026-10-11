# Materials

Schematics never contain game nodes. Every voxel is either a **material class** placeholder
(`sagas:m_<class>`) or the **palette colour** node (`sagas:color`, param2 = one of 256 colours).
When a landmark is placed, the mod swaps each placeholder for a node of the running game.

## Classes

| Class | Meaning | Minetest Game | Mineclonia / VoxeLibre |
|---|---|---|---|
| rock | natural stone, foundations | stone* | stone* |
| stone | dressed masonry (castle walls) | stonebrick* | stonebrick* |
| cobble | rubble masonry | cobble* | cobble* |
| moss | mossy rubble | mossycobble* | mossy stone bricks* |
| marble | light, smooth stone | silver sandstone block / stone block* | polished diorite* |
| stone_dark | dark masonry | obsidian brick | deepslate bricks |
| brick | fired clay bricks | brick | brick block |
| sandstone | sandstone masonry | sandstone block (or the site's sandstone) | smooth sandstone (or the site's) |
| wood | timber, planks | planks of the site's tree** | planks of the site's tree** |
| log | trunks, beams | trunk of the site's tree** | trunk of the site's tree** |
| planks | light floor planks | aspen planks | birch planks |
| roof_red | red roof tiles | brick | red terracotta |
| roof_dark | dark roof tiles | jungle wood | deepslate tiles |
| thatch | thatch | straw | hay bale |
| metal | iron work (budget 64) | steel block | iron block |
| gold | gold (budget 0 unless granted, max 64) | gold block | gold block |
| emerald | gems (budget 0 unless granted, max 64) | jade-coloured landmark stone | emerald block |
| glass, water, ice, snow, dirt, grass, leaves, bone, lamp | as named | game nodes; water is still water unless `sagas_real_water` | game nodes |
| debris | rubble mix | gravel, cobble, mossy cobble, dirt (varied per node) | same |

\* With `materials.context = "surroundings"` (the default) these follow the **stone family** of the
site: desert stone in deserts, sandstone in sandstone deserts, granite, deepslate, red sandstone in
mesas, and so on. The family comes from the biome's `node_stone`, else from the rock under the footprint.

\** The wood follows the biome: pine or spruce in taiga and snow, acacia in savanna, jungle wood in
jungles, the default tree elsewhere.

`materials.context = "fixed"` always uses the table above. `materials.overrides` changes single
classes: `{ roof_red = "fixed" }` keeps red roofs everywhere, `{ stone = "sandstone" }` uses the
sandstone mapping for walls.

A class without any node in the running game stays a striped placeholder block, visible but never
an "unknown node". Games other than these three get a generic mapping (mapgen aliases, node names).

## Value budget

Players can mine landmarks, so precious materials are limited per landmark: `gold` and `emerald` default to 0
and may be raised to at most 64 nodes (`materials.value_budget`), `metal` and `lamp` default to 64
and 32. `sagas lint` fails when a landmark exceeds its budget. Diamond and mese never appear.

## The palette

256 colours, generated in CIE Lab: 24 greys, a lattice of 12 hues x 5 lightness x 3 chroma levels,
and 52 material anchors (sandstone, granite, oak, thatch, moss, bone, water, ice, skin tones, metals).
Colours are matched in Lab space without dithering. The palette is fixed: changing it would recolour
every palette landmark, so `sagas palette` only checks it.

Use the palette for fantasy models whose colours matter (statues, dragons), classes for anything a
player would expect to be made of real materials (castles, houses, ships).
