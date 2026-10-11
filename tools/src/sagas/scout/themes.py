"""Theme -> search terms, and keyword -> placement suggestions. Edit freely."""

from __future__ import annotations

THEMES: dict[str, list[str]] = {
    "medieval": ["castle", "castle ruin", "watchtower", "fortress", "keep", "gatehouse", "stone bridge"],
    "viking": ["longship", "viking ship", "stave church", "longhouse", "rune stone"],
    "asian": ["pagoda", "torii", "shrine", "chinese temple", "japanese castle", "stone lantern"],
    "egyptian": ["sphinx", "obelisk", "egyptian temple", "pyramid", "colossus"],
    "antique": ["greek temple", "roman temple", "triumphal arch", "amphitheatre", "caryatid"],
    "prehistoric": ["dolmen", "menhir", "stone circle", "henge", "cairn", "broch"],
    "gothic": ["abbey ruins", "cathedral ruins", "cloister"],
    "nautical": ["lighthouse", "shipwreck", "harbour fort"],
    "dwarven": ["mine tunnel", "mine entrance", "cave", "rock face"],
    "elven": ["giant tree", "old oak", "tree trunk", "roots"],
    "alpine": ["swiss castle", "schloss", "burg"],
    "creatures": ["guardian lion", "komainu", "dragon statue", "knight statue", "griffin", "skeleton"],
    "celtic": ["roundhouse", "hill fort", "high cross", "broch"],
    "persian": ["persepolis", "ziggurat", "persian palace"],
}

# keyword in the title -> (site alternatives, biome tags)
SITE_HINTS: list[tuple[str, list[str], list[str]]] = [
    ("lighthouse", ["cliff+coast", "coast"], ["any"]),
    ("watchtower", ["peak", "cliff", "ridge"], ["any"]),
    ("tower", ["peak", "ridge", "plain"], ["any"]),
    ("castle", ["ridge", "peak", "plain"], ["grassland", "forest", "mountain"]),
    ("bridge", ["plain+river", "river"], ["any"]),
    ("ship", ["coast"], ["beach", "any"]),
    ("wreck", ["underwater", "coast"], ["ocean", "beach"]),
    ("pagoda", ["plain", "ridge"], ["forest", "jungle", "mountain"]),
    ("temple", ["plain", "ridge"], ["any"]),
    ("pyramid", ["plain"], ["desert", "savanna"]),
    ("sphinx", ["plain"], ["desert"]),
    ("dolmen", ["plain", "ridge"], ["grassland", "tundra", "taiga"]),
    ("henge", ["plain"], ["grassland", "tundra"]),
    ("mine", ["carve", "cave_floor"], ["any"]),
    ("cave", ["carve", "cave_floor"], ["any"]),
    ("tree", ["plain"], ["forest", "jungle"]),
    ("abbey", ["plain", "slope"], ["grassland", "forest"]),
]


def suggest(title: str, theme: str) -> tuple[list[str], list[str]]:
    t = title.lower()
    for kw, site, biomes in SITE_HINTS:
        if kw in t:
            return site, biomes
    if theme == "egyptian":
        return ["plain"], ["desert", "savanna"]
    return ["plain"], ["any"]
