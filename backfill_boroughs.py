#!/usr/bin/env python3
"""
backfill_boroughs.py — Patch data/galleries.json in-place:

  1. For every existing feature that has no 'borough' field, reverse-geocode
     its coordinates via Mapbox to detect the borough.
  2. Append the 9 curated Queens / Bronx / Staten Island venues (forward-
     geocoded from their addresses).
  3. Write the result back to data/galleries.json.

Run once, then commit:

    export MAPBOX_TOKEN='pk.eyJ1...'
    python3 backfill_boroughs.py
"""

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

MAPBOX_TOKEN = os.environ.get("MAPBOX_TOKEN", "").strip()
GALLERIES_PATH = Path("data/galleries.json")
SLEEP = 0.12   # polite pacing between Mapbox calls

_LOCALITY_TO_BOROUGH = {
    "manhattan": "Manhattan",
    "brooklyn": "Brooklyn",
    "queens": "Queens",
    "the bronx": "Bronx",
    "bronx": "Bronx",
    "staten island": "Staten Island",
}

# Curated venues for boroughs with no scraped directory source.
CURATED = [
    # Queens — Long Island City art district
    {"name": "SculptureCenter",              "address": "44-19 Purves St, Long Island City, NY",    "url": "https://www.sculpture-center.org"},
    {"name": "MoMA PS1",                     "address": "22-25 Jackson Ave, Long Island City, NY",  "url": "https://www.moma.org/ps1"},
    {"name": "Flux Factory",                 "address": "39-31 29th St, Long Island City, NY",      "url": "https://fluxfactory.org"},
    {"name": "Dorsky Gallery",               "address": "11-03 45th Ave, Long Island City, NY",     "url": "https://www.dorsky.org"},
    # Bronx
    {"name": "The Bronx Museum of the Arts", "address": "1040 Grand Concourse, Bronx, NY",          "url": "https://www.bronxmuseum.org"},
    {"name": "Bronx River Art Center",       "address": "32 W Fordham Rd, Bronx, NY",               "url": "https://bronxriverart.org"},
    {"name": "Longwood Arts Project",        "address": "450 Grand Concourse, Bronx, NY",           "url": "https://bronxcouncilonthearts.org"},
    # Staten Island
    {"name": "Newhouse Center for Contemporary Art", "address": "1000 Richmond Terrace, Staten Island, NY", "url": "https://www.snug-harbor.org"},
    {"name": "Staten Island Museum",         "address": "75 Stuyvesant Pl, Staten Island, NY",      "url": "https://statenislandmuseum.org"},
]

NYC_BBOX = (-74.260, 40.490, -73.700, 40.930)


def _borough_from_context(context: list) -> str:
    for item in context:
        if _LOCALITY_TO_BOROUGH.get(item.get("text", "").lower()):
            return _LOCALITY_TO_BOROUGH[item["text"].lower()]
    return ""


def reverse_geocode(lon: float, lat: float) -> str:
    """Return the NYC borough for (lon, lat), or '' if not found."""
    url = (
        f"https://api.mapbox.com/geocoding/v5/mapbox.places/{lon},{lat}.json"
        f"?access_token={MAPBOX_TOKEN}&types=locality,place&limit=1"
    )
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return ""
    features = r.json().get("features") or []
    if not features:
        return ""
    # The top result itself might be a locality
    text = features[0].get("text", "").lower()
    if text in _LOCALITY_TO_BOROUGH:
        return _LOCALITY_TO_BOROUGH[text]
    return _borough_from_context(features[0].get("context", []))


def forward_geocode(query: str) -> tuple[float, float, str] | None:
    """Return (lon, lat, borough) for an address query, or None."""
    url = (
        f"https://api.mapbox.com/geocoding/v5/mapbox.places/{quote(query)}.json"
        f"?access_token={MAPBOX_TOKEN}"
        f"&proximity=-73.97,40.72"
        f"&bbox={','.join(str(x) for x in NYC_BBOX)}"
        f"&limit=1"
    )
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return None
    features = r.json().get("features") or []
    if not features:
        return None
    lon, lat = features[0]["center"]
    borough = _borough_from_context(features[0].get("context", []))
    return lon, lat, borough


def main():
    if not MAPBOX_TOKEN:
        print("ERROR: set MAPBOX_TOKEN before running.")
        print("  export MAPBOX_TOKEN='pk.eyJ1...'")
        sys.exit(1)

    geojson = json.loads(GALLERIES_PATH.read_text())
    features = geojson["features"]

    # ── Step 1: backfill borough on existing features ──────────────────────
    print(f"Step 1/2 — Reverse-geocoding {len(features)} existing galleries")
    patched = 0
    for i, feat in enumerate(features, 1):
        props = feat["properties"]
        if props.get("borough"):
            print(f"  [{i:3d}/{len(features)}] skip (already tagged): {props['name']}")
            continue
        lon, lat = feat["geometry"]["coordinates"]
        borough = reverse_geocode(lon, lat)
        props["borough"] = borough
        patched += 1
        print(f"  [{i:3d}/{len(features)}] {props['name']!r} → {borough or '?'}")
        time.sleep(SLEEP)
    print(f"  Patched {patched} features.\n")

    # ── Step 2: append curated Queens / Bronx / Staten Island venues ───────
    existing_names = {f["properties"]["name"].lower() for f in features}
    print(f"Step 2/2 — Forward-geocoding {len(CURATED)} curated venues")
    added = 0
    for g in CURATED:
        if g["name"].lower() in existing_names:
            print(f"  SKIP (duplicate): {g['name']}")
            continue
        result = forward_geocode(g["address"])
        if not result:
            print(f"  SKIP (no geocode): {g['name']}")
            continue
        lon, lat, borough = result
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "name": g["name"],
                "address": g["address"],
                "url": g["url"],
                "borough": borough,
                "updated": False,
            },
        })
        existing_names.add(g["name"].lower())
        added += 1
        print(f"  {g['name']!r} → {lon:.4f},{lat:.4f} [{borough or '?'}]")
        time.sleep(SLEEP)
    print(f"  Added {added} new venues.\n")

    GALLERIES_PATH.write_text(json.dumps(geojson, indent=2))
    print(f"Done. Wrote {len(features)} total features to {GALLERIES_PATH}")
    print("Commit and push to make the changes live.")


if __name__ == "__main__":
    main()
