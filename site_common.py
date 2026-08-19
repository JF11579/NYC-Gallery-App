#!/usr/bin/env python3
"""
site_common.py — Shared chrome for every generated page on NYC Gallery Tracker.

render_area_pages.py predates this module and keeps its own copy of the styles;
the CSS here is written to match it so borough pages, guides, walking routes, and
weekly digests all look like one site. New generators should import from here:

    from site_common import BASE_URL, esc, slugify, page_shell

Keeping the shell in one place matters more than it sounds: Google's site-quality
review reads the whole domain, not one page, and a site that looks stitched
together from three different templates reads as lower quality than one that
doesn't.
"""

import math
import re
from datetime import date

BASE_URL = "https://nyc-gallery-app.netlify.app"

# Districts we generate walking routes for, in the order they appear in nav.
# Anything below ~5 galleries doesn't make a walk worth publishing.
ROUTE_MIN_GALLERIES = 5


def esc(value):
    """Escape a value for insertion into HTML text or a double-quoted attribute."""
    return (
        str(value).replace("&", "&amp;").replace("<", "&lt;")
        .replace(">", "&gt;").replace('"', "&quot;")
    )


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def haversine_km(a, b):
    """Great-circle distance in km between two [lon, lat] points."""
    (lon1, lat1), (lon2, lat2) = a, b
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def walking_minutes(km):
    """Minutes to walk a distance at a realistic city pace (~4.5 km/h with lights)."""
    return max(1, round(km / 4.5 * 60))


def fmt_distance(km):
    """Human distance. New Yorkers think in minutes and blocks, not kilometres."""
    miles = km * 0.621371
    if miles < 0.1:
        return "a few steps"
    return f"{miles:.1f} mi"


STYLES = """
    :root { --blue:#1565c0; --ink:#1a1a1a; --muted:#666; }
    * { box-sizing:border-box; }
    body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
           line-height:1.65; color:var(--ink); margin:0; background:#fafafa; }
    header { background:var(--blue); color:#fff; padding:14px 20px; }
    header a { color:#fff; text-decoration:none; font-weight:600; }
    main { max-width:820px; margin:0 auto; padding:24px 20px 60px; }
    h1 { font-size:1.7rem; margin:.2em 0 .4em; line-height:1.25; }
    h2 { font-size:1.25rem; margin:1.8em 0 .4em; }
    h3 { font-size:1.05rem; margin:1.5em 0 .3em; }
    p { margin:.7em 0; }
    .intro { font-size:1.1rem; color:#333; }
    .count { color:#555; font-size:.95rem; margin:.5em 0 1.2em; }
    ul.galleries { list-style:none; padding:0; }
    ul.galleries li { background:#fff; border:1px solid #e5e5e5; border-radius:8px;
                      padding:12px 14px; margin-bottom:8px; }
    .meta { display:block; color:var(--muted); font-size:.9rem; margin-top:2px; }
    .new { background:#2e7d32; color:#fff; font-size:.72rem; font-weight:700;
           padding:2px 7px; border-radius:10px; vertical-align:middle; }
    a { color:var(--blue); }
    ol.route { list-style:none; padding:0; counter-reset:stop; }
    ol.route li { background:#fff; border:1px solid #e5e5e5; border-radius:8px;
                  padding:12px 14px 12px 52px; margin-bottom:8px; position:relative; }
    ol.route li:before { counter-increment:stop; content:counter(stop);
                         position:absolute; left:14px; top:12px; width:26px; height:26px;
                         background:var(--blue); color:#fff; border-radius:50%;
                         font-size:.85rem; font-weight:700; display:flex;
                         align-items:center; justify-content:center; }
    .leg { display:block; color:var(--muted); font-size:.85rem; margin-top:6px;
           padding-top:6px; border-top:1px dashed #e0e0e0; }
    .callout { background:#eef4fb; border-left:4px solid var(--blue);
               padding:14px 16px; border-radius:0 8px 8px 0; margin:1.4em 0; }
    .callout p:first-child { margin-top:0; }
    .callout p:last-child { margin-bottom:0; }
    .stats { display:flex; flex-wrap:wrap; gap:10px; margin:1.2em 0; padding:0; list-style:none; }
    .stats li { background:#fff; border:1px solid #e5e5e5; border-radius:8px;
                padding:10px 14px; flex:1 1 140px; }
    .stats strong { display:block; font-size:1.4rem; line-height:1.2; }
    .stats span { color:var(--muted); font-size:.85rem; }
    table.digest { width:100%; border-collapse:collapse; margin:1em 0; background:#fff; }
    table.digest th, table.digest td { text-align:left; padding:9px 12px;
                                       border-bottom:1px solid #eee; font-size:.95rem; }
    table.digest th { background:#f2f5f9; font-size:.85rem; text-transform:uppercase;
                      letter-spacing:.03em; color:#444; }
    nav.areas { margin-top:40px; padding-top:20px; border-top:1px solid #ddd;
                font-size:.92rem; color:#444; }
    nav.areas p { margin:.35em 0; }
    .back { display:inline-block; margin-top:24px; font-weight:600; }
    footer.sitefoot { margin-top:40px; padding-top:18px; border-top:1px solid #ddd;
                      font-size:.9rem; color:var(--muted); }
    footer.sitefoot a { margin-right:14px; }
"""


def page_shell(*, title, description, url, body, ld_json=None, extra_head=""):
    """Wrap page body HTML in the shared document shell.

    Every generated page gets a canonical URL, an OG card, and the same styles.
    `ld_json` is a pre-serialised JSON-LD string, or None.
    """
    ld_block = ""
    if ld_json:
        ld_block = f'  <script type="application/ld+json">\n{ld_json}\n  </script>\n'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{esc(title)}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{esc(description)}">
  <link rel="canonical" href="{url}">
  <link rel="icon" href="/icons/icon-192.png">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="NYC Gallery Tracker">
  <meta property="og:url" content="{url}">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:image" content="{BASE_URL}/docs/map.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="{BASE_URL}/docs/map.png">
{ld_block}{extra_head}  <style>{STYLES}  </style>
</head>
<body>
  <header><a href="/">← NYC Gallery Tracker — interactive map</a></header>
  <main>
{body}
{site_footer()}
  </main>
</body>
</html>
"""


def site_footer(current=""):
    """Shared footer. Cross-links the standalone guides from every generated page."""
    links = [
        ("/", "Interactive map"),
        ("/visiting-nyc-galleries.html", "How to visit NYC galleries"),
        ("/routes/", "Gallery walking routes"),
        ("/new-shows/", "What's new this week"),
        ("/about.html", "About"),
    ]
    rendered = " ".join(
        f'<a href="{href}">{esc(label)}</a>' for href, label in links if href != current
    )
    return f"""    <footer class="sitefoot">
      {rendered}
      <p>Updated {date.today().strftime('%B %-d, %Y')} · NYC Gallery Tracker tracks
      art galleries across all five boroughs and checks each one for new shows every week.</p>
    </footer>"""
