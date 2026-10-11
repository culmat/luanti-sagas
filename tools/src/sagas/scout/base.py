"""Candidate records, licence normalisation, polite HTTP with an on-disk cache."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

USER_AGENT = "luanti-sagas-scout/0.1 (+https://github.com/culmat/luanti-sagas)"
CACHE = Path(os.environ.get("SAGAS_CACHE", Path.home() / ".cache" / "sagas" / "scout"))
CACHE_SECONDS = 24 * 3600

# raw licence labels -> SPDX (only free ones; anything else is dropped)
LICENCE_MAP = {
    "cc0": "CC0-1.0",
    "cc0 public domain": "CC0-1.0",
    "cc0 1.0": "CC0-1.0",
    "public domain": "CC0-1.0",
    "cc attribution": "CC-BY-4.0",
    "by": "CC-BY-4.0",
    "cc by 4.0": "CC-BY-4.0",
    "cc-by-4.0": "CC-BY-4.0",
    "cc by 3.0": "CC-BY-3.0",
    "cc-by-3.0": "CC-BY-3.0",
    "cc attribution-sharealike": "CC-BY-SA-4.0",
    "by-sa": "CC-BY-SA-4.0",
    "cc by-sa 4.0": "CC-BY-SA-4.0",
    "cc-by-sa-4.0": "CC-BY-SA-4.0",
    "cc by-sa 3.0": "CC-BY-SA-3.0",
    "cc-by-sa-3.0": "CC-BY-SA-3.0",
    "mit": "MIT",
}

NC_ND = re.compile(
    r"non[- ]?commercial|\bby-nc\b|\bnc\b|no[- ]?deriv|\bby-nd\b|all rights reserved|editorial", re.IGNORECASE
)
TRADEMARK = re.compile(
    r"\b(smaug|disney|marvel|pokemon|pokémon|lego|warhammer|star wars|minecraft|zelda|"
    r"game of thrones|lord of the rings|harry potter|mario)\b",
    re.IGNORECASE,
)


def spdx(label: str) -> str | None:
    return LICENCE_MAP.get((label or "").strip().lower())


@dataclass
class Candidate:
    source: str
    source_id: str
    title: str
    url: str
    author: str = ""
    author_url: str = ""
    license: str = ""  # SPDX
    license_label: str = ""
    faces: int | None = None
    formats: list[str] = field(default_factory=list)
    download_size: int | None = None
    thumbnail: str = ""
    saga: str = ""
    query: str = ""
    suggested_site: list[str] = field(default_factory=list)
    suggested_biomes: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    download: dict = field(default_factory=dict)  # how `promote` fills [source]
    notes: str = ""
    first_seen: str = ""

    @property
    def id(self) -> str:
        return f"{self.source}:{self.source_id}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["id"] = self.id
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Candidate:
        d = {k: v for k, v in d.items() if k != "id"}
        return cls(**d)


def check_text(c: Candidate, *texts: str) -> None:
    """Flag NC/ND wording and trademarked characters found in descriptions or titles."""
    blob = " ".join(t for t in texts if t)
    if NC_ND.search(blob):
        c.flags.append("licence-conflict")
    if TRADEMARK.search(blob):
        c.flags.append("trademark")


class RateLimited(RuntimeError):
    pass


HOST_DELAY = {"api.sketchfab.com": 2.0, "api.si.edu": 2.0}  # seconds between requests per host


class Http:
    """GET JSON politely: identify ourselves, wait between requests, cache responses for a day.

    A host that rate-limits us is skipped for the rest of the run instead of being retried for minutes."""

    def __init__(self, rps: float | None = None, refresh: bool = False):
        import httpx

        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=30, follow_redirects=True
        )
        self.delay = 1.0 / float(rps or os.environ.get("SAGAS_SCOUT_RPS", 2))
        self.refresh = refresh
        self.last = 0.0
        self.blocked: set[str] = set()

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None) -> dict:
        from urllib.parse import urlparse

        key = hashlib.sha1((url + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()
        path = CACHE / f"{key}.json"
        if not self.refresh and path.exists() and time.time() - path.stat().st_mtime < CACHE_SECONDS:
            return json.loads(path.read_text())
        host = urlparse(url).netloc
        if host in self.blocked:
            raise RateLimited(f"{host} rate-limited us earlier in this run")
        host_delay = HOST_DELAY.get(host, self.delay)
        for attempt in range(2):
            wait = max(self.delay, host_delay) - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            r = self.client.get(url, params=params, headers=headers)
            self.last = time.time()
            # 202 with an empty body is a bot-protection challenge (seen on Sketchfab): back off like a 429
            if r.status_code in (429, 503) or (r.status_code == 202 and not r.content):
                retry = r.headers.get("Retry-After", "")
                if attempt == 0 and retry.isdigit() and int(retry) <= 30:
                    time.sleep(int(retry))
                    continue
                self.blocked.add(host)
                raise RateLimited(f"{host} answered {r.status_code}; skipping it for this run")
            r.raise_for_status()
            try:
                data = r.json()
            except ValueError:
                raise RuntimeError(f"{host} returned non-JSON ({r.status_code}): {r.text[:80]!r}") from None
            CACHE.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data))
            return data
        self.blocked.add(host)
        raise RateLimited(f"{host} kept rate-limiting")
