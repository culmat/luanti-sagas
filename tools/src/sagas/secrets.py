"""Tokens from the environment, else from avanti's secrets file (avanti secrets setup).

The file is ${XDG_CONFIG_HOME:-~/.config}/avanti/secrets.env with NAME=value lines; it is parsed,
never executed, and only the names asked for are returned.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_LINE = re.compile(r"^([A-Z_][A-Z0-9_]*)=(.*)$")


def secrets_file() -> Path:
    if os.environ.get("AVANTI_SECRETS"):
        return Path(os.environ["AVANTI_SECRETS"])
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "avanti" / "secrets.env"


def get(name: str, default: str = "") -> str:
    if os.environ.get(name):
        return os.environ[name]
    p = secrets_file()
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            m = _LINE.match(line)
            if m and m.group(1) == name:
                return m.group(2)
    return default
