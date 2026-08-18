#!/usr/bin/env python3
"""
scraper.py — Detects which tracked galleries have posted something new.

How this used to work, and why it changed
-----------------------------------------
The original version hashed the raw bytes of each gallery's homepage
(`md5(response.content)`) and flagged the gallery whenever that hash moved.
Measured against this repo's own commit history, that reported roughly 120 of 223
galleries changing EVERY SINGLE DAY — about 54% of the map, day after day, for
weeks. Real exhibitions do not turn over at 54% a day.

The false positives come from things that have nothing to do with art: CSRF and
session nonces, cache-busting build hashes on assets, rotating ad and analytics
identifiers, "last updated" timestamps baked into the HTML, and A/B variants. All
of them move the raw bytes on every fetch while the page a visitor sees is
identical.

That mattered for more than tidiness. A green "new show" dot that lights up for
half the city is noise, and a weekly digest built on it would publish a plainly
false number every week.

What it does now
----------------
Instead of hashing the whole document, we extract a *content signal* — the parts
of a page that genuinely change when the show changes:

    <title> + <h1>..<h4> text + the text of every link

A new exhibition means a new show title, a new artist name, a new run of dates,
and those live in headings and links. Rotating tokens, scripts, timestamps and
tracking pixels do not. The signal is deduplicated, lowercased, stripped of bare
numbers, sorted, and hashed.

Fallback chain, most to least reliable:
    1. heading/link signal   (preferred)
    2. normalized visible text, with volatile patterns scrubbed
    3. raw bytes             (last resort, recorded as low-confidence)

Sites that render entirely in JavaScript often yield an empty signal; those fall
through to tier 2 or 3. We would rather miss a change than invent one.

Re-baselining is safe: a gallery is only flagged when there is a PREVIOUS signal
to compare against, so the first run after this change records signals for
everyone and flags nobody.

Usage:
    python3 scraper.py              # normal run, writes data/galleries.json
    python3 scraper.py --dry-run    # report what would change, write nothing
    python3 scraper.py --limit 20   # only check the first 20 galleries (testing)
"""

import hashlib
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

GALLERIES_PATH = Path("data/galleries.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NYCGalleryTracker/1.0; "
                  "+https://nyc-gallery-app.netlify.app)"
}
TIMEOUT = 15
SLEEP = 0.5

# Patterns that move on their own and never indicate a new exhibition.
VOLATILE = [
    re.compile(r"\b[0-9a-f]{12,}\b", re.I),                      # build ids, nonces
    re.compile(r"\b\d{9,13}\b"),                                  # epoch timestamps
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\b", re.I),
]

BARE_NUMBER = re.compile(r"^[\d\W]+$")


def _clean(text):
    text = text.lower()
    for pat in VOLATILE:
        text = pat.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _soup(content):
    s = BeautifulSoup(content, "html.parser")
    for tag in s(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    return s


def content_signal(content):
    """Return (signal_hash, tier).

    tier is 'signal' | 'text' | 'raw', recording which rung of the fallback chain
    produced the hash so callers can tell how much to trust it.
    """
    try:
        s = _soup(content)
    except Exception:
        return hashlib.md5(content).hexdigest(), "raw"

    parts = []
    if s.title and s.title.get_text(strip=True):
        parts.append(s.title.get_text(" ", strip=True))
    for tag in s.find_all(["h1", "h2", "h3", "h4"]):
        parts.append(tag.get_text(" ", strip=True))
    for a in s.find_all("a"):
        parts.append(a.get_text(" ", strip=True))

    cleaned = []
    for p in parts:
        p = _clean(p)
        if p and not BARE_NUMBER.match(p):
            cleaned.append(p)
    cleaned = sorted(set(cleaned))

    # A page with almost no headings or links is usually JS-rendered; fall back.
    if len(cleaned) >= 3:
        return hashlib.md5("\n".join(cleaned).encode("utf-8", "replace")).hexdigest(), "signal"

    text = _clean(s.get_text(" "))
    if len(text) >= 200:
        return hashlib.md5(text.encode("utf-8", "replace")).hexdigest(), "text"

    return hashlib.md5(content).hexdigest(), "raw"


def fetch_signal(url):
    """Fetch a URL and return (hash, tier), or (None, None) on failure."""
    if not url:
        return None, None
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return content_signal(r.content)
    except Exception as e:
        print(f"  WARN: {url}: {type(e).__name__}: {e}")
        return None, None


def _prev_hash(prev_signals, url):
    entry = prev_signals.get(url)
    if isinstance(entry, dict):
        return entry.get("h")
    return None


def main():
    dry_run = "--dry-run" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    geojson = json.loads(GALLERIES_PATH.read_text())
    features = geojson["features"]
    today = date.today().isoformat()

    # _signals supersedes the old _hashes map. The old raw hashes are retained for
    # one migration cycle so the change is reversible.
    prev_signals = geojson.get("_signals", {})
    prev_raw = geojson.get("_hashes", {})
    new_signals = {}

    targets = features[:limit] if limit else features
    print(f"Loaded {len(features)} galleries, checking {len(targets)}  [{today}]"
          + ("  (DRY RUN)" if dry_run else ""))

    updated, errors = 0, 0
    tiers = {"signal": 0, "text": 0, "raw": 0}
    first_run = not prev_signals

    for i, feature in enumerate(targets, 1):
        props = feature["properties"]
        name = props.get("name", "?")
        url = props.get("url", "")
        props.pop("updated", None)              # legacy boolean field
        props.setdefault("last_updated", "")

        if not url:
            print(f"  [{i:3d}/{len(targets)}] no url  {name}")
            continue

        h, tier = fetch_signal(url)
        time.sleep(SLEEP)

        if h is None:
            errors += 1
            # Preserve what we knew; a fetch failure is not a change.
            if url in prev_signals:
                new_signals[url] = prev_signals[url]
            print(f"  [{i:3d}/{len(targets)}] ERROR   {name}")
            continue

        tiers[tier] = tiers.get(tier, 0) + 1
        prev = _prev_hash(prev_signals, url)
        new_signals[url] = {"h": h, "tier": tier}

        # Only a change against a KNOWN previous signal counts. On the first run
        # after this rewrite there are no previous signals, so nothing is flagged.
        if prev is not None and h != prev:
            updated += 1
            if not dry_run:
                props["last_updated"] = today
            print(f"  [{i:3d}/{len(targets)}] UPDATED {name}  ({tier})")
        else:
            print(f"  [{i:3d}/{len(targets)}] same    {name}  ({tier})")

    checked = sum(tiers.values())
    share = (updated / checked * 100) if checked else 0
    print()
    print(f"Checked {checked} reachable galleries ({errors} errors).")
    print(f"  detection tier: signal={tiers.get('signal', 0)} "
          f"text={tiers.get('text', 0)} raw={tiers.get('raw', 0)}")
    if first_run:
        print("  First run with content signals — baseline recorded, nothing flagged.")
    else:
        print(f"  {updated} flagged as updated ({share:.0f}% of those checked).")
        if share > 25:
            print("  NOTE: that share is high. If it stays above ~25% daily, some sites are")
            print("        still churning; re-check with --dry-run before trusting the digest.")

    if dry_run:
        print("\nDry run — data/galleries.json not written.")
        return

    geojson["_signals"] = new_signals
    geojson["_hashes"] = prev_raw           # retained for one migration cycle
    GALLERIES_PATH.write_text(json.dumps(geojson, indent=2))
    print(f"Done. {updated} updated.")


if __name__ == "__main__":
    main()
