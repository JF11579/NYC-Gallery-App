#!/usr/bin/env python3
"""
validate_data.py — Sanity-checks data/galleries.json before it reaches the site.

Two records shipped with coordinates that contradicted their own addresses:
"Ulrik" was labelled Bronx with a Manhattan address at 175 Canal St, and
"Nicodim Gallery" carried a SoHo address at 15 Greene St while its coordinates
placed it near Greenpoint. Both appeared on the wrong neighbourhood pages as a
result, because every area page is built from coordinates.

That kind of error is quietly expensive. Area pages are assembled by nearest
centroid, so one bad coordinate silently moves a gallery into a district it isn't
in — and a directory that puts galleries in the wrong neighbourhood is exactly the
sort of thing a manual quality review notices.

Checks performed:
  * URLs that are malformed or missing a scheme (these render as broken links)
  * coordinates outside the New York City bounding box
  * borough labels that disagree with the coordinates
  * addresses naming a borough that disagrees with the borough field
  * duplicate URLs and duplicate gallery names
  * records missing a name, address or coordinates

Exit code is 1 if any ERROR-level problem is found, so this can gate a build.
Warnings do not fail the run.

Usage:
    python3 validate_data.py
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

DATA_PATH = Path("data/galleries.json")

# Generous bounding box around the five boroughs.
NYC_BBOX = {"lat": (40.47, 40.93), "lon": (-74.30, -73.68)}

# Approximate bounding boxes per borough. Deliberately loose — the point is to
# catch a gallery placed in the wrong borough entirely, not to police block-level
# accuracy. Overlaps are expected and handled by checking membership, not
# exclusivity.
BOROUGH_BBOX = {
    "Manhattan":     {"lat": (40.680, 40.882), "lon": (-74.030, -73.906)},
    "Brooklyn":      {"lat": (40.551, 40.740), "lon": (-74.060, -73.833)},
    "Queens":        {"lat": (40.541, 40.812), "lon": (-73.965, -73.700)},
    "Bronx":         {"lat": (40.785, 40.918), "lon": (-73.935, -73.748)},
    "Staten Island": {"lat": (40.477, 40.652), "lon": (-74.260, -74.049)},
}

BOROUGH_IN_ADDRESS = {
    "Manhattan": ["new york, ny", "manhattan"],
    "Brooklyn": ["brooklyn"],
    "Queens": ["queens", "long island city", "astoria", "ridgewood", "flushing", "jamaica"],
    "Bronx": ["bronx"],
    "Staten Island": ["staten island"],
}


def in_box(lat, lon, box):
    return (box["lat"][0] <= lat <= box["lat"][1]
            and box["lon"][0] <= lon <= box["lon"][1])


def main():
    data = json.loads(DATA_PATH.read_text())
    features = data["features"]

    errors, warnings = [], []

    urls = Counter()
    names = Counter()

    for f in features:
        p = f.get("properties", {})
        name = p.get("name") or "(unnamed)"
        coords = (f.get("geometry") or {}).get("coordinates") or []

        if not p.get("name"):
            errors.append(f"record with no name: {p}")
        names[name.strip().lower()] += 1

        url = p.get("url", "")
        if url:
            urls[url] += 1
            if not re.match(r"^https?://[^/:\s]+", url):
                errors.append(f"{name}: malformed url {url!r}")

        if not p.get("address"):
            warnings.append(f"{name}: no address")

        if len(coords) != 2:
            errors.append(f"{name}: missing or malformed coordinates {coords!r}")
            continue

        lon, lat = coords
        if not in_box(lat, lon, NYC_BBOX):
            errors.append(f"{name}: coordinates ({lat:.4f}, {lon:.4f}) fall outside NYC")
            continue

        borough = (p.get("borough") or "").strip()
        if borough in BOROUGH_BBOX and not in_box(lat, lon, BOROUGH_BBOX[borough]):
            errors.append(
                f"{name}: labelled {borough} but coordinates ({lat:.4f}, {lon:.4f}) "
                f"are outside {borough} — address is {p.get('address', 'unknown')!r}"
            )

        addr = (p.get("address") or "").lower()
        if addr and borough:
            for other, markers in BOROUGH_IN_ADDRESS.items():
                if other == borough:
                    continue
                if any(m in addr for m in markers) and other != "Manhattan":
                    warnings.append(
                        f"{name}: borough field says {borough} but address mentions {other} "
                        f"({p.get('address')})"
                    )
                    break

            # An address with no borough, ZIP or city qualifier is ambiguous, and
            # most geocoders resolve a bare "175 Canal St" to Manhattan. So an
            # unqualified address on a NON-Manhattan record is a likely mis-geocode:
            # either the coordinates are wrong, or the borough label is. This is
            # what put a "Bronx" gallery at a Canal Street address and a "Brooklyn"
            # one on Greene Street in SoHo.
            qualified = (
                any(m in addr for markers in BOROUGH_IN_ADDRESS.values() for m in markers)
                or re.search(r"\b1[01]\d{3}\b", addr)      # NYC ZIP codes
                or "ny" in addr
            )
            if not qualified and borough != "Manhattan":
                errors.append(
                    f"{name}: labelled {borough} with the unqualified address "
                    f"{p.get('address')!r}. Broadway, White St, Leonard St, Grand St, "
                    "Franklin St and Greene St all exist in both Manhattan and Brooklyn, "
                    "so a bare address can geocode to the wrong borough. Run "
                    "fix_geocoding.py"
                )

    for url, n in urls.items():
        if n > 1:
            warnings.append(f"{n} galleries share the url {url} "
                            "(they will be flagged as updated together)")
    for name, n in names.items():
        if n > 1:
            warnings.append(f"{n} records share the name {name!r}")

    no_url = sum(1 for f in features if not f["properties"].get("url"))
    if no_url:
        warnings.append(f"{no_url} galleries have no url and can never be flagged "
                        "as having a new show")

    print(f"Validated {len(features)} galleries in {DATA_PATH}\n")
    if errors:
        print(f"ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  ✗ {e}")
        print()
    if warnings:
        print(f"WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  ! {w}")
        print()
    if not errors and not warnings:
        print("No problems found.")

    if errors:
        print(f"FAILED: {len(errors)} error(s).")
        sys.exit(1)
    print(f"PASSED with {len(warnings)} warning(s).")


if __name__ == "__main__":
    main()
