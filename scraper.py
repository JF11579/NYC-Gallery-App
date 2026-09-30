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

What changed, not just that it changed
--------------------------------------
The hash says a page moved; it cannot say what moved. So alongside it we keep the
page's headings (<h1>..<h4>, original casing) in data/headlines.json. When a
gallery is flagged, the headings it has today that it did not have yesterday are
logged to data/new_headlines.json under today's date. On a gallery homepage those
are usually the new show title and artist names. Boilerplate ("Home", "Join our
mailing list") is identical day to day, so the diff drops it without a blocklist;
JUNK below catches the few that rotate. The weekly archive pages print these
under each gallery. Only headings are kept, not link text: links are mostly
navigation and would bury the titles.

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
from datetime import date, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

GALLERIES_PATH = Path("data/galleries.json")
HEADLINES_PATH = Path("data/headlines.json")          # today's headings per gallery
NEW_HEADLINES_PATH = Path("data/new_headlines.json")  # {date: {url: [new headings]}}
NEW_HEADLINES_KEEP_DAYS = 21                          # the weekly pages need 7
MAX_HEADLINES = 40
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

# Headings that can appear or reappear on a page without saying anything about
# the art. Matched against the whole heading, case-insensitively.
JUNK = re.compile(
    r"^(home|menu|search|cart|shop|store|news|press|contact|about|visit|info|featured|highlights|welcome|"
    r"subscribe|newsletter|sign up|log ?in|account|follow us|share|close|"
    r"cookie.*|.*mailing list.*|item added to.*|.*your cart.*|"
    r"(now |currently )?(current|upcoming|past|on view|opening)?\s*"
    r"(exhibitions?|shows?|events?|programs?|on view)?\W*)$",
    re.I,
)

# A heading that is only a date or date range ("September 11 - November 1, 2026")
# says when, not what. Strip these words and if nothing is left, it's a date.
DATE_WORDS = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?|"
    r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?|\b(through|thru|to|until|and|from)\b|"
    r"\b\d+(st|nd|rd|th)?\b|[\W_]",
    re.I,
)


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


def extract_headlines(content):
    """The page's <h1>..<h4> texts in page order, original casing, deduplicated."""
    try:
        s = _soup(content)
    except Exception:
        return []
    out, seen = [], set()
    for tag in s.find_all(["h1", "h2", "h3", "h4"]):
        text = re.sub(r"\s+", " ", tag.get_text(" ", strip=True))
        key = text.casefold()
        if 3 <= len(text) <= 200 and not BARE_NUMBER.match(text) and key not in seen:
            seen.add(key)
            out.append(text)
            if len(out) >= MAX_HEADLINES:
                break
    return out


def new_headlines(prev, current):
    """Headings in `current` that were not in `prev`, minus boilerplate."""
    before = {h.casefold() for h in prev}
    return [h for h in current
            if h.casefold() not in before and not JUNK.match(h) and DATE_WORDS.sub("", h)]


def fetch_signal(url):
    """Fetch a URL and return (hash, tier, headlines), or (None, None, None) on failure."""
    if not url:
        return None, None, None
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        h, tier = content_signal(r.content)
        return h, tier, extract_headlines(r.content)
    except Exception as e:
        print(f"  WARN: {url}: {type(e).__name__}: {e}")
        return None, None, None


def _load_json(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


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
    prev_headlines = _load_json(HEADLINES_PATH)
    headlines = dict(prev_headlines)    # galleries we don't reach keep yesterday's
    todays_new = {}

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

        h, tier, heads = fetch_signal(url)
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
        # An empty list usually means a fetch that rendered nothing (JS-only page);
        # keep yesterday's headings so tomorrow isn't diffed against nothing.
        if heads:
            headlines[url] = heads

        # Only a change against a KNOWN previous signal counts. On the first run
        # after this rewrite there are no previous signals, so nothing is flagged.
        if prev is not None and h != prev:
            updated += 1
            if not dry_run:
                props["last_updated"] = today
            # Without a previous list every heading would look new; say nothing.
            fresh = new_headlines(prev_headlines[url], heads) if url in prev_headlines and heads else []
            if fresh:
                todays_new[url] = fresh
            print(f"  [{i:3d}/{len(targets)}] UPDATED {name}  ({tier})"
                  + (f"  new: {' | '.join(fresh[:3])}" if fresh else ""))
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

    # Record when the signal baseline was established. The weekly digest needs
    # this: the first run after a re-baseline flags nothing because there is
    # nothing to compare against, which is NOT the same as "nothing changed".
    # Without this marker the digest published "Nothing changed this week" on a
    # permanent page the day the baseline was reset.
    if first_run or not geojson.get("_signals_since"):
        geojson["_signals_since"] = today

    geojson["_signals"] = new_signals
    geojson["_hashes"] = prev_raw           # retained for one migration cycle
    GALLERIES_PATH.write_text(json.dumps(geojson, indent=2))

    HEADLINES_PATH.write_text(json.dumps(headlines, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    log = _load_json(NEW_HEADLINES_PATH)
    if todays_new:
        log[today] = todays_new
    cutoff = (date.today() - timedelta(days=NEW_HEADLINES_KEEP_DAYS)).isoformat()
    log = {d: v for d, v in log.items() if d >= cutoff}
    NEW_HEADLINES_PATH.write_text(json.dumps(log, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    print(f"Done. {updated} updated, {len(todays_new)} with readable new headings.")


if __name__ == "__main__":
    main()
