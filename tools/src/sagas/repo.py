"""Repository layout: where content, packs and sources live, and how selectors resolve."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .errors import ConfigError, SagasError


@dataclass
class Saga:
    name: str
    title: str
    description: str
    path: Path
    supported_games: str = "minetest_game, mineclonia, mineclone2"
    extra: dict = field(default_factory=dict)

    @property
    def pack(self) -> str:
        return f"sagas_{self.name}"


@dataclass
class Repo:
    root: Path

    @property
    def content(self) -> Path:
        return self.root / "content"

    @property
    def mods(self) -> Path:
        return self.root / "mods"

    @property
    def core_mod(self) -> Path:
        return self.mods / "sagas"

    @property
    def sources(self) -> Path:
        env = os.environ.get("SAGAS_SOURCES")
        return Path(env).expanduser() if env else self.root / "sources"

    def pack_dir(self, saga: str) -> Path:
        return self.mods / f"sagas_{saga}"

    def sagas(self) -> list[Saga]:
        out = []
        if not self.content.is_dir():
            return out
        for d in sorted(p for p in self.content.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
            out.append(self.saga(d.name))
        return out

    def saga(self, name: str) -> Saga:
        d = self.content / name
        meta: dict = {}
        tf = d / "saga.toml"
        if tf.exists():
            try:
                meta = tomllib.loads(tf.read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError as e:
                raise ConfigError(f"{tf}: {e}") from e
        return Saga(
            name=name,
            title=meta.get("title", f"Sagas: {name.replace('_', ' ').title()}"),
            description=meta.get("description", f"Landmarks of the {name} saga for the sagas mod."),
            path=d,
            supported_games=meta.get("supported_games", "minetest_game, mineclonia, mineclone2"),
            extra=meta,
        )

    def landmark_paths(self, saga: str | None = None) -> list[Path]:
        base = self.content / saga if saga else self.content
        return sorted(base.glob("*/landmark.toml") if saga else base.glob("*/*/landmark.toml"))

    def landmarks(self, saga: str | None = None) -> list[config.Landmark]:
        return [config.load(p) for p in self.landmark_paths(saga)]

    def select(self, selector: str | None) -> list[config.Landmark]:
        """all | <saga> | <saga>/<id> | <id> | path to a landmark dir or landmark.toml."""
        if not selector or selector == "all":
            return self.landmarks()
        p = Path(selector)
        if (p / "landmark.toml").exists() or (p.name == "landmark.toml" and p.exists()):
            return [config.load(p)]
        if "/" in selector:
            saga, sid = selector.split("/", 1)
            path = self.content / saga / sid / "landmark.toml"
            if not path.exists():
                raise SagasError(f"no landmark {selector!r} ({path} missing)")
            return [config.load(path)]
        if (self.content / selector).is_dir() and not (self.content / selector / "landmark.toml").exists():
            return self.landmarks(selector)
        hits = list(self.content.glob(f"*/{selector}/landmark.toml"))
        if len(hits) == 1:
            return [config.load(hits[0])]
        if not hits:
            raise SagasError(f"no saga or landmark named {selector!r}")
        raise SagasError(f"{selector!r} is ambiguous: {', '.join(str(h.parent) for h in hits)}")


def find_root(start: Path | None = None) -> Repo:
    env = os.environ.get("SAGAS_ROOT")
    if env:
        return Repo(Path(env).expanduser().resolve())
    cur = (start or Path.cwd()).resolve()
    for d in (cur, *cur.parents):
        if (d / "content").is_dir() and (d / "mods").is_dir():
            return Repo(d)
    raise SagasError("not inside a sagas repository (no content/ and mods/ found); use --root or SAGAS_ROOT")
