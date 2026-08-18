#!/usr/bin/env python3
"""
render_digest_pages.py — Publishes the weekly "new shows" digest as permanent web pages.

Why this exists
---------------
scraper.py fetches all ~234 gallery websites every day and hashes them, so we know
which NYC galleries changed their site and when. That is a genuinely original dataset
— nobody else, Google included, is tracking it — and until now it was expressed as a
green dot on a map and an email that disappeared into subscribers' inboxes.

This script turns that same signal into a dated, permanent page per week:

    /new-shows/2026-08-18.html      one week's activity, kept forever
    /new-shows/index.html           the archive index, newest first

Each dated page is written once and never regenerated, so the archive accumulates into
a real record of the NYC gallery season instead of a single page that overwrites itself.
After a year that is ~52 pages of timely, first-hand content that cannot be scraped from
anywhere else — which is the direct answer to AdSense's "low value content" finding and
to Search Console refusing to index the thin templated pages.

data/digest_history.json keeps a small running tally so each week's page can compare
itself with the weeks before it ("the busiest week since ..."), which is what makes the
prose on each page genuinely different rather than a filled-in template.

Usage:
    python3 render_digest_pages.py            # publish the week ending today
    python3 render_digest_pages.py --force    # overwrite today's page if it exists
    python3 render_digest_pages.py --backfill # rebuild archive index only
"""

import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from site_common import BASE_URL, esc, page_shell, site_footer

DATA_PATH = Path("data/galleries.json")
HISTORY_PATH = Path("data/digest_history.json")
OUT_DIR = Path("new-shows")
WINDOW_DAYS = 7

# Sanity ceiling. Before scraper.py switched from raw-byte hashing to content
# signals, roughly 54% of tracked galleries were flagged as "changed" every single
# day — noise from rotating nonces and cache-busting build hashes, not exhibitions.
# A week in which more than this share of the map changes is far more likely to be
# a detection fault than a real event, and publishing that number would put a
# plainly false claim on a permanent page. Above the ceiling we refuse to publish.
MAX_PLAUSIBLE_SHARE = 0.25


# ---------------------------------------------------------------- data helpers

def load_features():
    return json.loads(DATA_PATH.read_text())["features"]


def new_since(features, cutoff):
    """Galleries whose site changed on or after `cutoff` (ISO date string)."""
    out = []
    for f in features:
        p = f["properties"]
        lu = p.get("last_updated") or ""
        if lu and lu >= cutoff:
            out.append(p)
    out.sort(key=lambda p: (p.get("borough", ""), p["name"].lower()))
    return out


def load_history():
    if HISTORY_PATH.exists():
        try:
            return json.loads(HISTORY_PATH.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_history(history):
    HISTORY_PATH.parent.mkdir(exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, indent=2, sort_keys=True) + "\n")


# ------------------------------------------------------------------ narrative

def ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def pretty_date(iso):
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%B %-d, %Y")


