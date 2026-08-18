#!/usr/bin/env python3
"""
fix_geocoding.py — Repairs galleries whose coordinates landed in the wrong borough.

The problem
-----------
About thirty galleries in data/galleries.json carry Tribeca and SoHo addresses but
coordinates in Brooklyn. Measured against their real locations they are wrong by
3-6 km:

    Luhring Augustine Tribeca   17 White St     stored 6.1 km away, in Brooklyn
    Marian Goodman Gallery      385 Broadway    stored 4.3 km away, in Brooklyn
    ISLAA                       142 Franklin St stored 4.3 km away, in Greenpoint
    Nicodim Gallery             15 Greene St    stored 3.6 km away, in Brooklyn
    Peter Blum Gallery          176 Grand St    stored 3.4 km away, in Brooklyn

The cause is street-name collision. Broadway, White Street, Leonard Street, Grand
Street, Franklin Street and Greene Street all exist in BOTH Manhattan and Brooklyn.
When an address was geocoded as a bare "176 Grand St" with no borough, the geocoder
was free to resolve it to the Brooklyn one — and often did.

The consequences run through the whole site, because every area page is built from
coordinates: major Manhattan galleries appear on the Brooklyn borough page and in
the Williamsburg and Greenpoint neighbourhood pages, while Tribeca and SoHo are
missing galleries that genuinely belong to them. The map pins are wrong too.

What this script does
---------------------
Finds every record whose address has no borough, city or ZIP qualifier and whose
borough is not Manhattan, re-geocodes it with the borough spelled out explicitly,
and updates the coordinates and borough only when the new result is confident and
materially different.

It is a dry run unless you pass --apply, and it never edits a record whose address
already names a borough.

    export GOOGLE_PLACES_KEY='AIza...'
    python3 fix_geocoding.py                # show what would change
    python3 fix_geocoding.py --apply        # write data/galleries.json

Afterwards, re-run the build so the pages pick up the corrections:

    python3 build_site.py
"""

import json
import math
import os
import re
import sys
import time
from pathlib import Path

import requests

GALLERIES_PATH = Path("data/galleries.json")
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
GOOGLE_KEY = os.environ.get("GOOGLE_PLACES_KEY", "").strip()

BOROUGH_MARKERS = [
    "manhattan", "brooklyn", "queens", "bronx", "staten island",
    "new york, ny", "long island city", "astoria", "ridgewood",
]

# How far the new coordinate must be from the old one before we treat it as a
# correction rather than noise.
MIN_MOVE_KM = 0.4

ACCEPTABLE_TYPES = {"street_address", "premise", "subpremise", "establishment",
                    "point_of_interest"}


def haversine_km(a, b):
    (lat1, lon1), (lat2, lon2) = a, b
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def is_unqualified(address):
    a = (address or "").lower()
    if not a:
        return False
    if any(m in a for m in BOROUGH_MARKERS):
        return False
    if re.search(r"\b1[01]\d{3}\b", a):      # NYC ZIP
        return False
    return True


def geocode(address, borough):
    """Geocode an address with the borough spelled out. Returns (lat, lon, formatted)."""
    query = f"{address}, {borough}, New York, NY"
    resp = requests.get(GEOCODE_URL, params={"address": query, "key": GOOGLE_KEY},
                        timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "OK" or not data.get("results"):
        return None
    top = data["results"][0]
    if not (set(top.get("types", [])) & ACCEPTABLE_TYPES):
        return None
    if top.get("partial_match"):
        return None
    loc = top["geometry"]["location"]
    return loc["lat"], loc["lng"], top.get("formatted_address", "")


def main():
    apply_changes = "--apply" in sys.argv

    if not GOOGLE_KEY:
        print("GOOGLE_PLACES_KEY is not set.\n")
        print("  export GOOGLE_PLACES_KEY='AIza...'")
        print("  python3 fix_geocoding.py")
        sys.exit(1)

    data = json.loads(GALLERIES_PATH.read_text())
    features = data["features"]

    candidates = [
        f for f in features
        if is_unqualified(f["properties"].get("address"))
        and (f["properties"].get("borough") or "") != "Manhattan"
    ]

    print(f"{len(features)} galleries loaded; {len(candidates)} have an unqualified "
          f"address and a non-Manhattan borough.\n")
    if not candidates:
        print("Nothing to repair.")
        return

    changed, skipped, failed = 0, 0, 0

    for f in candidates:
        p = f["properties"]
        name = p["name"]
        addr = p["address"]
        old_lon, old_lat = f["geometry"]["coordinates"]

        # These addresses are Manhattan street names that collide with Brooklyn ones,
        # so resolve them explicitly against Manhattan.
        try:
            result = geocode(addr, "Manhattan")
        except Exception as e:
            print(f"  ERROR  {name}: {type(e).__name__}: {e}")
            failed += 1
            continue
        time.sleep(0.2)

        if not result:
            print(f"  SKIP   {name}: no confident match for {addr!r}")
            skipped += 1
            continue

        lat, lon, formatted = result
        moved = haversine_km((old_lat, old_lon), (lat, lon))

        if moved < MIN_MOVE_KM:
            print(f"  ok     {name}: already within {moved * 1000:.0f} m")
            skipped += 1
            continue

        print(f"  FIX    {name}")
        print(f"           {addr!r}  ->  {formatted!r}")
        print(f"           ({old_lat:.4f}, {old_lon:.4f}) -> ({lat:.4f}, {lon:.4f})  "
              f"moved {moved:.1f} km")
        print(f"           borough {p.get('borough')!r} -> 'Manhattan'")

        if apply_changes:
            f["geometry"]["coordinates"] = [lon, lat]
            p["borough"] = "Manhattan"
            p["address"] = formatted
        changed += 1

    print()
    print(f"{changed} to fix, {skipped} left alone, {failed} errors.")

    if not apply_changes:
        print("\nDry run — nothing written. Re-run with --apply to save.")
        return

    GALLERIES_PATH.write_text(json.dumps(data, indent=2))
    print(f"\nWrote {GALLERIES_PATH}. Now run:  python3 build_site.py")


if __name__ == "__main__":
    main()
