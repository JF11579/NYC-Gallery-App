#!/usr/bin/env python3
"""
build_gallery_list.py — One-time builder for NYC-Gallery-App's galleries.json.

Fetches gallery directories for all five NYC boroughs:
  • Manhattan  — downtowngallerymap.com (LES, SoHo/Tribeca) + agora-gallery.com
  • Brooklyn   — agora-gallery.com (Bushwick, DUMBO, Williamsburg)
  • Queens     — curated list (LIC art district)
  • Bronx      — curated list
  • Staten Island — curated list

Parses out gallery name + address + website, dedupes, geocodes each location
via the Mapbox Geocoding API, detects borough from the geocode response, and
writes a GeoJSON FeatureCollection to data/galleries.json suitable for the
live map.

Run this once locally:

    export MAPBOX_TOKEN='pk.eyJ1...'        # your Mapbox public token
    python3 build_gallery_list.py

Then commit data/galleries.json and push.
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup


# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

# Mapbox public token. Either set the MAPBOX_TOKEN env var or paste it here.
# (Your existing index.html token is fine; geocoding is free up to 100k/month.)
MAPBOX_TOKEN = os.environ.get("MAPBOX_TOKEN", "").strip()

SOURCES = {
    # downtown gallery map — only covers LES and SoHo/Tribeca
    "downtown_les": "https://downtowngallerymap.com/galleries_les.php",
    "downtown_soho_tribeca": "https://downtowngallerymap.com/galleries_soho-trib.php",
    # agora gallery guide — Manhattan neighborhoods
    "agora_upper_east_side": "https://agora-gallery.com/ny-art-galleries/upper-east-side/",
    "agora_chelsea": "https://agora-gallery.com/ny-art-galleries/chelsea/",
    "agora_soho": "https://agora-gallery.com/ny-art-galleries/soho/",
    "agora_les_east_village": "https://agora-gallery.com/ny-art-galleries/lower-east-site-east-village/",
    # agora gallery guide — Brooklyn neighborhoods
    "agora_bushwick": "https://agora-gallery.com/ny-art-galleries/bushwick/",
    "agora_dumbo": "https://agora-gallery.com/ny-art-galleries/dumbo/",
    "agora_williamsburg": "https://agora-gallery.com/ny-art-galleries/williamsburg/",
}

# Labels used in progress output for each agora source
_AGORA_LABELS = {
    "agora_upper_east_side": "Upper East Side",
    "agora_chelsea": "Chelsea",
    "agora_soho": "SoHo (Agora)",
    "agora_les_east_village": "LES / East Village (Agora)",
    "agora_bushwick": "Bushwick",
    "agora_dumbo": "DUMBO",
    "agora_williamsburg": "Williamsburg",
}

OUTPUT_PATH = Path("data/galleries.json")
CACHE_DIR = Path(".cache")  # raw HTML cached here so reruns don't re-fetch

# Use a normal-browser user agent. Some directory sites block default Python UA.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# Bounding box for all five NYC boroughs (approximate).
# Anything geocoded outside this is dropped.
# (lon_min, lat_min, lon_max, lat_max)
NYC_BBOX = (-74.260, 40.490, -73.700, 40.930)

# Galleries for boroughs not covered by scraped sources.
# Queens/Bronx/Staten Island have no equivalent gallery-map directories,
# so we seed them with a curated list of known art spaces.
CURATED = [
    # Queens — Long Island City art district
    {"name": "SculptureCenter",              "address": "44-19 Purves St, Long Island City",    "url": "https://www.sculpture-center.org"},
    {"name": "MoMA PS1",                     "address": "22-25 Jackson Ave, Long Island City",  "url": "https://www.moma.org/ps1"},
    {"name": "Flux Factory",                 "address": "39-31 29th St, Long Island City",      "url": "https://fluxfactory.org"},
    {"name": "Dorsky Gallery",               "address": "11-03 45th Ave, Long Island City",     "url": "https://www.dorsky.org"},
    # Bronx
    {"name": "The Bronx Museum of the Arts", "address": "1040 Grand Concourse, Bronx",          "url": "https://www.bronxmuseum.org"},
    {"name": "Bronx River Art Center",       "address": "32 W Fordham Rd, Bronx",               "url": "https://bronxriverart.org"},
    {"name": "Longwood Arts Project",        "address": "450 Grand Concourse, Bronx",           "url": "https://bronxcouncilonthearts.org"},
    # Staten Island
    {"name": "Newhouse Center for Contemporary Art", "address": "1000 Richmond Terrace, Staten Island", "url": "https://www.snug-harbor.org"},
    {"name": "Staten Island Museum",         "address": "75 Stuyvesant Pl, Staten Island",      "url": "https://statenislandmuseum.org"},
]


# ----------------------------------------------------------------------------
# Fetching
# ----------------------------------------------------------------------------

def fetch_html(name: str, url: str) -> str | None:
    """Fetch a page, caching the result to disk so reruns are fast and offline-friendly.
    Returns None if fetch fails (the script continues with whatever sources work)."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / f"{name}.html"
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")
    print(f"  Fetching {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"  WARN: failed to fetch {name}: {e}")
        return None
    cache_file.write_text(r.text, encoding="utf-8")
    return r.text


# ----------------------------------------------------------------------------
# Parsers — one per source. Each returns a list of dicts with name/address/url.
# ----------------------------------------------------------------------------

# Match a real street address. Two flavors we care about:
#   (a) "NUM [E/W/etc.] ORDINAL Street/Ave"            — UES style, "45 East 78th Street"
#   (b) "NUM [E/W/etc.] WORD [WORD...] StreetSuffix"   — "395 Broadway", "88 Eldridge St."
_STREET_SUFFIX = (
    r"(?:Street|St\.?|Avenue|Ave\.?|Broadway|Bowery|Place|Pl\.?|"
    r"Alley|Boulevard|Blvd\.?|Square|Sq\.?|Lane|Ln\.?|Road|Rd\.?|Plaza|Plz\.?)"
)
_DIR = r"(?:East|West|North|South|E\.?|W\.?|N\.?|S\.?)"

_STREET_RES = [
    # NUM [DIR] ORDINAL Suffix  ("45 East 78th Street")
    re.compile(
        rf"\b(\d{{1,4}}[A-Z]?\s+(?:{_DIR}\s+)?\d{{1,3}}(?:st|nd|rd|th)\s+{_STREET_SUFFIX})\b"
    ),
    # NUM [DIR] WORD [WORD...] Suffix  ("88 Eldridge St", "980 Madison Ave")
    re.compile(
        rf"\b(\d{{1,4}}[A-Z]?\s+(?:{_DIR}\s+)?[A-Z][\w\-']*(?:\s+[A-Z][\w\-']*){{0,3}}\s+{_STREET_SUFFIX})\b"
    ),
    # NUM SingleNamedStreet  ("395 Broadway", "313 Bowery") — the street name IS the suffix
    re.compile(
        rf"\b(\d{{1,4}}[A-Z]?\s+(?:Broadway|Bowery))\b"
    ),
]

# Words that, if they appear as the "street name" word, mean it's a false positive.
_NOT_A_STREET = {"salon", "gallery", "studio"}


def _find_address(text: str):
    """Return the first plausible street address in `text`, or None."""
    for pattern in _STREET_RES:
        for m in pattern.finditer(text):
            full = m.group(1).strip()
            # Reject if the first word after the number is a known non-street noise word
            words = full.split()
            if len(words) >= 2 and words[1].lower() in _NOT_A_STREET:
                continue
            return full
    return None


def parse_downtowngallerymap(html: str) -> list[dict]:
    """downtowngallerymap.com — galleries are <h1> name, then address text + <a> link."""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for h1 in soup.find_all("h1"):
        name = h1.get_text(strip=True)
        if not name or name.lower().startswith(("downtowngallerymap", "lower east", "tribeca", "soho")):
            continue
        # Skip event headers
        if "tribeca gallery night" in name.lower():
            continue

        # Walk forward through siblings collecting text until we hit the next <h1>
        chunk = []
        for sib in h1.next_siblings:
            if getattr(sib, "name", None) == "h1":
                break
            chunk.append(sib)

        # Combine that chunk into text + extract the first plausible gallery URL
        chunk_html = "".join(str(c) for c in chunk)
        chunk_soup = BeautifulSoup(chunk_html, "html.parser")
        chunk_text = chunk_soup.get_text(" ", strip=True)

        # Find an address: e.g. "395 Broadway", "88 Eldridge St."
        address = _find_address(chunk_text)
        if not address:
            continue
        # Find the gallery's own website (first <a> whose text looks like a domain)
        url = None
        for a in chunk_soup.find_all("a"):
            href = a.get("href", "")
            text = a.get_text(strip=True)
            # Skip instagram, mailto, internal nav
            if not href or "instagram.com" in href or href.startswith("mailto:"):
                continue
            if "downtowngallerymap.com" in href or href.startswith("#"):
                continue
            # The first external link is almost always the gallery site
            if "." in text and not text.startswith("@"):
                url = href
                break
        if not url:
            # Fall back to any external link
            for a in chunk_soup.find_all("a", href=True):
                if a["href"].startswith("http") and "instagram.com" not in a["href"]:
                    url = a["href"]
                    break

        results.append({"name": name, "address": address, "url": url or ""})

    return results


def parse_agora(html: str) -> list[dict]:
    """agora-gallery.com — galleries are bold <strong><a>NAME</a></strong> followed by description.
    Often no inline address; we'll geocode by 'NAME, New York, NY'."""
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Each gallery block looks like:  <p><strong><a href="...">Name</a></strong><br>Description</p>
    for strong in soup.find_all("strong"):
        a = strong.find("a", href=True)
        if not a:
            continue
        name = a.get_text(strip=True)
        url = a["href"]
        if not name or len(name) > 100:
            continue
        # Skip nav / footer noise
        if name.lower() in {"current", "archive", "about", "contact", "art blog"}:
            continue
        # Skip if URL is internal to agora itself
        if "agora-gallery.com" in url:
            continue

        # Look for an inline address near this name (rare on agora, but try)
        parent_text = strong.parent.get_text(" ", strip=True) if strong.parent else ""
        address = _find_address(parent_text) or ""

        results.append({"name": name, "address": address, "url": url})

    return results


# ----------------------------------------------------------------------------
# Dedup
# ----------------------------------------------------------------------------

def normalize_for_dedup(name: str, url: str) -> str:
    """Make a hash-key that catches the same gallery written different ways."""
    base = re.sub(r"[^a-z0-9]", "", name.lower())
    # Pull the domain out of the URL for cross-checking
    dom = ""
    if url:
        m = re.search(r"://(?:www\.)?([^/]+)", url)
        if m:
            dom = m.group(1).lower()
    return f"{base}|{dom}"


def dedupe(galleries: list[dict]) -> list[dict]:
    seen = {}
    for g in galleries:
        key = normalize_for_dedup(g["name"], g["url"])
        # Keep the entry with the most info (prefer ones with address)
        if key not in seen:
            seen[key] = g
        else:
            existing = seen[key]
            if not existing["address"] and g["address"]:
                seen[key] = g
    return list(seen.values())


# ----------------------------------------------------------------------------
# Geocoding (Mapbox)
# ----------------------------------------------------------------------------

_LOCALITY_TO_BOROUGH = {
    "manhattan": "Manhattan",
    "brooklyn": "Brooklyn",
    "queens": "Queens",
    "the bronx": "Bronx",
    "bronx": "Bronx",
    "staten island": "Staten Island",
}


def _borough_from_context(context: list) -> str:
    """Extract the NYC borough name from a Mapbox geocode context array."""
    for item in context:
        text = item.get("text", "").lower()
        if text in _LOCALITY_TO_BOROUGH:
            return _LOCALITY_TO_BOROUGH[text]
    return ""


def geocode_one(query: str) -> tuple[float, float, str] | None:
    """Hit Mapbox forward geocoding. Returns (lon, lat, borough) or None."""
    if not MAPBOX_TOKEN:
        raise RuntimeError("MAPBOX_TOKEN is not set")
    url = (
        f"https://api.mapbox.com/geocoding/v5/mapbox.places/{quote(query)}.json"
        f"?access_token={MAPBOX_TOKEN}"
        f"&proximity=-73.97,40.72"           # bias toward NYC center
        f"&bbox={','.join(str(x) for x in NYC_BBOX)}"
        f"&limit=1"
    )
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        print(f"    Mapbox returned {r.status_code} for {query!r}")
        return None
    data = r.json()
    features = data.get("features") or []
    if not features:
        return None
    lon, lat = features[0]["center"]
    borough = _borough_from_context(features[0].get("context", []))
    return lon, lat, borough


def in_coverage_area(lon: float, lat: float) -> bool:
    lo_min, la_min, lo_max, la_max = NYC_BBOX
    return lo_min <= lon <= lo_max and la_min <= lat <= la_max


def geocode_all(galleries: list[dict]) -> list[dict]:
    """Add 'coordinates' and 'borough' to each gallery. Drop ones that fail to geocode."""
    out = []
    for i, g in enumerate(galleries, 1):
        if g["address"]:
            query = f"{g['address']}, New York, NY"
        else:
            query = f"{g['name']}, New York, NY"

        result = geocode_one(query)
        if not result:
            print(f"  [{i:3d}/{len(galleries)}] SKIP (no geocode): {g['name']!r}")
            continue
        lon, lat, borough = result
        if not in_coverage_area(lon, lat):
            print(f"  [{i:3d}/{len(galleries)}] SKIP (outside NYC): {g['name']!r} -> {lon:.4f},{lat:.4f}")
            continue
        g_out = dict(g)
        g_out["coordinates"] = [lon, lat]
        g_out["borough"] = borough
        out.append(g_out)
        print(f"  [{i:3d}/{len(galleries)}] {g['name']!r} -> {lon:.4f},{lat:.4f} [{borough or '?'}]")
        # Polite pacing — Mapbox allows ~600 req/min on free tier
        time.sleep(0.12)
    return out


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------

def to_geojson(galleries: list[dict]) -> dict:
    features = []
    for g in galleries:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": g["coordinates"]},
            "properties": {
                "name": g["name"],
                "address": g["address"],
                "url": g["url"],
                "borough": g.get("borough", ""),
                "updated": False,  # the daily scraper will flip this when sites change
            },
        })
    return {"type": "FeatureCollection", "features": features}


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    dry_run = "--dry-run" in sys.argv

    if not dry_run and not MAPBOX_TOKEN:
        print("ERROR: Set MAPBOX_TOKEN environment variable before running.")
        print("  export MAPBOX_TOKEN='pk.eyJ1...'")
        print("Or use --dry-run to skip geocoding and just see the parsed list.")
        sys.exit(1)

    print("Step 1/4 — Fetching directory pages")
    htmls = {}
    for name, url in SOURCES.items():
        html = fetch_html(name, url)
        if html:
            htmls[name] = html

    if not htmls:
        print("ERROR: All sources failed to fetch. Check your network connection.")
        sys.exit(1)

    print("\nStep 2/4 — Parsing")
    raw = []
    if "downtown_les" in htmls:
        before = len(raw)
        raw += parse_downtowngallerymap(htmls["downtown_les"])
        print(f"  Downtown LES: {len(raw)-before} galleries")
    if "downtown_soho_tribeca" in htmls:
        before = len(raw)
        raw += parse_downtowngallerymap(htmls["downtown_soho_tribeca"])
        print(f"  SoHo/Tribeca: {len(raw)-before} galleries")
    for key, label in _AGORA_LABELS.items():
        if key in htmls:
            before = len(raw)
            raw += parse_agora(htmls[key])
            print(f"  {label}: {len(raw)-before} galleries")

    # Inject curated galleries for boroughs without scraped sources
    before = len(raw)
    raw += [dict(g) for g in CURATED]
    print(f"  Curated (Queens/Bronx/Staten Island): {len(raw)-before} galleries")

    print(f"\n  Total before dedupe: {len(raw)}")
    galleries = dedupe(raw)
    print(f"  Total after dedupe:  {len(galleries)}")

    if dry_run:
        print("\n--dry-run set; skipping geocoding. Parsed galleries:")
        for g in galleries:
            print(f"  {g['name']:40s} | addr={g['address']!r:30s} | {g['url']}")
        return

    print("\nStep 3/4 — Geocoding (this takes a few minutes)")
    galleries = geocode_all(galleries)

    print(f"\nStep 4/4 — Writing GeoJSON ({len(galleries)} galleries)")
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(to_geojson(galleries), indent=2))
    print(f"  Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
