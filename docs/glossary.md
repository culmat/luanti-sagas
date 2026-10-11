# Glossary

| Term | Meaning |
|---|---|
| **saga** | A theme with its own look and story, such as *ruins*, *antiquity*, *vikings* or *dragon fantasy*. A saga is a folder `content/<saga>/` (with `saga.toml`: title, description) and becomes one content pack mod, `sagas_<saga>`. Players and server owners enable or disable whole sagas. |
| **landmark** | One structure made from one 3D model: a castle, a ship, a temple, a statue. Described by `content/<saga>/<landmark>/landmark.toml`; its id in game is `sagas_<saga>:<landmark>`, e.g. `sagas_ruins:cathedral`. |
| **Sagas** (the mod) | The core mod `sagas`. It maps material classes to the running game and decides where landmarks go. Its chat command is `/saga`. |
| **content pack** | The generated mod of one saga (`mods/sagas_<saga>/`): schematics, registry, licences. Never edited by hand. |
| **source model** | The free 3D model a landmark is made from (glTF, OBJ, DAE, STL, MagicaVoxel, voxel list, or a schematic built in game). Never committed; `landmark.toml` records where it comes from and its licence. |
| **hints** | What a creator says about a landmark: where it belongs and what it is made of. Written in words (`hints`) and as fields (`site`, `exposure`, `biomes`, `materials`). |
| **site** | A placement rule evaluated on the terrain: `plain`, `peak`, `cliff`, `coast`, `river`, `cave_floor`, `carve`, ... Combine with `+` (`cliff+coast`); list alternatives. See [placement.md](placement.md). |
| **exposure** | Whether a landmark wants to be seen (`prominent`), tucked away (`hidden`), or `any`. |
| **biome tag** | A game-independent biome group (`desert`, `taiga`, `mountain`, ...) that the mod maps to each game's biomes. |
| **rarity** | Roughly how many generated mapchunks each landmark gets one placement attempt in (60 common, 400 rare, 5000 legendary). |
| **material class** | An abstract material in a schematic (`stone`, `wood`, `roof_red`, ...), stored as a placeholder node `sagas:m_<class>` and replaced by a node of the game and site when placed. See [materials.md](materials.md). |
| **surroundings** | The default material context: stone and wood classes follow the stone family and trees of the site (desert stone in deserts, spruce in taiga). |
| **palette node** | `sagas:color`, one node with 256 colours, used where a landmark's colours matter (statues, creatures). |
| **value budget** | The cap on precious materials (gold, emerald) per landmark, so landmarks don't become mines. |
| **large landmark** | A landmark bigger than one mapchunk (`large = true`), emerged and placed after map generation. |
| **voxels.vx.gz** | The committed voxelization of a source model; lets anyone rebuild packs without downloading models. |
| **scout** | `sagas scout`: searches free model sources per saga and lists candidates in `docs/scouting/`. |
| **agent** | Any coding assistant that works in this repository (Claude Code, opencode, ...). Project notes for agents are in [AGENTS.md](../AGENTS.md). |
