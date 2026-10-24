"""From a creator's words to [placement]: the table in docs/authoring-landmarks.md, section 2.

Deterministic keyword rules, used when a landmark arrives through the "Model found" form and no
person or agent has read the words yet. The words are kept in `hints`; a maintainer or the
creator refines the fields later (PR comment commands, or by hand).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# (pattern, site expression), in order of preference when several match
SITES = [
    (r"sea ?cliff|cliffs? (by|above|over) the sea", "cliff+coast"),
    (r"cave (entrance|mouth)|guard(s|ing)? (a|the) cave", "cave_mouth+against_rock"),
    (r"against (the )?(rock|cliff|mountain)|lean(s|ing)? on|propped|built into the hill", "slope+against_rock"),
    (r"sunken|wreck|sea ?floor|under ?water|seabed", "underwater"),
    (r"hanging from|cave ceiling", "cave_ceiling"),
    (r"in(side)? (a|the) caves?|cave floor|underground", "cave_floor"),
    (r"carved into|dwarven halls|inside the mountain", "carve"),
    (r"floating island|floatland|in the sky", "floatland"),
    (r"waterfall", "waterfall"),
    (r"hill ?top|summit|peak|overlooking|on top of (a|the) (hill|mountain)", "peak"),
    (r"\bridge\b", "ridge"),
    (r"cliff|edge of a drop|precipice", "cliff"),
    (r"\b(river|bridge|ford|stream)\b", "plain+river"),
    (r"\b(lake|pond)\b", "lake"),
    (r"\b(sea|harbou?r|shore|coast|beach|port)\b", "coast"),
    (r"hillside|slope", "slope"),
    (r"\b(fields?|meadows?|village|plains?|flat|clearing|grassland)\b", "plain"),
]
EXPOSURE = [
    (r"\b(hidden|secret|deep in the forest|in a valley|tucked away)\b", "hidden"),
    (r"landmark|visible from afar|watch(es|ing)? over|towering|seen from far|prominent", "prominent"),
]
RARITY = [  # mapchunks per landmark, the scale in docs/authoring-landmarks.md
    (r"unique|one of a kind|only once|legendary|very rare", 3000),
    (r"\brare\b|seldom|special", 600),
    (r"\b(common|often|everywhere|many|network|chain of)\b", 120),
]
BIOMES = [
    (r"\b(desert|dunes?|sand)\b", ["desert"]),
    (r"savanna|steppe", ["savanna"]),
    (r"jungle|rain ?forest", ["jungle"]),
    (r"swamp|marsh|bog", ["swamp"]),
    (r"\b(cold|north|snowy?|ice|frozen|arctic|tundra)\b", ["tundra", "snow", "taiga"]),
    (r"taiga|pine forest|conifer", ["taiga"]),
    (r"mountain|alpine|highland", ["mountain"]),
    (r"\b(forest|woods)\b", ["forest"]),
    (r"meadow|grassland|field|prairie", ["grassland"]),
    (r"\bbeach\b", ["beach"]),
    (r"ocean|open sea", ["ocean"]),
]
CAVES = {"cave_floor", "cave_ceiling", "carve"}


@dataclass
class Placement:
    site: list[str] = field(default_factory=lambda: ["plain"])
    exposure: str = "any"
    biomes: list[str] = field(default_factory=lambda: ["any"])
    rarity: int = 600
    y_max: int | None = None
    matched: list[str] = field(default_factory=list)  # the words that decided, for the PR text

    def fields(self) -> dict:
        out = {"site": self.site, "exposure": self.exposure, "biomes": self.biomes, "rarity": self.rarity}
        if self.y_max is not None:
            out["y_max"] = self.y_max
        return out


def suggest(text: str) -> Placement:
    """Placement fields for a description like "on sea cliffs in the cold north, rare"."""
    words = text.lower()
    p = Placement()
    sites = []
    for pat, site in SITES:
        m = re.search(pat, words)
        if m and site not in sites:
            sites.append(site)
            p.matched.append(m.group(0))
    if sites:
        p.site = sites[:3]
    for pat, value in EXPOSURE:
        m = re.search(pat, words)
        if m:
            p.exposure = value
            p.matched.append(m.group(0))
            break
    for pat, value in RARITY:
        m = re.search(pat, words)
        if m:
            p.rarity = value
            p.matched.append(m.group(0))
            break
    biomes: list[str] = []
    for pat, tags in BIOMES:
        m = re.search(pat, words)
        if m:
            biomes += [t for t in tags if t not in biomes]
            p.matched.append(m.group(0))
    if biomes:
        p.biomes = biomes
    if any(part in CAVES for s in p.site for part in s.split("+")):
        p.y_max = -20
    return p