def build_narrative(today, shows, by_borough, history, total_tracked):
    """Write the week's commentary from the data.

    This is deliberately branchy: the point is that a quiet week and a busy week
    produce genuinely different prose, rather than the same sentence with a
    different number dropped into it.
    """
    n = len(shows)
    paras = []

    prior = sorted(k for k in history if k < today)
    prior_counts = [history[k]["count"] for k in prior]
    avg = round(sum(prior_counts) / len(prior_counts), 1) if prior_counts else None

    share = round(n / total_tracked * 100) if total_tracked else 0

    # --- opening paragraph: the headline, in context
    if n == 0:
        paras.append(
            "Nothing changed this week. Every gallery site we track looks the same as it "
            "did seven days ago — no new exhibition pages, no updated listings, nothing. "
            "That happens more often than you'd think, particularly in midsummer and over "
            "the winter holidays, when the gallery calendar goes quiet and shows that "
            "opened a month ago simply stay up."
        )
    else:
        lead = (
            f"{n} of the {total_tracked} galleries we track changed something on their "
            f"website in the past seven days — about {share}% of the map. "
        )
        if avg is not None:
            if n > avg * 1.5:
                lead += (
                    f"That's well above the {avg} we normally see in a week, and usually "
                    "means a wave of openings rather than routine housekeeping."
                )
            elif n < avg * 0.6:
                lead += (
                    f"That's down on the usual {avg} a week — a slower stretch, the kind "
                    "that tends to fall between one run of shows closing and the next opening."
                )
            else:
                lead += f"That's roughly the usual pace; we average about {avg} a week."
        else:
            lead += (
                "This is the first week in the archive, so there's nothing yet to compare "
                "it against — that changes from next week on."
            )
        paras.append(lead)

    # --- second paragraph: where the activity was
    if n:
        top = by_borough.most_common()
        if len(top) == 1:
            b, c = top[0]
            paras.append(
                f"All of this week's activity was in {b}. When changes cluster in a single "
                "borough it's usually a scheduling artifact — galleries in the same district "
                "tend to open on the same Thursday, so their sites update within a day or "
                "two of each other."
            )
        else:
            lead_b, lead_c = top[0]
            rest = ", ".join(f"{b} ({c})" for b, c in top[1:])
            paras.append(
                f"{lead_b} led the week with {lead_c} "
                f"{'gallery' if lead_c == 1 else 'galleries'} posting something new, "
                f"followed by {rest}. A change can mean a new exhibition going up, a run "
                "of dates being extended, or simply a fresh set of images — we detect that "
                "the page moved, not what moved on it, so the list below is a starting "
                "point for a visit rather than a guarantee of a brand-new show."
            )

    # --- third paragraph: record-keeping context
    if n and prior_counts:
        busiest = max(prior_counts)
        if n > busiest:
            paras.append(
                f"This is the busiest week since we started keeping this archive "
                f"{len(prior_counts)} {'week' if len(prior_counts) == 1 else 'weeks'} ago, "
                f"beating the previous high of {busiest}."
            )
        elif n == busiest:
            paras.append(
                f"That ties the busiest week on record for this archive, at {busiest}."
            )
        else:
            rank = sorted(prior_counts + [n], reverse=True).index(n) + 1
            if rank <= 3:
                paras.append(
                    f"That makes it the {ordinal(rank)}-busiest week in this archive so far."
                )

    return paras


# ------------------------------------------------------------------ rendering

