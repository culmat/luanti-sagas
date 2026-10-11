"""Hand-built sagas: a schematic exported in game (/landmark export) -> VoxelModel with classes.

Game nodes are mapped back to material classes so the landmark adapts to every game: explicit table
first, then name patterns (stairs and slabs use their base material), coloured blocks (wool,
concrete, terracotta) keep their colour. Unknown nodes fall back to the default class and are
reported; a materials rule can still override any node (match = { part = "mod:node" }).
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from . import schematic
from .voxels import VoxelModel, compute_normals

EXPLICIT = {
    # Minetest Game
    "default:stone": "rock",
    "default:desert_stone": "rock",
    "default:sandstone": "sandstone",
    "default:desert_sandstone": "sandstone",
    "default:silver_sandstone": "sandstone",
    "default:stonebrick": "stone",
    "default:stone_block": "marble",
    "default:desert_stonebrick": "stone",
    "default:desert_stone_block": "marble",
    "default:sandstonebrick": "sandstone",
    "default:sandstone_block": "sandstone",
    "default:desert_sandstone_brick": "sandstone",
    "default:desert_sandstone_block": "sandstone",
    "default:silver_sandstone_brick": "marble",
    "default:silver_sandstone_block": "marble",
    "default:cobble": "cobble",
    "default:desert_cobble": "cobble",
    "default:mossycobble": "moss",
    "default:obsidian": "stone_dark",
    "default:obsidianbrick": "stone_dark",
    "default:obsidian_block": "stone_dark",
    "default:brick": "brick",
    "default:steelblock": "metal",
    "default:copperblock": "metal",
    "default:tinblock": "metal",
    "default:bronzeblock": "metal",
    "default:goldblock": "gold",
    "default:meselamp": "lamp",
    "default:glass": "glass",
    "default:obsidian_glass": "glass",
    "default:dirt": "dirt",
    "default:dirt_with_grass": "grass",
    "default:dry_dirt": "dirt",
    "default:snowblock": "snow",
    "default:ice": "ice",
    "default:gravel": "debris",
    "default:water_source": "water",
    "default:river_water_source": "water",
    "default:coral_skeleton": "bone",
    "default:clay": "dirt",
    "farming:straw": "thatch",
    "default:bookshelf": "wood",
    # Mineclonia / VoxeLibre
    "mcl_core:stone": "rock",
    "mcl_core:granite": "rock",
    "mcl_core:diorite": "rock",
    "mcl_core:andesite": "rock",
    "mcl_core:stonebrick": "stone",
    "mcl_core:stonebrickcracked": "stone",
    "mcl_core:stonebrickcarved": "stone",
    "mcl_core:stonebrickmossy": "moss",
    "mcl_core:stone_smooth": "marble",
    "mcl_core:granite_smooth": "marble",
    "mcl_core:diorite_smooth": "marble",
    "mcl_core:andesite_smooth": "marble",
    "mcl_core:cobble": "cobble",
    "mcl_core:mossycobble": "moss",
    "mcl_core:sandstone": "sandstone",
    "mcl_core:sandstonesmooth": "sandstone",
    "mcl_core:sandstonesmooth2": "sandstone",
    "mcl_core:sandstonecarved": "sandstone",
    "mcl_core:redsandstone": "sandstone",
    "mcl_core:redsandstonesmooth": "sandstone",
    "mcl_core:brick_block": "brick",
    "mcl_core:ironblock": "metal",
    "mcl_core:goldblock": "gold",
    "mcl_core:emeraldblock": "emerald",
    "mcl_core:glass": "glass",
    "mcl_core:dirt": "dirt",
    "mcl_core:coarse_dirt": "dirt",
    "mcl_core:dirt_with_grass": "grass",
    "mcl_core:snowblock": "snow",
    "mcl_core:ice": "ice",
    "mcl_core:packed_ice": "ice",
    "mcl_core:gravel": "debris",
    "mcl_core:water_source": "water",
    "mcl_core:bone_block": "bone",
    "mcl_farming:hay_block": "thatch",
    "mcl_ocean:sea_lantern": "lamp",
    "mcl_nether:glowstone": "lamp",
    "mcl_core:obsidian": "stone_dark",
    "mcl_deepslate:deepslate": "rock",
    "mcl_deepslate:deepslate_bricks": "stone_dark",
    "mcl_deepslate:deepslate_tiles": "roof_dark",
    "mcl_deepslate:deepslate_cobbled": "cobble",
    "mcl_deepslate:deepslate_polished": "stone_dark",
}

PATTERNS = [  # (regex on the node name without the stair/slab prefix, class), first match wins
    (r"mossy", "moss"),
    (r"cobble", "cobble"),
    (r"stonebrick|stone_brick|bricks?_stone", "stone"),
    (r"brick", "brick"),
    (r"sandstone", "sandstone"),
    (r"marble|quartz|smooth|polished", "marble"),
    (r"obsidian|deepslate|blackstone|basalt", "stone_dark"),
    (r"stone|granite|andesite|diorite|rock", "rock"),
    (r"leaves|needles", "leaves"),
    (r"tree|log|trunk", "log"),
    (r"wood|plank|fence|door|gate|ladder", "wood"),
    (r"glass|pane", "glass"),
    (r"straw|hay|thatch", "thatch"),
    (r"lamp|lantern|torch|glowstone", "lamp"),
    (r"iron|steel|copper|bronze|tin|metal|bars", "metal"),
    (r"gold", "gold"),
    (r"emerald", "emerald"),
    (r"snow", "snow"),
    (r"ice", "ice"),
    (r"gravel", "debris"),
    (r"grass", "grass"),
    (r"dirt|clay|mud", "dirt"),
    (r"water", "water"),
    (r"bone", "bone"),
    (r"roof|tile|shingle", "roof_red"),
]

# Colours of coloured blocks: (name pattern, rgb). Concrete values from matmod's palettes.lua.
DYES = {
    "white": (209, 214, 215),
    "silver": (129, 129, 119),
    "light_grey": (129, 129, 119),
    "grey": (57, 60, 64),
    "dark_grey": (57, 60, 64),
    "black": (8, 10, 16),
    "red": (147, 34, 34),
    "orange": (226, 101, 1),
    "yellow": (241, 178, 22),
    "lime": (97, 172, 25),
    "green": (75, 94, 37),
    "dark_green": (75, 94, 37),
    "cyan": (22, 123, 140),
    "light_blue": (37, 141, 201),
    "blue": (46, 49, 148),
    "purple": (103, 33, 159),
    "violet": (103, 33, 159),
    "magenta": (172, 50, 162),
    "pink": (213, 103, 145),
    "brown": (99, 61, 32),
}
COLOURED = re.compile(r"(?:wool|concrete|hardened_clay|terracotta|glazed)[_:]?(\w*)$")


def classify_node(name: str) -> tuple[str, tuple[int, int, int] | None]:
    """-> (class or "color", rgb for colour nodes)."""
    if name in EXPLICIT:
        return EXPLICIT[name], None
    item = name.split(":", 1)[-1]
    m = COLOURED.search(item) or (re.search(r"^(\w+)$", item) if name.startswith("wool:") else None)
    if m:
        colour = m.group(1).replace("powder_", "").strip("_")
        for dye, rgb in sorted(DYES.items(), key=lambda kv: -len(kv[0])):
            if colour.endswith(dye):
                return "color", rgb
    base = re.sub(r"^(stair|slab|stairs|slabs|step)_?(inner_|outer_|top_|double_)?", "", item)
    for pat, cls in PATTERNS:
        if re.search(pat, base):
            return cls, None
    return "", None


def read_mts(path: Path) -> tuple[VoxelModel, list[str]]:
    """VoxelModel from an exported .mts; returns the model and the node names that had no mapping."""
    g = schematic.read_mts(Path(path).read_bytes())
    skip = {"air", "ignore"}
    placed = ((g.param1 & 0x7F) > 0) & ~np.isin(g.content, [i for i, n in enumerate(g.names) if n in skip])
    model = VoxelModel.empty(g.size)
    model.occ = placed.copy()
    unknown = []
    parts = []
    for i, name in enumerate(g.names):
        if name in skip:
            continue
        cls, rgb = classify_node(name)
        sel = placed & (g.content == i)
        if not sel.any():
            continue
        if not cls:
            unknown.append(name)
        parts.append((name, "color" if cls == "color" else (f"class:{cls}" if cls else "")))
        model.part[sel] = len(parts) - 1
        if rgb:
            model.rgb[sel] = rgb
            model.has_rgb[sel] = True
    model.parts = parts
    model.normal = compute_normals(model.occ)
    return model.cropped(), unknown
