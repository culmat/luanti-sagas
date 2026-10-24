"""Change landmark.toml from the command line or a pull request comment, keeping its comments.

`set_values` writes dotted keys (`transform.target_size = 24`) with tomlkit and validates the result
with the normal loader; an invalid change is undone. `command` turns the comment commands of the
contribution bot (`/size 24`, `/site cliff+coast`, ...) into such assignments.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import tomlkit

from . import config, vocab
from .errors import SagasError


def parse_value(text: str):
    """A TOML value (`24`, `["a", "b"]`, `true`, `"x"`), or the text itself as a string."""
    try:
        return tomllib.loads(f"v = {text}")["v"]
    except tomllib.TOMLDecodeError:
        return text


def set_values(path: Path, assignments: dict[str, object]) -> config.Landmark:
    old = path.read_text(encoding="utf-8")
    doc = tomlkit.parse(old)
    for key, value in assignments.items():
        *sections, name = key.split(".")
        table = doc
        for part in sections:
            if part not in table:
                table[part] = tomlkit.table()
            table = table[part]
        table[name] = value
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    try:
        return config.load(path)
    except SagasError:
        path.write_text(old, encoding="utf-8")
        raise


FACINGS = ("+x", "-x", "+z", "-z")
HELP = """\
`/size 24` longest side in nodes · `/bigger` · `/smaller` · `/turn 90` · `/up z`
`/site cliff+coast plain` · `/exposure prominent|hidden|any` · `/rarity common|rare|legendary|N`
`/biomes tundra snow` · `/door +z` (or `-z`, `+x`, `-x`, `none`, `auto`)
`/title ...` · `/lore ...` · `/hints ...` · `/rebuild`"""


def command(landmark: config.Landmark, line: str) -> tuple[dict[str, object], str]:
    """(assignments, what changed) for one comment command; `/door <side>` is resolved by the
    caller, which needs a build (see door_opening)."""
    m = re.match(r"^/(\w+)\s*(.*)$", line.strip())
    if not m:
        raise SagasError(f"not a command: {line!r}")
    cmd, arg = m.group(1).lower(), m.group(2).strip()
    t = landmark.transform
    if cmd == "size":
        if not arg.isdigit():
            raise SagasError("/size needs a number, e.g. /size 24")
        return {"transform.target_size": int(arg), "transform.scale": 0.0}, f"size {arg}"
    if cmd in ("bigger", "smaller"):
        f = 1.25 if cmd == "bigger" else 0.8
        n = max(4, min(400, round(t.target_size * f)))
        return {"transform.target_size": n, "transform.scale": 0.0}, f"size {t.target_size} -> {n}"
    if cmd == "turn":
        if arg not in ("90", "180", "270", "0"):
            raise SagasError("/turn takes 90, 180 or 270")
        return {"transform.rotate_y": (t.rotate_y + int(arg)) % 360}, f"turned by {arg}"
    if cmd == "up":
        return {"transform.up": arg}, f"up axis {arg}"
    if cmd == "site":
        sites = arg.split()
        for s in sites:
            try:
                vocab.parse_site(s)
            except ValueError as e:
                raise SagasError(f"/site: {e}") from None
        return {"placement.site": sites}, f"site {' or '.join(sites)}"
    if cmd == "exposure":
        return {"placement.exposure": arg}, f"exposure {arg}"
    if cmd == "rarity":
        value = int(arg) if arg.isdigit() else arg
        try:
            vocab.rarity_value(value)
        except ValueError as e:
            raise SagasError(f"/rarity: {e}") from None
        return {"placement.rarity": value}, f"rarity {arg}"
    if cmd == "biomes":
        return {"placement.biomes": arg.split()}, f"biomes {arg}"
    if cmd in ("title", "lore"):
        return {cmd: arg}, f"{cmd} changed"
    if cmd == "hints":
        return {"placement.hints": arg}, "hints changed"
    if cmd == "door":
        if arg in ("none", "auto"):
            return {"voxel.doorway": arg}, f"doorway {arg}"
        if arg in FACINGS:
            return {}, f"door {arg}"
        raise SagasError("/door takes +x, -x, +z, -z, none or auto")
    if cmd == "rebuild":
        return {}, "rebuilt"
    raise SagasError(f"unknown command /{cmd}; commands:\n{HELP}")


def door_opening(suggestions: list[str], facing: str) -> list[int]:
    """The doorway box the build suggests for one side ("+z [x1, y1, z1, x2, y2, z2]")."""
    for s in suggestions:
        side, _, box = s.partition(" ")
        if side == facing:
            return [int(v) for v in re.findall(r"-?\d+", box)]
    raise SagasError(f"no doorway can be cut facing {facing} (the rooms may already have a way in)")
