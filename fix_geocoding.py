#!/usr/bin/env python3
"""
fix_geocoding.py — Repairs galleries whose coordinates landed in the wrong borough.

The problem
-----------
About thirty galleries in data/galleries.json carry Tribeca and SoHo addresses but
coordinates in Brooklyn, wrong by 3-6 km:

    Luhring Augustine Tribeca   17 White St     stored 6.1 km away, in Brooklyn
    Marian Goodman Gallery      385 Broadway    stored 4.3 km away, in Brooklyn
    ISLAA                       142 Franklin St stored 4.3 km away, in Greenpoint

The cause is street-name collision. Broadway, White St, Leonard St, Grand St,
Franklin St and Greene St all exist in BOTH Manhattan and Brooklyn, so a bare
"176 Grand St" can resolve to either.

Why this needs more than a geocoder
-----------------------------------
Re-geocoding cannot fix this on its own. Asked for "17 White St", OpenStreetMap
returns a house-number-level match in Manhattan AND one in Brooklyn — both real.
The address string genuinely does not identify a borough, so any script that just
re-queries it is guessing. An earlier version of this file did exactly that and
changed nothing.

So this script goes and finds independent evidence of where each gallery actually
is, from the gallery's own website, and only then asks the geocoder for precise
coordinates within the borough that evidence points to.

Evidence, strongest first
-------------------------
  anchored-zip   A NYC ZIP appearing next to this gallery's street address on its
                 own site. Survives galleries with several locations, which is why
                 it is preferred: luhringaugustine.com lists both 10013 (Tribeca)
                 and 10011 (Chelsea), and only the anchored match picks the right
                 one for "17 White St".
  page-zip       Exactly one distinct NYC ZIP anywhere on the site.
  geocoder       The house number exists in only one borough, so there is no
                 collision for this particular address after all.

A record is changed only when evidence is found and the resulting borough differs
from, or the coordinates disagree with, what is stored. Everything else is left
alone and listed as needing a manual look — being unfixed is recoverable, being
silently wrong is not.

Usage
-----
    python3 fix_geocoding.py            # dry run, prints the proposed changes
    python3 fix_geocoding.py --apply    # write data/galleries.json
    python3 fix_geocoding.py --json out.json    # also dump evidence per gallery

Needs no API key. Uses OpenStreetMap's Nominatim (rate-limited to 1 req/sec per
their usage policy) and plain HTTPS fetches of the gallery sites.
"""

import json
import re
import sys
import time
import urllib.parse
import urllib.request

DATA = "data/galleries.json"

NOMINATIM = "https://nominatim.openstreetmap.org/search"
NOMINATIM_UA = "NYCGalleryTracker/1.0 (+https://nycgallerytracker.com)"
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ZIP prefix -> borough. NYC ZIPs are allocated by borough, so a ZIP is an
# unambiguous borough label in a way a street address is not.
ZIP_RANGES = [
    ("Manhattan", lambda z: 10001 <= z <= 10282),
    ("Bronx", lambda z: 10451 <= z <= 10475),
    ("Staten Island", lambda z: 10301 <= z <= 10314),
    ("Brooklyn", lambda z: 11201 <= z <= 11256),
    ("Queens", lambda z: (11004 <= z <= 11109) or (11351 <= z <= 11697)),
]

BOROUGHS = ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"]

BOROUGH_MARKERS = {
    "Manhattan": ["manhattan", "new york, ny", "soho", "tribeca"],
    "Brooklyn": ["brooklyn"],
    "Queens": ["queens", "astoria", "long island city"],
    "Bronx": ["bronx"],
    "Staten Island": ["staten island"],
}


