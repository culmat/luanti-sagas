"""Source adapters. Each yields Candidates with a free licence; searches are metadata only."""

from __future__ import annotations

import re
from collections.abc import Iterator
from html import unescape

from .. import secrets
from .base import Candidate, Http, RateLimited, check_text, spdx

SKETCHFAB_LICENCES = {"cc0": "CC0-1.0", "by": "CC-BY-4.0", "by-sa": "CC-BY-SA-4.0"}


def _strip_html(s: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def sketchfab(http: Http, saga: str, term: str, limit: int, licences: list[str]) -> Iterator[Candidate]:
    """Sketchfab v3 search. Sketchfab challenges anonymous scripted clients, so set SKETCHFAB_TOKEN
    (your API token from https://sketchfab.com/settings/password). Downloads need a login anyway,
    so promoted landmarks are manual."""
    token = secrets.get("SKETCHFAB_TOKEN")
    headers = {"Authorization": f"Token {token}"} if token else None
    for lic in licences:
        if lic not in SKETCHFAB_LICENCES:
            continue
        params = {
            "type": "models",
            "downloadable": "true",
            "license": lic,
            "q": term,
            "count": min(24, limit),
            "sort_by": "-likeCount",
        }
        try:
            data = http.get_json("https://api.sketchfab.com/v3/search", params, headers=headers)
        except RateLimited as e:
            hint = (
                ""
                if token
                else " (run 'avanti secrets setup' or set SKETCHFAB_TOKEN: anonymous scripts are challenged)"
            )
            raise RateLimited(str(e) + hint) from None
        for r in data.get("results", [])[:limit]:
            user = r.get("user") or {}
            label = (r.get("license") or {}).get("label", "")
            c = Candidate(
                source="sketchfab",
                source_id=r["uid"],
                title=r.get("name", ""),
                url=r.get("viewerUrl", ""),
                author=user.get("displayName") or user.get("username", ""),
                author_url=user.get("profileUrl", ""),
                license=spdx(label) or SKETCHFAB_LICENCES[lic],
                license_label=label,
                faces=r.get("faceCount"),
                formats=sorted((r.get("archives") or {}).keys()),
                download_size=((r.get("archives") or {}).get("gltf") or {}).get("size"),
                thumbnail=max((r.get("thumbnails") or {}).get("images", [{}]), key=lambda i: i.get("width", 0)).get(
                    "url", ""
                ),
                saga=saga,
                query=term,
                download={
                    "manual": True,
                    "file": f"{slug(r.get('name', 'model'))}.zip",
                    "member": "scene.gltf",
                    "instructions": "Sketchfab needs a login: download the model as glTF (zip) from the URL",
                },
            )
            check_text(c, r.get("description", ""), r.get("name", ""))
            yield c


def commons(http: Http, saga: str, term: str, limit: int, licences: list[str]) -> Iterator[Candidate]:
    """Wikimedia Commons 3D files (STL). Licence per file from extmetadata."""
    data = http.get_json(
        "https://commons.wikimedia.org/w/api.php",
        {
            "action": "query",
            "format": "json",
            "list": "search",
            "srnamespace": 6,
            "srlimit": min(20, limit),
            "srsearch": f"filetype:3d {term}",
        },
    )
    titles = [x["title"] for x in data.get("query", {}).get("search", [])]
    if not titles:
        return
    info = http.get_json(
        "https://commons.wikimedia.org/w/api.php",
        {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "titles": "|".join(titles),
        },
    )
    for page in info.get("query", {}).get("pages", {}).values():
        ii = (page.get("imageinfo") or [{}])[0]
        em = ii.get("extmetadata", {})
        label = em.get("LicenseShortName", {}).get("value", "")
        lic = spdx(label)
        if not lic:
            continue
        name = page["title"].removeprefix("File:")
        c = Candidate(
            source="commons",
            source_id=name,
            title=name.rsplit(".", 1)[0],
            url=ii.get("descriptionurl", ""),
            author=_strip_html(em.get("Artist", {}).get("value", "")),
            license=lic,
            license_label=label,
            formats=[name.rsplit(".", 1)[-1].lower()],
            download_size=ii.get("size"),
            saga=saga,
            query=term,
            download={"url": ii.get("url", ""), "file": name.replace(" ", "_")},
            notes="STL without colour: use material rules by height and normal",
        )
        check_text(c, _strip_html(em.get("ImageDescription", {}).get("value", "")), name)
        yield c


def polyhaven(http: Http, saga: str, term: str, limit: int, licences: list[str]) -> Iterator[Candidate]:
    """Poly Haven models (all CC0); matched by name, tags and categories."""
    if "cc0" not in licences:
        return
    assets = http.get_json("https://api.polyhaven.com/assets", {"type": "models"})
    words = term.lower().split()
    n = 0
    for slug_, a in sorted(assets.items()):
        hay = set(
            re.findall(
                r"[a-z0-9]+", " ".join([a.get("name", ""), *a.get("tags", []), *a.get("categories", [])]).lower()
            )
        )
        if not all(w in hay for w in words):
            continue
        c = Candidate(
            source="polyhaven",
            source_id=slug_,
            title=a.get("name", slug_),
            url=f"https://polyhaven.com/a/{slug_}",
            author=", ".join(a.get("authors", {}).keys()),
            license="CC0-1.0",
            license_label="CC0",
            faces=a.get("polycount"),
            formats=["gltf"],
            thumbnail=f"https://cdn.polyhaven.com/asset_img/thumbs/{slug_}.png?height=256",
            saga=saga,
            query=term,
            download={"polyhaven": slug_},
        )
        yield c
        n += 1
        if n >= limit:
            return


def smithsonian(http: Http, saga: str, term: str, limit: int, licences: list[str]) -> Iterator[Candidate]:
    """Smithsonian Open Access records with a 3D package and usage CC0 (api.data.gov key, DEMO_KEY works)."""
    if "cc0" not in licences:
        return
    key = secrets.get("SI_API_KEY", "DEMO_KEY")
    data = http.get_json("https://api.si.edu/openaccess/api/v1.0/search", {"q": term, "rows": 100, "api_key": key})
    n = 0
    for row in data.get("response", {}).get("rows", []):
        dnr = row.get("content", {}).get("descriptiveNonRepeating", {})
        for m in dnr.get("online_media", {}).get("media", []):
            if m.get("type") != "3d_voyager" or (m.get("usage") or {}).get("access") != "CC0":
                continue
            package = m.get("content", "")
            c = Candidate(
                source="smithsonian",
                source_id=row.get("id", package),
                title=row.get("title", ""),
                url=f"https://3d.si.edu/object/3d/{package.rsplit(':', 1)[-1]}" if package else "",
                author=f"Smithsonian Institution ({dnr.get('data_source', '')})".replace(" ()", ""),
                license="CC0-1.0",
                license_label="CC0 (Smithsonian Open Access)",
                formats=["glb"],
                saga=saga,
                query=term,
                download={"voyager": package},
                notes="Voyager GLBs are often Z-up and Draco-compressed; check the package is the object you want",
            )
            yield c
            n += 1
            break
        if n >= limit:
            return


CIV_SAGAS = {
    "britons": "celtic",
    "gauls": "celtic",
    "iberians": "celtic",
    "athenians": "antique",
    "spartans": "antique",
    "macedonians": "antique",
    "romans": "antique",
    "seleucids": "antique",
    "ptolemies": "egyptian",
    "kushites": "egyptian",
    "persians": "persian",
    "han": "asian",
    "mauryas": "asian",
    "carthaginians": "antique",
}
ZEROAD_SHA = "61a3b9507d974084e6badb88a0826bd89a6d5b8b"  # last commit of the archived GitHub mirror


def zeroad(http: Http, saga: str, term: str, limit: int, licences: list[str]) -> Iterator[Candidate]:
    """0 A.D. structure actors (CC-BY-SA 3.0). Matches civilisations whose saga is `saga`."""
    if "by-sa" not in licences:
        return
    base = "https://api.github.com/repos/0ad/0ad/git/trees"
    for civ, civ_saga in sorted(CIV_SAGAS.items()):
        if civ_saga != saga:
            continue
        tree = http.get_json(f"{base}/{ZEROAD_SHA}:binaries/data/mods/public/art/actors/structures/{civ}")
        n = 0
        for entry in tree.get("tree", []):
            name = entry.get("path", "")
            if not name.endswith(".xml") or (term and not any(w in name for w in term.lower().split())):
                continue
            actor = f"art/actors/structures/{civ}/{name}"
            yield Candidate(
                source="zeroad",
                source_id=f"{civ}/{name[:-4]}",
                title=f"0 A.D. {civ} {name[:-4].replace('_', ' ')}",
                url=f"https://github.com/0ad/0ad/blob/{ZEROAD_SHA}/binaries/data/mods/public/{actor}",
                author="Wildfire Games (0 A.D.)",
                author_url="https://play0ad.com",
                license="CC-BY-SA-3.0",
                license_label="CC-BY-SA 3.0 (0 A.D. art)",
                formats=["dae"],
                saga=saga,
                query=term,
                download={"zeroad_actor": actor},
                notes="Read the actor XML for <mesh> and baseTex; use extra_files, voxel.texture, voxel.alpha = ignore",
            )
            n += 1
            if n >= limit:
                break


SOURCES = {
    "sketchfab": sketchfab,
    "commons": commons,
    "polyhaven": polyhaven,
    "smithsonian": smithsonian,
    "zeroad": zeroad,
}


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:40] or "model"
