#!/usr/bin/env python3
"""
fetch_holiday_hours.py — Pull holiday ("special") hours from Google for every gallery.

Why: tourists in town between Thanksgiving and New Year's walk to galleries that
turn out to be shut. Google Places knows when a business has posted different
hours for a holiday, but only for the NEXT SEVEN DAYS (currentOpeningHours).
So this is run a few times a season, not daily:

    ~Nov 20  -> Thanksgiving, Black Friday
    ~Dec 19  -> Christmas Eve, Christmas Day, Dec 26
    ~Dec 26  -> New Year's Eve, New Year's Day

Each run is merged into data/holiday_hours.json (older holiday dates are kept),
and render_holiday_page.py turns that into the public page during the normal
daily build — the build itself never calls the API.

Cost: resolving place IDs uses Text Search with an IDs-only field mask (free);
the IDs are cached in data/place_ids.json, so later runs skip that step. The
hours themselves are one Place Details call per gallery (Enterprise SKU), about
950 calls a run.

Also records each gallery's regular weekly open days, which the page uses for
the "which days are galleries open" numbers.

Usage:
    python3 fetch_holiday_hours.py
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import time

import requests


def call(method, url, **kw):
    """requests call that waits out Google's per-minute rate limit (HTTP 429)."""
    for attempt in range(6):
        r = requests.request(method, url, timeout=20, **kw)
        if r.status_code != 429:
            return r
        time.sleep(10 * (attempt + 1))
    return r

GALLERIES_PATH = Path("data/galleries.json")
IDS_PATH = Path("data/place_ids.json")
OUT_PATH = Path("data/holiday_hours.json")

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/{}"
DETAILS_MASK = "currentOpeningHours,regularOpeningHours.periods,businessStatus"

# Google's day numbers: 0 = Sunday.
DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


def load_key():
    for line in Path(".env").read_text().splitlines():
        if line.startswith("GOOGLE_PLACES_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    sys.exit("No GOOGLE_PLACES_KEY in .env")


def gallery_key(p):
    return f"{p['name']}|{p['address']}"


def resolve_id(key, props, coords):
    """Place ID for one gallery. IDs-only field mask = the free Text Search tier."""
    lon, lat = coords
    body = {
        "textQuery": f"{props['name']} {props['address']}",
        "pageSize": 1,
        "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lon},
                                    "radius": 150.0}},
    }
    r = call("POST", SEARCH_URL, json=body,
             headers={"X-Goog-Api-Key": KEY, "X-Goog-FieldMask": "places.id"})
    if r.status_code != 200:
        return key, "ERROR"  # not cached; retried next run
    places = r.json().get("places") or []
    return key, places[0]["id"] if places else None


def hhmm(point):
    h, m = point.get("hour", 0), point.get("minute", 0)
    suffix = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}{':%02d' % m if m else ''}{suffix}"


def fetch_hours(key, place_id):
    r = call("GET", DETAILS_URL.format(place_id),
             headers={"X-Goog-Api-Key": KEY, "X-Goog-FieldMask": DETAILS_MASK})
    if r.status_code != 200:
        return key, None
    d = r.json()
    cur = d.get("currentOpeningHours", {})

    # Regular week: which days the gallery opens at all.
    open_days = sorted({p["open"]["day"] for p in
                        d.get("regularOpeningHours", {}).get("periods", []) if "open" in p})

    # Special (holiday) dates within the next seven days, with that day's hours.
    special = {}
    for s in cur.get("specialDays", []):
        dt = s["date"]
        iso = f"{dt['year']:04d}-{dt['month']:02d}-{dt['day']:02d}"
        spans = []
        for p in cur.get("periods", []):
            o, c = p.get("open", {}), p.get("close", {})
            od = o.get("date")
            if od and (od["year"], od["month"], od["day"]) == (dt["year"], dt["month"], dt["day"]):
                spans.append(f"{hhmm(o)}–{hhmm(c)}" if c else "open 24 hours")
        special[iso] = spans  # [] means closed that day
    return key, {"place_id": place_id, "open_days": open_days, "special": special,
                 "status": d.get("businessStatus", "")}


def main():
    global KEY
    KEY = load_key()
    feats = json.loads(GALLERIES_PATH.read_text())["features"]
    ids = json.loads(IDS_PATH.read_text()) if IDS_PATH.exists() else {}

    todo = [(gallery_key(f["properties"]), f["properties"], f["geometry"]["coordinates"])
            for f in feats if gallery_key(f["properties"]) not in ids]
    if todo:
        print(f"Resolving {len(todo)} place IDs (free tier)...")
        with ThreadPoolExecutor(8) as ex:
            for k, pid in ex.map(lambda t: resolve_id(*t), todo):
                if pid != "ERROR":
                    ids[k] = pid
        IDS_PATH.write_text(json.dumps(ids, indent=1, ensure_ascii=False, sort_keys=True))
    resolved = {k: v for k, v in ids.items() if v}
    print(f"{len(resolved)} of {len(feats)} galleries have a place ID.")

    wanted = [(gallery_key(f["properties"]), resolved[gallery_key(f["properties"])])
              for f in feats if gallery_key(f["properties"]) in resolved]
    print(f"Fetching hours for {len(wanted)} galleries...")
    with ThreadPoolExecutor(8) as ex:
        results = dict(ex.map(lambda t: fetch_hours(*t), wanted))

    old = json.loads(OUT_PATH.read_text()) if OUT_PATH.exists() else {"galleries": {}}
    merged = old.get("galleries", {})
    for k, v in results.items():
        if v is None:
            continue
        prev = merged.get(k, {})
        special = {**prev.get("special", {}), **v["special"]}  # keep earlier holidays
        merged[k] = {**v, "special": special}

    out = {"fetched": date.today().isoformat(),
           "window_start": date.today().isoformat(),
           "runs": sorted(set(old.get("runs", [])) | {date.today().isoformat()}),
           "galleries": merged}
    OUT_PATH.write_text(json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True))
    n_special = sum(1 for v in results.values() if v and v["special"])
    print(f"Done. {n_special} galleries have posted special hours this week -> {OUT_PATH}")


if __name__ == "__main__":
    main()
