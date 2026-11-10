#!/usr/bin/env python3
"""
discover_galleries.py — Find galleries missing from data/galleries.json.

Why this exists: fetch_google_places.py ran ONE text search per neighbourhood,
and Google returns at most 60 results per search. Dense districts were cut off
at 60, so whole buildings were missing — the Fuller Building (41 E 57th St)
houses well over a dozen galleries and the site listed one. A Reddit reader
caught it.

How it works: each gallery district is a rectangle. A rectangle is searched
with Places API (New) Text Search, restricted to that rectangle. If a search
comes back full (60 results — the cap), the rectangle is split into four and
each quarter is searched again, until every tile returns fewer than 60. That
makes the search exhaustive regardless of density, and sparse areas stay cheap.

Nothing is written to galleries.json. New finds go to data/candidates.json for
review; merge_candidates.py adds the approved ones.

Setup: put the key in .env (git-ignored) as one line:
    GOOGLE_PLACES_KEY=AIza...
The key needs "Places API (New)" enabled.

Usage:
    python3 discover_galleries.py              # all districts
    python3 discover_galleries.py ues chelsea  # only some
    python3 discover_galleries.py --max-calls 50
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

ENV_PATH = Path(".env")
GALLERIES_PATH = Path("data/galleries.json")
CANDIDATES_PATH = Path("data/candidates.json")

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join([
    "places.id", "places.displayName", "places.formattedAddress",
    "places.location", "places.websiteUri", "places.types",
    "places.primaryType", "places.businessStatus",
    "places.regularOpeningHours", "nextPageToken",
])
CAP = 60  # Google's maximum results per search (3 pages of 20)

# (south, west, north, east). Generous on purpose — the tiling is what keeps
# each search under the cap, so the boxes can be loose.
DISTRICTS = {
    "chelsea":    (40.740, -74.012, 40.758, -73.995),
    "ues":        (40.757, -73.982, 40.790, -73.950),  # incl. 57th St / Fuller Bldg
    "downtown":   (40.710, -74.014, 40.730, -73.975),  # Tribeca, SoHo, Chinatown, LES
    "eastvillage":(40.720, -73.998, 40.735, -73.975),
    "harlem":     (40.800, -73.960, 40.830, -73.930),
    "williamsburg":(40.700, -73.970, 40.730, -73.935),
    "bushwick":   (40.690, -73.940, 40.715, -73.905),
    "greenpoint": (40.720, -73.962, 40.740, -73.940),
    "dumbo":      (40.697, -73.995, 40.707, -73.980),
    "lic":        (40.738, -73.960, 40.758, -73.930),
}

# Buildings that house many galleries. Area searches under-count these (the
# Fuller Building returned 5 tenants by area, 9 when searched by address), so
# each gets its own address search. Add buildings here as readers report them.
BUILDINGS = [
    "41 E 57th St",      # Fuller Building
    "24 W 57th St",
    "980 Madison Ave",
    "529 W 20th St",
    "547 W 27th St",
    "535 W 22nd St",
    "508 W 26th St",
    "526 W 26th St",
    "511 W 25th St",
    "530 W 25th St",
    "548 W 28th St",
    "55 Walker St",
    "370 Broadway",
    "88 Eldridge St",
]
MANHATTAN = (40.700, -74.020, 40.830, -73.930)


def street_key(address: str) -> str:
    a = address.lower().split(",")[0]
    a = re.sub(r"\b(west)\b", "w", a)
    a = re.sub(r"\b(east)\b", "e", a)
    a = re.sub(r"\bstreet\b", "st", a)
    a = re.sub(r"\bavenue\b", "ave", a)
    m = re.match(r"\s*(\d+)\s+([nsew]\s+)?(\w+)", a)
    return " ".join(x.strip() for x in m.groups() if x) if m else ""


def walk_in_status(place: dict) -> tuple[str, str]:
    """('walk-in' | 'check', human-readable hours)."""
    hours = place.get("regularOpeningHours") or {}
    periods = hours.get("periods") or []
    days = {p.get("open", {}).get("day") for p in periods}
    text = "; ".join(hours.get("weekdayDescriptions") or [])
    if len(days) >= 3:
        return "walk-in", text
    return "check", text or "no hours on Google"


# Places tagged art_gallery that are not exhibition galleries.
NOT_A_GALLERY = re.compile(
    r"\b(fram(e|es|ing)|tattoo|photo ?booth|portrait studio|art supply|"
    r"auction|antiques?|furniture|rug|jewel|interior|decor|print shop|"
    r"paint ?(and|&|n) ?sip|kids|children|school|academy|class(es)?)\b",
    re.I,
)


def load_key() -> str:
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if line.strip().startswith("GOOGLE_PLACES_KEY="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("gallery", ""))


def borough_of(address: str) -> str:
    a = address.lower()
    if "brooklyn" in a:
        return "Brooklyn"
    if "bronx" in a:
        return "Bronx"
    if "staten island" in a:
        return "Staten Island"
    if any(q in a for q in ("queens", "long island city", "astoria", "ridgewood")):
        return "Queens"
    if "new york, ny" in a:
        return "Manhattan"
    return ""


class Searcher:
    def __init__(self, key: str, max_calls: int):
        self.key = key
        self.max_calls = max_calls
        self.calls = 0

    def search(self, box, query="art gallery", strict=True) -> list[dict]:
        """All results for one rectangle (up to the 60 cap)."""
        s, w, n, e = box
        body = {
            "textQuery": query,
            "pageSize": 20,
            "locationRestriction": {"rectangle": {
                "low": {"latitude": s, "longitude": w},
                "high": {"latitude": n, "longitude": e},
            }},
        }
        if strict:
            body["includedType"] = "art_gallery"
            body["strictTypeFiltering"] = True
        headers = {"X-Goog-Api-Key": self.key, "X-Goog-FieldMask": FIELD_MASK}
        out = []
        while True:
            if self.calls >= self.max_calls:
                raise RuntimeError(f"stopped at --max-calls {self.max_calls}")
            self.calls += 1
            r = requests.post(SEARCH_URL, json=body, headers=headers, timeout=20)
            if r.status_code != 200:
                raise RuntimeError(f"Places API {r.status_code}: {r.text[:300]}")
            data = r.json()
            out.extend(data.get("places", []))
            token = data.get("nextPageToken")
            if not token:
                return out
            body["pageToken"] = token
            time.sleep(1.5)

    def search_tiled(self, box, depth=0) -> list[dict]:
        found = self.search(box)
        if len(found) < CAP or depth >= 5:
            if len(found) >= CAP:
                print(f"    WARN: tile still full at depth {depth}: {box}")
            return found
        s, w, n, e = box
        mlat, mlon = (s + n) / 2, (w + e) / 2
        quarters = [(s, w, mlat, mlon), (s, mlon, mlat, e),
                    (mlat, w, n, mlon), (mlat, mlon, n, e)]
        print(f"    {'  ' * depth}tile full -> splitting into 4")
        results = []
        for q in quarters:
            results.extend(self.search_tiled(q, depth + 1))
        return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("districts", nargs="*", help=f"subset of: {', '.join(DISTRICTS)}")
    ap.add_argument("--max-calls", type=int, default=300,
                    help="hard stop on billed API calls (default 300)")
    args = ap.parse_args()

    key = load_key()
    if not key:
        sys.exit("No GOOGLE_PLACES_KEY in .env — see the docstring.")

    names = args.districts or list(DISTRICTS)
    unknown = [d for d in names if d not in DISTRICTS]
    if unknown:
        sys.exit(f"Unknown district(s): {unknown}")

    features = json.loads(GALLERIES_PATH.read_text())["features"]
    existing = {normalize(f["properties"]["name"]) for f in features}

    searcher = Searcher(key, args.max_calls)
    by_id = {}
    try:
        for d in names:
            print(f"{d}:")
            places = searcher.search_tiled(DISTRICTS[d])
            for p in places:
                p["_district"] = d
                by_id[p["id"]] = p
            print(f"  {len(places)} results ({searcher.calls} calls so far)")
        if not args.districts:
            print("buildings:")
            for b in BUILDINGS:
                want = street_key(b)
                hits = 0
                for q in (f"art galleries at {b} New York", f"art dealer {b} New York"):
                    for p in searcher.search(MANHATTAN, query=q, strict=False):
                        if street_key(p.get("formattedAddress", "")) == want and \
                                "art_gallery" in p.get("types", []):
                            p.setdefault("_district", "building:" + b)
                            by_id.setdefault(p["id"], p)
                            hits += 1
                print(f"  {b}: {hits} gallery results ({searcher.calls} calls so far)")
    except RuntimeError as e:
        print(f"\nSTOPPED: {e}\nSaving what was found so far.")

    candidates, skipped = [], {"already listed": 0, "closed": 0, "not a gallery": 0}
    for p in by_id.values():
        name = p.get("displayName", {}).get("text", "")
        if p.get("businessStatus", "OPERATIONAL") != "OPERATIONAL":
            skipped["closed"] += 1
            continue
        if normalize(name) in existing:
            skipped["already listed"] += 1
            continue
        if NOT_A_GALLERY.search(name):
            skipped["not a gallery"] += 1
            continue
        address = p.get("formattedAddress", "")
        loc = p.get("location", {})
        status, hours = walk_in_status(p)
        candidates.append({
            "approve": None,  # set true/false during review
            "walk_in": status,
            "hours": hours,
            "name": name,
            "address": address,
            "url": p.get("websiteUri", ""),
            "borough": borough_of(address),
            "lat": loc.get("latitude"),
            "lon": loc.get("longitude"),
            "district": p["_district"],
            "primary_type": p.get("primaryType", ""),
            "place_id": p["id"],
        })

    candidates.sort(key=lambda c: (c["district"], c["address"]))
    CANDIDATES_PATH.write_text(json.dumps(candidates, indent=2, ensure_ascii=False))
    print(f"\n{searcher.calls} API calls. {len(by_id)} unique places.")
    print(f"Skipped: {skipped}")
    print(f"{len(candidates)} new candidates -> {CANDIDATES_PATH}")


if __name__ == "__main__":
    main()
