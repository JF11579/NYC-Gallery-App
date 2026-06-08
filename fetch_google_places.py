#!/usr/bin/env python3
"""
fetch_google_places.py — Supplement galleries.json with Google Places data.

Searches for art galleries in Chelsea and Brooklyn (Bushwick, DUMBO,
Williamsburg) — neighborhoods not reachable by the existing scrapers.
Merges new finds into data/galleries.json without overwriting existing entries.

Run once locally after build_gallery_list.py:

    export GOOGLE_PLACES_KEY='AIza...'
    python3 fetch_google_places.py

Then commit data/galleries.json and push.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import requests

GOOGLE_KEY = os.environ.get("GOOGLE_PLACES_KEY", "").strip()
GALLERIES_PATH = Path("data/galleries.json")

# One search query per neighborhood. Each returns up to 60 results (3 pages).
SEARCHES = [
    "art gallery Chelsea Manhattan New York",
    "art gallery Bushwick Brooklyn New York",
    "art gallery DUMBO Brooklyn New York",
    "art gallery Williamsburg Brooklyn New York",
]

# Manhattan + Brooklyn bounding box (lon_min, lat_min, lon_max, lat_max)
COVERAGE_BBOX = (-74.060, 40.570, -73.830, 40.880)


def in_coverage_area(lon: float, lat: float) -> bool:
    lo_min, la_min, lo_max, la_max = COVERAGE_BBOX
    return lo_min <= lon <= lo_max and la_min <= lat <= la_max


def text_search(query: str) -> list[dict]:
    """Run a Places Text Search with pagination. Returns up to 60 place dicts."""
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    results = []
    params = {"query": query, "type": "art_gallery", "key": GOOGLE_KEY}

    while True:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        status = data.get("status")
        if status == "ZERO_RESULTS":
            break
        if status != "OK":
            print(f"  WARN: Places API returned {status!r} for {query!r}")
            break
        results.extend(data.get("results", []))
        token = data.get("next_page_token")
        if not token:
            break
        time.sleep(2)  # Google requires a short delay before next_page_token is valid
        params = {"pagetoken": token, "key": GOOGLE_KEY}

    return results


def get_website(place_id: str) -> str:
    """Fetch a gallery's website via Place Details (one extra API call per place)."""
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {"place_id": place_id, "fields": "website", "key": GOOGLE_KEY}
    r = requests.get(url, params=params, timeout=15)
    return r.json().get("result", {}).get("website", "")


def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def main():
    if not GOOGLE_KEY:
        print("ERROR: Set GOOGLE_PLACES_KEY environment variable before running.")
        print("  export GOOGLE_PLACES_KEY='AIza...'")
        sys.exit(1)

    geojson = json.loads(GALLERIES_PATH.read_text())
    existing_keys = {normalize(f["properties"]["name"]) for f in geojson["features"]}
    print(f"Loaded {len(geojson['features'])} existing galleries\n")

    new_features = []

    for query in SEARCHES:
        print(f"Searching: {query!r}")
        places = text_search(query)
        print(f"  {len(places)} results from Places API")

        added = 0
        for place in places:
            name = place.get("name", "")
            if not name or normalize(name) in existing_keys:
                continue

            loc = place.get("geometry", {}).get("location", {})
            lat, lon = loc.get("lat"), loc.get("lng")
            if lat is None or not in_coverage_area(lon, lat):
                continue

            address = place.get("formatted_address", "")
            place_id = place.get("place_id", "")
            website = get_website(place_id) if place_id else ""
            time.sleep(0.1)

            new_features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "name": name,
                    "address": address,
                    "url": website,
                    "updated": False,
                },
            })
            existing_keys.add(normalize(name))
            added += 1
            print(f"    + {name}")

        print(f"  Added {added} new galleries\n")

    geojson["features"].extend(new_features)
    GALLERIES_PATH.write_text(json.dumps(geojson, indent=2))
    print(f"Done. Total: {len(geojson['features'])} galleries (+{len(new_features)} new)")


if __name__ == "__main__":
    main()