# ------------------------------------------------------------------------
# Manually verified, 2026-08-19.
#
# These are the records the automated tiers could not settle: JS-only sites
# that never print a street address in their HTML, two sites that were down,
# and one record with no URL at all. Each was confirmed individually against
# the source named below, so the result is reproducible rather than a one-off
# hand edit of the JSON.
#
# Underdonk is the interesting one. validate_data.py flags it, but it is not
# wrong: its stored coordinates match 297 Grand St in Williamsburg (11211)
# exactly, and Underdonk is a Brooklyn space. It is a false positive of the
# "unqualified address + non-Manhattan borough" rule. Qualifying its address
# fixes the record and clears the warning without weakening the rule.
# ------------------------------------------------------------------------
VERIFIED = {
    "KATES–FERRI PROJECTS":  ("Manhattan", "katesferriprojects.com/contact lists ZIP 10002"),
    "Ulrik":                 ("Manhattan", "ulrik.nyc/contact lists ZIP 10013"),
    "125 Newbury":           ("Manhattan", "125newbury.com/contact lists Tribeca, ZIP 10013"),
    "D. D. D. D.":           ("Manhattan", "dddd.pictures/about lists Manhattan, Tribeca, ZIP 10013"),
    "SARAHCROWN":            ("Manhattan", "sarahcrown.com describes its Tribeca space"),
    "Almine Rech":           ("Manhattan", "361 Broadway, NY 10013, Tribeca flagship (ADAA, ARTnews)"),
    "Space ZeroOne":         ("Manhattan", "371 Broadway, Tribeca (Hanwha Foundation, e-flux)"),
    "Will Shott":            ("Manhattan", "17 Pike St, NY 10002, Lower East Side (Artforum artguide)"),
    "Hemingway Gallery":     ("Manhattan", "88 Leonard St Tribeca storefront (The Art Newspaper, 2019)"),
    "370 Broadway (JDJ, Deanna Evans Projects, Chozick Family Art Gallery)":
                             ("Manhattan", "OSM has 370 Broadway as Manhattan 10013, Civic Center"),
}

# Records the validator flags that are already correct. Value is the address to
# store instead, qualified so the address itself is no longer ambiguous.
CONFIRMED_CORRECT = {
    "Underdonk": ("Brooklyn", "297 Grand St, Brooklyn",
                  "coordinates already match 297 Grand St, Williamsburg 11211"),
}


def zip_to_borough(z):
    for name, test in ZIP_RANGES:
        if test(z):
            return name
    return None


def flagged(props):
    """The same predicate validate_data.py uses to raise its 30 errors."""
    addr = (props.get("address") or "").lower()
    borough = (props.get("borough") or "").strip()
    if not addr or not borough:
        return False
    qualified = (
        any(m in addr for markers in BOROUGH_MARKERS.values() for m in markers)
        or re.search(r"\b1[01]\d{3}\b", addr)
        or "ny" in addr
    )
    return not qualified and borough != "Manhattan"


