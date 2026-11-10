#!/usr/bin/env python3
"""
merge_candidates.py — Add reviewed galleries from data/candidates.json
(made by discover_galleries.py) to data/galleries.json.

Policy: walk-in galleries only. A candidate is added when Google lists regular
opening hours on 3+ days a week ("walk_in": "walk-in") and Google classifies it
as a gallery, museum, studio or cultural centre. Private dealers that see
visitors by appointment only are left off: a pin is a promise that you can walk
in. An explicit "approve": true/false in candidates.json overrides the rules.

Duplicates are caught three ways, because Google's names rarely match the
site's exactly ("Nara Roesler | New York" vs "Nara Roesler"): normalized name,
one name containing the other, and same website domain.

Also splits the scraper's combined entries ("55 Walker(Andrew Kreps, ...)")
into the separate galleries they stand for.

Usage:
    python3 merge_candidates.py           # dry run: prints what would change
    python3 merge_candidates.py --apply   # writes data/galleries.json
"""

import argparse
import copy
import json
import math
import re
from pathlib import Path
from urllib.parse import urlparse

GALLERIES_PATH = Path("data/galleries.json")
CANDIDATES_PATH = Path("data/candidates.json")
REPORT_PATH = Path("data/merge_report.txt")

GALLERY_TYPES = {"art_gallery", "art_museum", "art_studio", "cultural_center"}

# Combined entries -> the separate galleries at that address. Galleries listed
# here that discover_galleries.py also found are taken from the candidates;
# the rest are added with the combined entry's coordinates.
SPLITS = {
    "55 Walker(Andrew Kreps, Bortolami, kaufmann repetto)": [
        {"name": "Andrew Kreps Gallery", "url": "https://www.andrewkreps.com"},
        {"name": "Bortolami", "url": "https://www.bortolamigallery.com"},
        # kaufmann repetto is already its own record
    ],
    "370 Broadway (JDJ, Deanna Evans Projects, Chozick Family Art Gallery)": [],
}

APPOINTMENT = re.compile(r"by appointment|appointment (only|required)", re.I)

# Upper-floor galleries Google files under "Apt" that are open to visitors.
KNOWN_GOOD = {"Galerie St. Etienne"}

# Rejected by hand during review (not exhibition galleries).
REJECT = {"Dienst + Dotter Antikviteter"}


def street_address(address: str) -> str:
    """Drop ', USA' and any leading 'Building name,' / 'Storefront,' parts so
    the address starts at the street number — the map groups pins by it."""
    a = re.sub(r",\s*USA$", "", address.strip())
    parts = [p.strip() for p in a.split(",")]
    while len(parts) > 1 and not re.match(r"\d", parts[0]):
        parts.pop(0)
    return ", ".join(parts)


SUFFIXES = re.compile(r"\s*(\|.*|,?\s*(inc|llc|ltd)\.?|\s+-\s+.*)$", re.I)


def clean_name(name: str) -> str:
    prev = None
    while prev != name:
        prev, name = name, SUFFIXES.sub("", name).strip()
    return name


def norm(name: str) -> str:
    n = clean_name(name).lower()
    n = re.sub(r"\b(gallery|galleries|galerie|fine art|new york|nyc|the)\b", "", n)
    return re.sub(r"[^a-z0-9]", "", n)