def render_digest_page(today, shows, history, total_tracked):
    start = (datetime.strptime(today, "%Y-%m-%d").date() - timedelta(days=WINDOW_DAYS - 1)).isoformat()
    by_borough = Counter(p.get("borough", "Unknown") for p in shows)
    n = len(shows)

    title = (
        f"New NYC gallery shows — week ending {pretty_date(today)}"
        if n else
        f"No new NYC gallery shows — week ending {pretty_date(today)}"
    )
    desc = (
        f"{n} New York art galleries posted new shows or updated listings in the week "
        f"ending {pretty_date(today)}, tracked across all five boroughs."
        if n else
        f"A quiet week: none of the {total_tracked} NYC art galleries we track posted "
        f"changes in the week ending {pretty_date(today)}."
    )
    url = f"{BASE_URL}/new-shows/{today}.html"

    paras = build_narrative(today, shows, by_borough, history, total_tracked)
    narrative = "\n      ".join(f"<p>{esc(p)}</p>" for p in paras)

    stats = f"""      <ul class="stats">
        <li><strong>{n}</strong><span>galleries with something new</span></li>
        <li><strong>{len(by_borough)}</strong><span>{'borough' if len(by_borough) == 1 else 'boroughs'} active</span></li>
        <li><strong>{total_tracked}</strong><span>galleries checked</span></li>
      </ul>"""

    # Per-borough table, then the full list grouped by borough.
    if n:
        rows = "\n".join(
            f"        <tr><td>{esc(b)}</td><td>{c}</td></tr>"
            for b, c in by_borough.most_common()
        )
        table = f"""      <table class="digest">
        <thead><tr><th>Borough</th><th>Galleries with changes</th></tr></thead>
        <tbody>
{rows}
        </tbody>
      </table>"""

        groups = []
        current = None
        items = []
        for p in shows:
            b = p.get("borough", "Unknown")
            if b != current:
                if items:
                    groups.append(f'      <h3>{esc(current)}</h3>\n      <ul class="galleries">\n'
                                  + "\n".join(items) + "\n      </ul>")
                    items = []
                current = b
            addr = f'<span class="meta">{esc(p["address"])}</span>' if p.get("address") else ""
            link = (f' — <a href="{esc(p["url"])}" target="_blank" rel="noopener">website ↗</a>'
                    if p.get("url") else "")
            items.append(f'        <li><strong>{esc(p["name"])}</strong>{link}{addr}</li>')
        if items:
            groups.append(f'      <h3>{esc(current)}</h3>\n      <ul class="galleries">\n'
                          + "\n".join(items) + "\n      </ul>")
        listing = "\n".join(groups)
        listing_head = "<h2>Galleries with something new this week</h2>"
    else:
        table = ""
        listing = ""
        listing_head = ""

    ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "datePublished": today,
        "dateModified": today,
        "url": url,
        "description": desc,
        "author": {"@type": "Organization", "name": "NYC Gallery Tracker"},
        "publisher": {"@type": "Organization", "name": "NYC Gallery Tracker"},
    }, indent=2)

    body = f"""    <p style="font-size:.9rem;color:#666;margin-bottom:0">
      <a href="/new-shows/">← All weekly reports</a></p>
    <h1>{esc(title.split(' — ')[0])}</h1>
    <p class="count">Week of {esc(pretty_date(start))} – {esc(pretty_date(today))}</p>
{stats}
      {narrative}
{table}
    {listing_head}
{listing}
    <div class="callout">
      <p><strong>How we know.</strong> Every day we fetch the website of each gallery on
      the map and compare it with the copy we saw the day before. When a page changes, that
      gallery gets flagged here and shows up green on the map for eight days. It's an
      imperfect signal — a gallery that never updates its site won't appear here even if it
      has a superb show up — but it's the closest thing to a live pulse of the city's
      gallery calendar that we know of.</p>
    </div>
    <p><a class="back" href="/">← See these on the interactive map</a></p>"""

    return page_shell(title=title, description=desc, url=url, body=body, ld_json=ld)


def render_archive_index(entries, total_tracked):
    """entries: list of (iso_date, count), newest first."""
    url = f"{BASE_URL}/new-shows/"
    title = "What's new in NYC galleries — weekly archive"
    desc = ("A week-by-week archive of which New York art galleries posted new shows, "
            "tracked continuously across all five boroughs.")

    if entries:
        total_changes = sum(c for _, c in entries)
        busiest_date, busiest_n = max(entries, key=lambda e: e[1])
        rows = "\n".join(
            f'        <tr><td><a href="/new-shows/{d}.html">Week ending {esc(pretty_date(d))}</a></td>'
            f"<td>{c}</td></tr>"
            for d, c in entries
        )
        table = f"""      <table class="digest">
        <thead><tr><th>Week</th><th>Galleries with something new</th></tr></thead>
        <tbody>
{rows}
        </tbody>
      </table>"""
        stats = f"""      <ul class="stats">
        <li><strong>{len(entries)}</strong><span>weeks on record</span></li>
        <li><strong>{total_changes}</strong><span>gallery updates logged</span></li>
        <li><strong>{busiest_n}</strong><span>busiest week ({pretty_date(busiest_date)})</span></li>
      </ul>"""
        intro = (
            f"We check {total_tracked} New York galleries every day to see whether anything "
            "has changed on their websites. This is the running record: one report a week, "
            "kept permanently, going back to the day we started."
        )
    else:
        table = ""
        stats = f"""      <ul class="stats">
        <li><strong>{total_tracked}</strong><span>galleries checked daily</span></li>
        <li><strong>5</strong><span>boroughs covered</span></li>
        <li><strong>7 days</strong><span>per report</span></li>
      </ul>"""
        intro = (
            f"We check {total_tracked} New York galleries every day to see whether "
            "anything has changed on their websites. This page is the running record — "
            "one report a week, kept permanently. The first report publishes at the end "
            "of the current week."
        )

    body = f"""    <h1>What's new in NYC galleries</h1>
    <p class="intro">{esc(intro)}</p>
{stats}
    <p>Most listings of New York exhibitions are compiled by hand and skew toward the
    same few dozen well-known galleries. This one is assembled automatically from the
    galleries' own websites, which means the small artist-run space in Bushwick counts
    exactly as much as the blue-chip room in Chelsea. If a gallery updated its site, it's
    in the report for that week.</p>
{table}
    <h2>Why a weekly record instead of a live list</h2>
    <p>A gallery show is a temporary thing. It goes up, runs six weeks or so, comes down,
    and unless someone wrote about it, it leaves very little trace — which is why it is
    surprisingly hard to find out what was on in a given month even a year later.</p>
    <p>Keeping a dated page for every week turns a live map into a record. Over time it
    accumulates into something the live map cannot show you: which months are busy and
    which are dead, how sharply the season restarts in September, how completely August
    empties out, and which districts are gaining or losing spaces.</p>
    <p>Each report stays at its own permanent address and is never rewritten. The list
    below grows by one entry a week.</p>

    <h2>How to use it</h2>
    <p>If you are planning a visit, the most recent report is the most useful page here:
    it tells you which galleries have posted something in the last seven days, which is
    the best available proxy for where the new work is. Cross-reference it with the
    <a href="/routes/">walking routes</a> to build an afternoon around whichever district
    has the most activity.</p>
    <p>If you are simply curious how the season moves, read down the table. The pattern
    is clearer than anyone expects.</p>
    <div class="callout">
      <p><strong>What counts as a change.</strong> We compare each gallery's homepage
      against the copy we fetched the day before. A new exhibition page, an updated set of
      dates, a fresh run of images — all of it registers. What we can't tell you is which
      of those it was, so treat each week's list as a shortlist of galleries worth
      checking rather than a confirmed schedule of openings.</p>
    </div>
    <p><a class="back" href="/">← Back to the interactive map</a></p>"""

    ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": title,
        "url": url,
        "description": desc,
    }, indent=2)

    return page_shell(title=title, description=desc, url=url, body=body, ld_json=ld)