def fetch(url, ua, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(2_000_000)
    return raw.decode(r.headers.get_content_charset() or "utf-8", errors="replace")


def page_text(html):
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = html.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", html)


def nyc_zips(text):
    out = []
    for m in re.finditer(r"\b(1[01]\d{3})\b", text):
        z = int(m.group(1))
        if zip_to_borough(z):
            out.append((m.start(), z))
    return out


def anchored_zip(text, address):
    """Find a ZIP that sits just after this gallery's own street address."""
    m = re.match(r"\s*(\d+)\s+(.+)", address)
    if not m:
        return None
    house, rest = m.group(1), m.group(2)
    word = re.sub(r"[^a-z]", "", rest.split()[0].lower())
    if not word:
        return None
    zips = nyc_zips(text)
    if not zips:
        return None
    best = None
    for am in re.finditer(r"\b%s\b" % re.escape(house), text):
        window = text[am.end():am.end() + 60].lower()
        if word not in window:
            continue
        for pos, z in zips:
            gap = pos - am.end()
            if 0 <= gap <= 250 and (best is None or gap < best[0]):
                best = (gap, z)
    return best[1] if best else None


def geocode(address, borough):
    """Precise coordinates for an address constrained to one borough."""
    q = urllib.parse.urlencode({
        "street": address, "county": borough, "state": "NY",
        "country": "USA", "format": "jsonv2", "addressdetails": "1", "limit": "3",
    })
    try:
        body = fetch("%s?%s" % (NOMINATIM, q), NOMINATIM_UA, timeout=30)
        results = json.loads(body)
    except Exception:
        return None
    finally:
        time.sleep(1.1)  # Nominatim usage policy: max 1 request/second
    house = (re.match(r"\s*(\d+)", address) or [None, None])[1]
    for r in results:
        if house and r.get("address", {}).get("house_number") != house:
            continue
        return float(r["lat"]), float(r["lon"])
    return None


def which_boroughs_have(address):
    """Boroughs where this exact house number exists."""
    found = []
    for b in BOROUGHS:
        if geocode(address, b):
            found.append(b)
    return found


def resolve(props):
    """Gather evidence for one gallery. Returns (borough, method, note)."""
    address = props.get("address") or ""
    url = props.get("url") or ""

    name = props.get("name") or ""
    if name in VERIFIED:
        b, why = VERIFIED[name]
        return b, "verified", why

    if url:
        if not url.startswith("http"):
            url = "https://" + url
        try:
            text = page_text(fetch(url, BROWSER_UA))
        except Exception as e:
            text = ""
            note = "site unreachable (%s)" % type(e).__name__
        else:
            note = ""
            z = anchored_zip(text, address)
            if z:
                b = zip_to_borough(z)
                if b:
                    return b, "anchored-zip", "ZIP %d beside the address on its site" % z
            distinct = sorted({z for _, z in nyc_zips(text)})
            if len(distinct) == 1:
                b = zip_to_borough(distinct[0])
                if b:
                    return b, "page-zip", "only ZIP on the site is %d" % distinct[0]
            if distinct:
                note = "site lists %d ZIPs (%s), none beside the address" % (
                    len(distinct), ", ".join(str(z) for z in distinct))
    else:
        note = "no url on record"

    hits = which_boroughs_have(address)
    if len(hits) == 1:
        return hits[0], "geocoder", "house number exists only in %s" % hits[0]
    if len(hits) > 1:
        note = (note + "; " if note else "") + "address exists in " + ", ".join(hits)
    return None, None, note or "no evidence found"


def haversine(a, b):
    from math import radians, sin, cos, asin, sqrt
    lat1, lon1, lat2, lon2 = map(radians, [a[0], a[1], b[0], b[1]])
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * asin(sqrt(h))


def block_outliers(features):
    """Records whose coordinates contradict their own block.

    Wrong-borough is not the only way a coordinate goes bad. Nino Mier Gallery
    was labelled Manhattan, sat in Manhattan, and was still 4.6 km from every
    other gallery on its stretch of Broadway. The borough checks cannot see that
    because the record is self-consistent; only the neighbours give it away.
    """
    groups = {}
    for ft in features:
        p = ft["properties"]
        m = re.match(r"\s*(\d+)\s+(.+?)\s*$", (p.get("address") or ""))
        coords = (ft.get("geometry") or {}).get("coordinates")
        if not m or not coords:
            continue
        street = re.sub(r"\b(st|street|ave|avenue|rd|road|pl|place)\b\.?", "",
                        m.group(2).lower()).strip()
        street = re.sub(r"[^a-z0-9 ]", "", street).strip()
        if street:
            groups.setdefault(street, []).append((int(m.group(1)), ft))

    out = []
    for street, members in groups.items():
        if len(members) < 3:
            continue
        for house, ft in members:
            near = [o for o in members if o[1] is not ft and abs(o[0] - house) <= 20]
            if len(near) < 2:
                continue
            lon, lat = ft["geometry"]["coordinates"]
            gaps = [haversine((lat, lon),
                              (o[1]["geometry"]["coordinates"][1],
                               o[1]["geometry"]["coordinates"][0])) for o in near]
            if min(gaps) > 1.5:
                out.append((ft, min(gaps), len(near)))
    return out


def main():
    apply_changes = "--apply" in sys.argv
    dump = None
    if "--json" in sys.argv:
        dump = sys.argv[sys.argv.index("--json") + 1]

    with open(DATA) as f:
        doc = json.load(f)

    targets = [ft for ft in doc["features"] if flagged(ft["properties"])]
    print("%d galleries flagged by validate_data.py\n" % len(targets))

    changes, manual, evidence, confirmed = [], [], [], []
    already = 0

    for i, ft in enumerate(targets, 1):
        p = ft["properties"]
        name = p.get("name", "?")
        print("[%2d/%d] %-52s %-18s" % (i, len(targets), name[:52], p.get("address", "")),
              end="", flush=True)

        if name in CONFIRMED_CORRECT:
            boro, new_addr, why = CONFIRMED_CORRECT[name]
            if p.get("address") != new_addr:
                print("  already correct — qualifying address (%s)" % why)
                confirmed.append((ft, new_addr, why))
            else:
                print("  ok (already correct)")
                already += 1
            continue

        borough, method, note = resolve(p)
        evidence.append({"name": name, "address": p.get("address"),
                         "stored_borough": p.get("borough"), "resolved": borough,
                         "method": method, "note": note})

        if not borough:
            print("  UNRESOLVED — %s" % note)
            manual.append((name, p.get("address"), note))
            continue

        coords = geocode(p.get("address", ""), borough)
        if not coords:
            print("  UNRESOLVED — %s says %s but no house-level match there"
                  % (method, borough))
            manual.append((name, p.get("address"), "%s -> %s, no coords" % (method, borough)))
            continue

        old_lon, old_lat = ft["geometry"]["coordinates"]
        moved = haversine((old_lat, old_lon), coords)
        if p.get("borough") == borough and moved < 0.20:
            print("  ok (already correct)")
            continue

        print("  %s -> %s, moves %.1f km  [%s]" % (p.get("borough"), borough, moved, method))
        changes.append((ft, borough, coords, moved, method, note))

    # Pass 2: right borough, wrong coordinates.
    print("\nChecking for coordinates that contradict their own block...")
    for ft, gap, n in block_outliers(doc["features"]):
        p = ft["properties"]
        boro = p.get("borough") or "Manhattan"
        coords = geocode(p.get("address", ""), boro)
        if not coords:
            manual.append((p.get("name", "?"), p.get("address"),
                           "%.1f km from its block, no house-level match in %s" % (gap, boro)))
            continue
        old_lon, old_lat = ft["geometry"]["coordinates"]
        moved = haversine((old_lat, old_lon), coords)
        if moved < 0.20:
            continue
        print("  %-40s %-16s off by %.1f km from %d neighbours, moves %.1f km"
              % (p.get("name", "")[:40], p.get("address", ""), gap, n, moved))
        changes.append((ft, boro, coords, moved, "block", "%.1f km from its own block" % gap))

    print("\n%s" % ("=" * 78))
    ok = max(0, len(targets) - len(changes) - len(confirmed) - len(manual))
    print("%d to change, %d address qualified, %d need a manual look, %d already correct"
          % (len(changes), len(confirmed), len(manual), ok))

    if changes:
        print("\nProposed changes:")
        for ft, b, c, moved, method, note in changes:
            p = ft["properties"]
            print("  %-50s %-18s %s -> %-9s %5.1f km  (%s: %s)"
                  % (p.get("name", "")[:50], p.get("address", ""), p.get("borough"),
                     b, moved, method, note))

    if manual:
        print("\nNeed a manual look:")
        for name, addr, note in manual:
            print("  %-50s %-18s %s" % (name[:50], addr, note))

    if dump:
        with open(dump, "w") as f:
            json.dump(evidence, f, indent=2)
        print("\nEvidence written to %s" % dump)

    if not changes and not confirmed:
        print("\nNothing to write.")
        return

    if not apply_changes:
        print("\nDry run. Re-run with --apply to write %s." % DATA)
        return

    for ft, new_addr, _ in confirmed:
        ft["properties"]["address"] = new_addr

    for ft, borough, coords, _, _, _ in changes:
        ft["properties"]["borough"] = borough
        ft["geometry"]["coordinates"] = [round(coords[1], 6), round(coords[0], 6)]

    # Match how scraper.py and the other generators write this file exactly
    # (json.dumps(..., indent=2), ASCII-escaped, no trailing newline). Writing it
    # any other way leaves a diff the next daily bot run silently reverts.
    with open(DATA, "w") as f:
        f.write(json.dumps(doc, indent=2))
    print("\nWrote %d corrections and %d address qualifications to %s."
          % (len(changes), len(confirmed), DATA))


if __name__ == "__main__":
    main()