def domain(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


# Shared hosts — the same domain does not mean the same gallery.
SHARED_DOMAINS = {"", "instagram.com", "facebook.com", "linktr.ee", "sites.google.com",
                  "artsy.net", "squarespace.com", "wixsite.com", "business.site"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    geo = json.loads(GALLERIES_PATH.read_text())
    features = geo["features"]
    candidates = json.loads(CANDIDATES_PATH.read_text())

    report = []
    # 1. Remove combined entries; remember their coordinates.
    split_coords = {}
    kept = []
    for f in features:
        name = f["properties"]["name"]
        if name in SPLITS:
            split_coords[name] = f
            report.append(f"REMOVED combined entry: {name}")
        else:
            kept.append(f)
    features = kept

    base_count = len(features)
    # (norm name, domain, lon, lat) for everything already on the map.
    seen = [(norm(f["properties"]["name"]), domain(f["properties"].get("url", "")),
             *f["geometry"]["coordinates"]) for f in features]

    def km(lon1, lat1, lon2, lat2):
        dx = (lon2 - lon1) * 84.2   # km per degree of longitude at NYC
        dy = (lat2 - lat1) * 111.0
        return math.hypot(dx, dy)

    # A name or website match is only a duplicate when it is also within 300 m.
    # Galleries with several branches (Gagosian, Pace, Hollis Taggart) share a
    # name and a website, and each branch is a separate place to visit.
    def is_dup(name, url, lon, lat):
        n, d = norm(name), domain(url)
        if not n:
            return "empty name"
        for sn, sd, slon, slat in seen:
            if km(lon, lat, slon, slat) > 0.3:
                continue
            if n == sn:
                return "same name"
            if len(n) >= 6 and len(sn) >= 6 and (n.startswith(sn) or sn.startswith(n)):
                return "name contains existing"
            if d and d not in SHARED_DOMAINS and d == sd:
                return f"same website {d}"
        return None

    def add(name, address, url, borough, lon, lat, source):
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
            "properties": {"name": name, "address": address, "url": url,
                           "borough": borough, "last_updated": ""},
        })
        seen.append((norm(name), domain(url), lon, lat))
        report.append(f"ADDED [{source}] {name} | {address}")

    # 2. Manual split entries not covered by candidates.
    for combined, parts in SPLITS.items():
        src = split_coords.get(combined)
        if not src:
            continue
        lon, lat = src["geometry"]["coordinates"]
        for p in parts:
            if not is_dup(p["name"], p["url"], lon, lat):
                add(p["name"], src["properties"]["address"], p["url"],
                    src["properties"].get("borough", "Manhattan"), lon, lat, "split")

    # 3. Candidates.
    skipped = {}
    for c in candidates:
        approve = c.get("approve")
        reason = None
        if approve is False:
            reason = "rejected in review"
        elif approve is not True:
            if c["walk_in"] != "walk-in":
                reason = "not walk-in"
            elif c["primary_type"] not in GALLERY_TYPES:
                reason = f"type {c['primary_type'] or 'none'}"
        if not reason and not c.get("borough"):
            reason = "no borough"
        if not reason and c.get("lat") is None:
            reason = "no coordinates"
        address = street_address(c["address"])
        if approve is not True and not reason:
            if APPOINTMENT.search(c["name"] + " " + c["address"]):
                reason = "by appointment"
            elif not re.match(r"\d", address):
                reason = "no street number"
            elif re.search(r"\bapt\b", address, re.I) and c["name"] not in KNOWN_GOOD:
                reason = "apartment address"
            elif c["name"] in REJECT:
                reason = "rejected in review"
        name = clean_name(c["name"])
        if not reason:
            reason = is_dup(name, c["url"], c["lon"], c["lat"])
        if reason:
            key = "type (not a gallery)" if reason.startswith("type") else \
                  "duplicate" if reason.startswith(("same", "name")) else reason
            skipped[key] = skipped.get(key) or 0
            skipped[key] += 1
            if key == "duplicate":
                report.append(f"DUP ({reason}): {c['name']} | {c['address']}")
            continue
        add(name, address, c["url"], c["borough"], c["lon"], c["lat"], c["district"])

    skipped = {k: v for k, v in skipped.items() if v}
    added = sum(1 for r in report if r.startswith("ADDED"))
    print(f"Existing after removing combined entries: {base_count}")
    print(f"Would add: {added}  ->  total {len(features)}")
    print(f"Skipped: {skipped}")
    REPORT_PATH.write_text("\n".join(report) + "\n")
    print(f"Details: {REPORT_PATH}")

    if args.apply:
        out = copy.copy(geo)
        out["features"] = features
        GALLERIES_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))
        print("Wrote", GALLERIES_PATH)
    else:
        print("Dry run — re-run with --apply to write.")


if __name__ == "__main__":
    main()