# ----------------------------------------------------------------------- main

def archive_entries(history):
    """All published weeks, newest first, from history plus any files on disk."""
    entries = {}
    for iso, meta in history.items():
        entries[iso] = meta.get("count", 0)
    for path in OUT_DIR.glob("*.html"):
        if path.stem == "index":
            continue
        entries.setdefault(path.stem, 0)
    return sorted(entries.items(), key=lambda e: e[0], reverse=True)


def main():
    force = "--force" in sys.argv
    backfill_only = "--backfill" in sys.argv

    features = load_features()
    total_tracked = len(features)
    history = load_history()
    OUT_DIR.mkdir(exist_ok=True)

    if not backfill_only:
        today = date.today().isoformat()
        cutoff = (date.today() - timedelta(days=WINDOW_DAYS - 1)).isoformat()
        shows = new_since(features, cutoff)
        target = OUT_DIR / f"{today}.html"
        share = len(shows) / total_tracked if total_tracked else 0

        if share > MAX_PLAUSIBLE_SHARE:
            print(f"  REFUSING to publish: {len(shows)} of {total_tracked} galleries "
                  f"({share:.0%}) flagged in one week.")
            print(f"  That is above the {MAX_PLAUSIBLE_SHARE:.0%} plausibility ceiling and "
                  "almost certainly a detection fault,")
            print("  not a real event. Run `python3 scraper.py --dry-run` and check the")
            print("  detection tiers before publishing. No page was written.")
        elif target.exists() and not force:
            print(f"  {target} already exists; leaving it alone (use --force to rewrite).")
        else:
            target.write_text(render_digest_page(today, shows, history, total_tracked))
            print(f"  Wrote {target}  ({len(shows)} galleries with changes)")
            history[today] = {
                "count": len(shows),
                "tracked": total_tracked,
                "boroughs": dict(Counter(p.get("borough", "Unknown") for p in shows)),
            }
            save_history(history)

    entries = archive_entries(history)
    (OUT_DIR / "index.html").write_text(render_archive_index(entries, total_tracked))
    print(f"  Wrote {OUT_DIR / 'index.html'}  ({len(entries)} weeks in archive)")


if __name__ == "__main__":
    main()
