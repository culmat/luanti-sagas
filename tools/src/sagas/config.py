"""saga.toml: the source of truth for one saga (schema, defaults, validation)."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from . import vocab
from .errors import ConfigError

ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,31}$")
SOURCE_KINDS = ("mesh", "vox", "voxels", "handbuilt", "none")
AI_VALUES = ("none", "assisted", "generated")
UP_VALUES = ("auto", "x", "y", "z", "-x", "-y", "-z")
ANCHORS = ("bottom-center", "bottom-min", "center")
VOXEL_MODES = ("shell", "solid")
MATERIAL_MODES = ("palette", "classes", "hybrid")
RULE_MATCH_KEYS = {"material", "part", "color", "tol", "y", "y_frac", "normal"}
NORMALS = ("up", "down", "side")

# Licences ContentDB accepts for media (SPDX). NC/ND are never allowed.
LICENSE_ALLOWLIST = (
    "CC0-1.0",
    "CC-BY-3.0",
    "CC-BY-4.0",
    "CC-BY-SA-3.0",
    "CC-BY-SA-4.0",
    "MIT",
)
SHARE_ALIKE = ("CC-BY-SA-3.0", "CC-BY-SA-4.0")


@dataclass
class Source:
    kind: str = "mesh"
    url: str = ""
    manual: bool = False
    instructions: str = ""
    file: str = ""
    member: str = ""
    sha256: str = ""
    author: str = ""
    author_url: str = ""
    license: str = ""
    license_url: str = ""
    ai: str = "none"
    notes: str = ""


@dataclass
class Transform:
    up: str = "auto"
    rotate_y: int = 0
    mirror: str = ""
    target_size: int = 48
    scale: float = 0.0
    anchor: str = "bottom-center"
    trim_below: float = 0.0
    trim_above: float = 1.0


@dataclass
class Voxel:
    mode: str = "shell"
    supersample: int = 2
    close_radius: int = 0
    min_component: int = 8
    interior: str = "carve"  # carve: enclosed air replaces terrain; keep: leave terrain
    interior_close: int = 2  # per-layer closing radius used to find rooms behind doors/windows
    exclude: list[str] = field(default_factory=list)  # globs on part or material names (collision meshes, LODs)


@dataclass
class Rule:
    match: dict[str, Any]
    cls: str = ""  # target class (classes/hybrid)
    color: bool = False  # route to the palette node


@dataclass
class Materials:
    mode: str = "classes"
    default: str = "stone"
    context: str = "surroundings"
    overrides: dict[str, str] = field(default_factory=dict)
    value_budget: dict[str, int] = field(default_factory=dict)
    rules: list[Rule] = field(default_factory=list)


@dataclass
class Ruin:
    enabled: bool = False
    erosion: float = 0.0
    variation: float = 0.0
    debris_height: int = 0
    moss: float = 0.0
    seed: int = 0


@dataclass
class Placement:
    site: list[str] = field(default_factory=lambda: ["plain"])
    exposure: str = "any"
    biomes: list[str] = field(default_factory=lambda: ["any"])
    rarity: int = 400
    y_min: int = 1
    y_max: int = 300
    rotation: str = "random"
    foundation: int = 12  # max foundation depth in nodes, 0 = none
    clear_above: bool = True
    large: bool = False
    min_distance: int = 0  # 0 = automatic
    hints: str = ""


@dataclass
class Saga:
    id: str
    theme: str
    title: str
    path: Path
    tags: list[str] = field(default_factory=list)
    schema: int = 1
    source: Source = field(default_factory=Source)
    transform: Transform = field(default_factory=Transform)
    voxel: Voxel = field(default_factory=Voxel)
    materials: Materials = field(default_factory=Materials)
    ruin: Ruin = field(default_factory=Ruin)
    placement: Placement = field(default_factory=Placement)
    lore: str = ""

    @property
    def dir(self) -> Path:
        return self.path.parent

    @property
    def qualified_id(self) -> str:
        return f"{self.theme}:{self.id}"

    @property
    def vx_path(self) -> Path:
        return self.dir / "voxels.vx.gz"

    @property
    def preview_path(self) -> Path:
        return self.dir / "preview.png"


def _build(cls, data: dict, where: str):
    known = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {', '.join(unknown)}")
    obj = cls()
    for f in fields(cls):
        if f.name in data:
            value = data[f.name]
            default = getattr(obj, f.name)
            if isinstance(default, bool) and not isinstance(value, bool):
                raise ConfigError(f"{where}.{f.name}: expected true/false")
            if isinstance(default, float) and isinstance(value, int) and not isinstance(value, bool):
                value = float(value)
            if isinstance(default, int) and not isinstance(default, bool) and isinstance(value, bool):
                raise ConfigError(f"{where}.{f.name}: expected a number")
            setattr(obj, f.name, value)
    return obj


def _rules(raw: list, where: str) -> list[Rule]:
    rules = []
    for i, r in enumerate(raw):
        w = f"{where}[{i}]"
        if not isinstance(r, dict) or "match" not in r:
            raise ConfigError(f"{w}: needs a match table")
        extra = set(r) - {"match", "class", "color"}
        if extra:
            raise ConfigError(f"{w}: unknown key(s) {', '.join(sorted(extra))}")
        m = r["match"]
        bad = set(m) - RULE_MATCH_KEYS
        if bad:
            raise ConfigError(f"{w}.match: unknown key(s) {', '.join(sorted(bad))}")
        rules.append(Rule(match=dict(m), cls=r.get("class", ""), color=bool(r.get("color", False))))
    return rules


def parse(data: dict, path: Path) -> Saga:
    where = str(path)
    top = {
        "schema",
        "id",
        "theme",
        "title",
        "tags",
        "source",
        "transform",
        "voxel",
        "materials",
        "ruin",
        "placement",
        "lore",
    }
    unknown = sorted(set(data) - top)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {', '.join(unknown)}")
    for key in ("id", "theme", "title"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ConfigError(f"{where}: '{key}' is required")
    mats = dict(data.get("materials", {}))
    rules = _rules(mats.pop("rules", []), f"{where}: materials.rules")
    placement = dict(data.get("placement", {}))
    if isinstance(placement.get("site"), str):
        placement["site"] = [placement["site"]]
    if isinstance(placement.get("biomes"), str):
        placement["biomes"] = [placement["biomes"]]
    if "rarity" in placement:
        try:
            placement["rarity"] = vocab.rarity_value(placement["rarity"])
        except ValueError as e:
            raise ConfigError(f"{where}: placement.rarity: {e}") from e
    if isinstance(placement.get("foundation"), bool):
        placement["foundation"] = 12 if placement["foundation"] else 0
    lore = data.get("lore", "")
    if isinstance(lore, dict):
        lore = lore.get("text", "")
    saga = Saga(
        id=data["id"],
        theme=data["theme"],
        title=data["title"],
        path=path,
        tags=list(data.get("tags", [])),
        schema=int(data.get("schema", 1)),
        source=_build(Source, data.get("source", {}), f"{where}: source"),
        transform=_build(Transform, data.get("transform", {}), f"{where}: transform"),
        voxel=_build(Voxel, data.get("voxel", {}), f"{where}: voxel"),
        materials=_build(Materials, mats, f"{where}: materials"),
        ruin=_build(Ruin, data.get("ruin", {}), f"{where}: ruin"),
        placement=_build(Placement, placement, f"{where}: placement"),
        lore=lore,
    )
    saga.materials.rules = rules
    validate(saga)
    return saga


def load(path: Path) -> Saga:
    path = Path(path)
    if path.is_dir():
        path = path / "saga.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"{path}: not found") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    return parse(data, path)


def validate(s: Saga) -> None:
    """Structural checks that make a saga unusable. Policy checks live in lint.py."""
    w = str(s.path)
    if not ID_RE.match(s.id):
        raise ConfigError(f"{w}: id {s.id!r} must match {ID_RE.pattern}")
    if not ID_RE.match(s.theme):
        raise ConfigError(f"{w}: theme {s.theme!r} must match {ID_RE.pattern}")
    if s.schema != 1:
        raise ConfigError(f"{w}: unsupported schema {s.schema}")
    src = s.source
    if src.kind not in SOURCE_KINDS:
        raise ConfigError(f"{w}: source.kind must be one of {', '.join(SOURCE_KINDS)}")
    if src.ai not in AI_VALUES:
        raise ConfigError(f"{w}: source.ai must be one of {', '.join(AI_VALUES)}")
    t = s.transform
    if t.up not in UP_VALUES:
        raise ConfigError(f"{w}: transform.up must be one of {', '.join(UP_VALUES)}")
    if t.rotate_y not in (0, 90, 180, 270):
        raise ConfigError(f"{w}: transform.rotate_y must be 0, 90, 180 or 270")
    if t.mirror not in ("", "x", "z"):
        raise ConfigError(f"{w}: transform.mirror must be '', 'x' or 'z'")
    if t.anchor not in ANCHORS:
        raise ConfigError(f"{w}: transform.anchor must be one of {', '.join(ANCHORS)}")
    if not 4 <= t.target_size <= 400:
        raise ConfigError(f"{w}: transform.target_size must be between 4 and 400")
    if not 0.0 <= t.trim_below < t.trim_above <= 1.0:
        raise ConfigError(f"{w}: need 0 <= transform.trim_below < trim_above <= 1")
    v = s.voxel
    if v.mode not in VOXEL_MODES:
        raise ConfigError(f"{w}: voxel.mode must be one of {', '.join(VOXEL_MODES)}")
    if v.interior not in ("carve", "keep"):
        raise ConfigError(f"{w}: voxel.interior must be 'carve' or 'keep'")
    if not 1 <= v.supersample <= 8:
        raise ConfigError(f"{w}: voxel.supersample must be between 1 and 8")
    m = s.materials
    classes = vocab.classes()
    if m.mode not in MATERIAL_MODES:
        raise ConfigError(f"{w}: materials.mode must be one of {', '.join(MATERIAL_MODES)}")
    if m.default not in classes:
        raise ConfigError(f"{w}: materials.default {m.default!r} is not a class")
    if m.context not in vocab.vocabulary()["material_context"]:
        raise ConfigError(f"{w}: materials.context must be surroundings or fixed")
    for cls, target in m.overrides.items():
        if cls not in classes:
            raise ConfigError(f"{w}: materials.overrides: {cls!r} is not a class")
        if target != "fixed" and target not in classes:
            raise ConfigError(f"{w}: materials.overrides.{cls}: {target!r} is neither 'fixed' nor a class")
    for cls in m.value_budget:
        if cls not in classes:
            raise ConfigError(f"{w}: materials.value_budget: {cls!r} is not a class")
    for i, r in enumerate(m.rules):
        if r.color == bool(r.cls):
            raise ConfigError(f'{w}: materials.rules[{i}] needs exactly one of class = "..." or color = true')
        if r.cls and r.cls not in classes:
            raise ConfigError(f"{w}: materials.rules[{i}]: {r.cls!r} is not a class")
        n = r.match.get("normal")
        if n is not None and n not in NORMALS:
            raise ConfigError(f"{w}: materials.rules[{i}].match.normal must be up, down or side")
        for key in ("y", "y_frac"):
            if key in r.match:
                rng = r.match[key]
                if not (isinstance(rng, list) and len(rng) == 2 and rng[0] <= rng[1]):
                    raise ConfigError(f"{w}: materials.rules[{i}].match.{key} must be [low, high]")
        if "color" in r.match:
            try:
                vocab.hex_to_rgb(r.match["color"])
            except (ValueError, AttributeError) as e:
                raise ConfigError(f"{w}: materials.rules[{i}].match.color: {e}") from e
    p = s.placement
    if not p.site:
        raise ConfigError(f"{w}: placement.site needs at least one alternative")
    for expr in p.site:
        try:
            vocab.parse_site(expr)
        except ValueError as e:
            raise ConfigError(f"{w}: placement.site: {e}") from e
    voc = vocab.vocabulary()
    if p.exposure not in voc["exposure"]:
        raise ConfigError(f"{w}: placement.exposure must be one of {', '.join(voc['exposure'])}")
    bad = [b for b in p.biomes if b not in voc["biome_tags"]]
    if bad or not p.biomes:
        raise ConfigError(f"{w}: placement.biomes: unknown tag(s) {', '.join(bad) or '(empty)'}")
    if p.rotation not in voc["rotation"]:
        raise ConfigError(f"{w}: placement.rotation must be one of {', '.join(voc['rotation'])}")
    if p.y_min > p.y_max:
        raise ConfigError(f"{w}: placement.y_min > y_max")
    if not 0 <= p.foundation <= 64:
        raise ConfigError(f"{w}: placement.foundation must be 0..64 (depth in nodes) or true/false")
    r = s.ruin
    for key in ("erosion", "variation", "moss"):
        if not 0.0 <= getattr(r, key) <= 1.0:
            raise ConfigError(f"{w}: ruin.{key} must be between 0 and 1")
