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

Two geocoders are supported. OpenStreetMap's Nominatim needs no API key and is
the default, so this runs with no setup at all:

    python3 fix_geocoding.py                # dry run, uses OpenStreetMap
    python3 fix_geocoding.py --apply        # write data/galleries.json

Google is used instead when a key is present, which is worth doing if you have
one since it agrees with the rest of the dataset's provenance:

    export GOOGLE_PLACES_KEY='<your real key>'
    python3 fix_geocoding.py --apply

Force a provider with --provider osm or --provider google.

Afterwards, re-run the build so the pages pick up the corrections:

    python3 build_site.py
    python3 validate_data.py
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

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_UA = ("NYCGalleryTracker/1.0 (borough data repair; "
                "https://nyc-gallery-app.netlify.app)")
# Nominatim's usage policy: no more than one request per second.
OSM_SLEEP = 1.1

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


def geocode_google(address, borough):
    """Geocode via Google. Returns (lat, lon, formatted) or None."""
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


def geocode_osm(address, borough):
    """Geocode via OpenStreetMap Nominatim. No API key required.

    Nominatim's usage policy caps this at one request per second and requires a
    descriptive User-Agent, both of which are honoured here. Thirty records take
    about half a minute.

    We only accept a result that Nominatim itself places in the requested
    borough, which is the whole point — a bare "176 Grand St" is exactly the
    query that went wrong the first time.
    """
    resp = requests.get(
        NOMINATIM_URL,
        params={"q": f"{address}, {borough}, New York, NY", "format": "json",
                "limit": 1, "addressdetails": 1},
        headers={"User-Agent": NOMINATIM_UA},
        timeout=25,
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        return None
    top = results[0]

    # Confirm the result really is in the borough we asked for.
    details = top.get("address", {}) or {}
    haystack = " ".join([
        top.get("display_name", ""),
        details.get("city_district", ""), details.get("suburb", ""),
        details.get("county", ""), details.get("borough", ""),
    ]).lower()
    if borough.lower() == "manhattan":
        if not ("manhattan" in haystack or "new york county" in haystack):
            return None

    return float(top["lat"]), float(top["lon"]), top.get("display_name", "")


def geocode(address, borough, provider):
    if provider == "google":
        return geocode_google(address, borough)
    return geocode_osm(address, borough)


def main():
    apply_changes = "--apply" in sys.argv

    if "--provider" in sys.argv:
        provider = sys.argv[sys.argv.index("--provider") + 1].lower()
        if provider not in ("google", "osm"):
            print("--provider must be 'google' or 'osm'")
            sys.exit(1)
    else:
        provider = "google" if GOOGLE_KEY else "osm"

    if provider == "google" and not GOOGLE_KEY:
        print("--provider google was requested but GOOGLE_PLACES_KEY is not set.")
        print("Either export a real key, or use the no-key geocoder:\n")
        print("  python3 fix_geocoding.py --provider osm --apply")
        sys.exit(1)

    if provider == "osm":
        print("Using OpenStreetMap Nominatim (no API key needed, ~1 request/second).\n")
    else:
        print("Using the Google Geocoding API.\n")

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
            result = geocode(addr, "Manhattan", provider)
        except Exception as e:
            print(f"  ERROR  {name}: {type(e).__name__}: {e}")
            failed += 1
            time.sleep(OSM_SLEEP if provider == "osm" else 0.2)
            continue
        time.sleep(OSM_SLEEP if provider == "osm" else 0.2)

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
