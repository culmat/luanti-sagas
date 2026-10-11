"""The shared vocabulary (classes, sites, biome tags) that the Lua mod also reads.

`data/vocabulary.json` is the source of truth; `sagas sync-core` copies it to
`mods/sagas/vocabulary.json` so both sides always agree.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import cache
from importlib import resources


@dataclass(frozen=True)
class ClassDef:
    name: str
    rgb: tuple[int, int, int]
    tier: str  # common | limited | precious
    family: str  # stone | wood | ""
    default_cap: int | None  # None = unlimited


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    if len(v) != 6:
        raise ValueError(f"bad colour {value!r}")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def vocabulary_bytes() -> bytes:
    return resources.files("sagas").joinpath("data/vocabulary.json").read_bytes()


def vocabulary_sha256() -> str:
    return hashlib.sha256(vocabulary_bytes()).hexdigest()


@cache
def vocabulary() -> dict:
    return json.loads(vocabulary_bytes())


@cache
def classes() -> dict[str, ClassDef]:
    out = {}
    for name, d in sorted(vocabulary()["classes"].items()):
        out[name] = ClassDef(name, hex_to_rgb(d["rgb"]), d["tier"], d.get("family", ""), d.get("default_cap"))
    return out


def class_names() -> list[str]:
    return list(classes())


def site_primitives() -> list[str]:
    s = vocabulary()["sites"]
    return [*s["terrain"], *s["water"], *s["layer"], *s["any"]]


def parse_site(expr: str) -> list[str]:
    """`cliff+coast` -> ["cliff", "coast"]; raises ValueError on unknown primitives."""
    parts = [p.strip() for p in expr.split("+") if p.strip()]
    if not parts:
        raise ValueError("empty site expression")
    known = set(site_primitives())
    bad = [p for p in parts if p not in known]
    if bad:
        raise ValueError(f"unknown site primitive(s) {', '.join(bad)} in {expr!r}")
    layers = set(vocabulary()["sites"]["layer"])
    if sum(p in layers for p in parts) > 1:
        raise ValueError(f"{expr!r} combines more than one layer primitive")
    return parts


def rarity_value(value: int | str) -> int:
    named = vocabulary()["rarity"]
    if isinstance(value, str):
        if value not in named:
            raise ValueError(f"unknown rarity {value!r} (use a number or one of {', '.join(named)})")
        return int(named[value])
    if value < 1:
        raise ValueError("rarity must be >= 1 (expected mapchunks per landmark)")
    return int(value)
