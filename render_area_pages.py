#!/usr/bin/env python3
"""
render_area_pages.py — Generates SEO landing pages for boroughs and neighborhoods.

The homepage is one big interactive map; great for users, but for SEO it's a single
URL. People search "art galleries in Chelsea", "Bushwick galleries", "art galleries
Brooklyn" — long-tail queries a single-page app can't rank for. This script reads
data/galleries.json and bakes a static, crawlable page per AREA:

  • one page per borough (all 5)                        -> /galleries/manhattan.html ...
  • one page per major art neighborhood (>= MIN_GALLERIES) -> /galleries/chelsea.html ...

Each page has a unique title/description, real intro copy, the gallery list, schema.org
ItemList structured data, and internal links to sibling areas + the map. It also:

  • rewrites sitemap.xml to include every generated page, and
  • injects a "Browse by neighborhood" link block into index.html
    (between <!-- STATIC:AREAS --> markers) so the pages are internally linked.

Neighborhoods are assigned by nearest-centroid within a radius cap (see NEIGHBORHOODS /
RADIUS_KM). It's approximate — good enough for landing pages; a gallery near a boundary
may land in an adjacent area. Every gallery always appears on its borough page.

Run after data/galleries.json updates (wired into .github/workflows/scrape.yml):

    python3 render_area_pages.py
"""

import json
import math
import re
from datetime import date, timedelta
from pathlib import Path

DATA_PATH = Path("data/galleries.json")
INDEX_PATH = Path("index.html")
SITEMAP_PATH = Path("sitemap.xml")
OUT_DIR = Path("galleries")
BASE_URL = "https://nyc-gallery-app.netlify.app"

MIN_GALLERIES = 4      # don't generate a neighborhood page thinner than this
RADIUS_KM = 1.4        # a gallery must be within this of a centroid to get its label
NEW_DAYS = 8           # "new show" window, matching render_gallery_html.py

AREAS_RE = re.compile(r"(<!-- STATIC:AREAS -->)(.*?)(<!-- /STATIC:AREAS -->)", re.S)

# Neighborhood centroids as [lon, lat] (galleries.json uses lon,lat order).
# Only the dense art districts — everything else falls back to the borough page.
NEIGHBORHOODS = {
    # Manhattan
    "Chelsea":                 (-74.0014, 40.7465),
    "SoHo":                    (-74.0016, 40.7233),
    "Tribeca":                 (-74.0089, 40.7163),
    "Lower East Side":         (-73.9857, 40.7150),
    "East Village":            (-73.9843, 40.7265),
    "Greenwich Village":       (-74.0021, 40.7336),
    "Upper East Side":         (-73.9626, 40.7736),
    "Midtown":                 (-73.9840, 40.7549),
    "Harlem":                  (-73.9465, 40.8116),
    # Brooklyn
    "Bushwick":                (-73.9213, 40.6942),
    "Williamsburg":            (-73.9571, 40.7141),
    "Greenpoint":              (-73.9510, 40.7304),
    "DUMBO":                   (-73.9887, 40.7033),
    "Bedford-Stuyvesant":      (-73.9412, 40.6872),
    "Gowanus":                 (-73.9890, 40.6748),
    "Park Slope":              (-73.9776, 40.6710),
    "Red Hook":                (-74.0112, 40.6772),
    "Sunset Park":             (-74.0100, 40.6553),
    "Crown Heights":           (-73.9442, 40.6694),
}

# Which borough each neighborhood belongs to (for grouping the nav).
NEIGHBORHOOD_BOROUGH = {
    "Chelsea": "Manhattan", "SoHo": "Manhattan", "Tribeca": "Manhattan",
    "Lower East Side": "Manhattan", "East Village": "Manhattan",
    "Greenwich Village": "Manhattan", "Upper East Side": "Manhattan",
    "Midtown": "Manhattan", "Harlem": "Manhattan",
    "Bushwick": "Brooklyn", "Williamsburg": "Brooklyn", "Greenpoint": "Brooklyn",
    "DUMBO": "Brooklyn", "Bedford-Stuyvesant": "Brooklyn", "Gowanus": "Brooklyn",
    "Park Slope": "Brooklyn", "Red Hook": "Brooklyn", "Sunset Park": "Brooklyn",
    "Crown Heights": "Brooklyn",
}

BOROUGHS = ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"]

# Hand-written intros for the areas most likely to draw search traffic. Anything
# without an entry gets a templated intro (see intro_for()).
INTROS = {
    "Manhattan": "From the blue-chip galleries of Chelsea to the artist-run spaces of the Lower East Side, Manhattan holds the densest concentration of art galleries in New York City. This is a live map and directory of every one we track across the borough.",
    "Brooklyn": "Brooklyn's gallery scene has exploded beyond Williamsburg and DUMBO into Bushwick, Bed-Stuy, and beyond — a mix of commercial galleries, non-profits, and artist-run project spaces. Here's a live map of every Brooklyn gallery we track.",
    "Queens": "Queens punches above its weight, anchored by the Long Island City art district and institutions like MoMA PS1 and SculptureCenter. Here are the galleries and art spaces we track across the borough.",
    "Bronx": "The Bronx doesn't have the gallery-scene reputation of the other boroughs, but there's a genuine, active scene here for anyone paying attention. These are the art spaces we track across the borough.",
    "Staten Island": "Staten Island's art scene is small but real, centered on Snug Harbor. These are the art spaces we track on the island.",
    "Chelsea": "Chelsea is the heart of the New York gallery world — hundreds of galleries packed into the West 20s between 10th and 11th Avenues, from mega-galleries to intimate rooms. Here's a live map of the Chelsea galleries we track.",
    "SoHo": "Once the center of the downtown art world and now a mix of returning galleries and design showrooms, SoHo still rewards a gallery walk along its cast-iron streets. Here are the SoHo galleries we track.",
    "Lower East Side": "The Lower East Side is where much of New York's younger, experimental gallery energy lives — small storefront spaces packed between Orchard, Henry, and Canal. Here's a live map of the LES galleries we track.",
    "Tribeca": "Tribeca has quietly become one of the city's fastest-growing gallery districts, with dozens of spaces tucked into its lofts and ground floors. Here are the Tribeca galleries we track.",
    "Upper East Side": "The Upper East Side pairs its museums with a cluster of established galleries, many specializing in modern and postwar work. Here are the UES galleries we track.",
    "Bushwick": "Bushwick is Brooklyn's most concentrated artist-run gallery district — a sprawl of project spaces, studios, and non-profits, busiest during its open-studio weekends. Here's a live map of the Bushwick galleries we track.",
    "Williamsburg": "Williamsburg helped kick off Brooklyn's gallery boom and still holds a strong mix of galleries and art spaces near the waterfront. Here are the Williamsburg galleries we track.",
    "DUMBO": "DUMBO packs a dense cluster of galleries and non-profits into a few cobblestoned blocks under the bridges, with river views as a bonus. Here are the DUMBO galleries we track.",
}


def haversine_km(a, b):
    (lon1, lat1), (lon2, lat2) = a, b
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def assign_neighborhood(coords):
    """Return the nearest neighborhood within RADIUS_KM, or None."""
    best, best_d = None, RADIUS_KM
    for hood, centroid in NEIGHBORHOODS.items():
        d = haversine_km(coords, centroid)
        if d < best_d:
            best, best_d = hood, d
    return best


def esc(value):
    return (
        str(value).replace("&", "&amp;").replace("<", "&lt;")
        .replace(">", "&gt;").replace('"', "&quot;")
    )


def intro_for(area, borough):
    if area in INTROS:
        return INTROS[area]
    where = area if area in BOROUGHS else f"{area}, {borough}"
    return (
        f"A live map and directory of the art galleries we track in {where}. "
        "Green markers flag galleries that have posted something new in the past week."
    )


def render_page(area, borough, galleries, all_areas, cutoff):
    slug = slugify(area)
    is_borough = area in BOROUGHS
    where = area if is_borough else f"{area}, {borough}"
    title = f"Art Galleries in {where} — Map & Directory | NYC Gallery Tracker"
    desc = (
        f"Find {len(galleries)} art galleries in {where}. "
        "An interactive, weekly-updated map and directory of NYC art galleries."
    )
    url = f"{BASE_URL}/galleries/{slug}.html"

    def is_new(g):
        lu = g["properties"].get("last_updated") or ""
        return bool(lu) and lu >= cutoff

    galleries = sorted(galleries, key=lambda g: (0 if is_new(g) else 1,
                                                 g["properties"]["name"].lower()))

    # gallery list markup
    cards = []
    items = []
    for i, g in enumerate(galleries, 1):
        p = g["properties"]
        new = is_new(g)
        badge = '<span class="new">New show</span> ' if new else ""
        addr = f' · {esc(p["address"])}' if p.get("address") else ""
        link = (f' — <a href="{esc(p["url"])}" target="_blank" rel="noopener">website ↗</a>'
                if p.get("url") else "")
        cards.append(
            f'<li>{badge}<strong>{esc(p["name"])}</strong>'
            f'<span class="meta">{esc(p.get("borough",""))}{addr}</span>{link}</li>'
        )
        item = {"@type": "ListItem", "position": i,
                "item": {"@type": "ArtGallery", "name": p["name"]}}
        if p.get("address"):
            item["item"]["address"] = p["address"]
        if p.get("url"):
            item["item"]["url"] = p["url"]
        items.append(item)

    # sibling-area nav grouped by borough
    nav_groups = []
    for b in BOROUGHS:
        sibs = [a for a in all_areas if all_areas[a]["borough"] == b and a != area]
        if not sibs:
            continue
        links = " · ".join(
            f'<a href="/galleries/{slugify(a)}.html">{esc(a)}</a>' for a in sorted(sibs)
        )
        nav_groups.append(f"<p><strong>{esc(b)}:</strong> {links}</p>")
    nav_html = "\n".join(nav_groups)

    ld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": f"Art Galleries in {where}",
        "url": url,
        "description": desc,
        "mainEntity": {"@type": "ItemList", "numberOfItems": len(galleries),
                       "itemListElement": items},
    }

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{esc(title)}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{esc(desc)}">
  <link rel="canonical" href="{url}">
  <link rel="icon" href="/icons/icon-192.png">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="NYC Gallery Tracker">
  <meta property="og:url" content="{url}">
  <meta property="og:title" content="{esc('Art Galleries in ' + where)}">
  <meta property="og:description" content="{esc(desc)}">
  <meta property="og:image" content="{BASE_URL}/docs/map.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="{BASE_URL}/docs/map.png">
  <script type="application/ld+json">
{json.dumps(ld, indent=2)}
  </script>
  <style>
    :root {{ --blue:#1565c0; }}
    * {{ box-sizing:border-box; }}
    body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
           line-height:1.5; color:#1a1a1a; margin:0; background:#fafafa; }}
    header {{ background:var(--blue); color:#fff; padding:14px 20px; }}
    header a {{ color:#fff; text-decoration:none; font-weight:600; }}
    main {{ max-width:820px; margin:0 auto; padding:24px 20px 60px; }}
    h1 {{ font-size:1.7rem; margin:.2em 0; }}
    .intro {{ font-size:1.05rem; color:#333; }}
    .count {{ color:#555; font-size:.95rem; margin:.5em 0 1.2em; }}
    ul.galleries {{ list-style:none; padding:0; }}
    ul.galleries li {{ background:#fff; border:1px solid #e5e5e5; border-radius:8px;
                       padding:12px 14px; margin-bottom:8px; }}
    ul.galleries strong {{ display:inline; }}
    .meta {{ display:block; color:#666; font-size:.9rem; margin-top:2px; }}
    .new {{ background:#2e7d32; color:#fff; font-size:.72rem; font-weight:700;
            padding:2px 7px; border-radius:10px; vertical-align:middle; }}
    a {{ color:var(--blue); }}
    nav.areas {{ margin-top:40px; padding-top:20px; border-top:1px solid #ddd;
                 font-size:.92rem; color:#444; }}
    nav.areas p {{ margin:.35em 0; }}
    .back {{ display:inline-block; margin-top:24px; font-weight:600; }}
  </style>
</head>
<body>
  <header><a href="/">← NYC Gallery Tracker — interactive map</a></header>
  <main>
    <h1>Art Galleries in {esc(where)}</h1>
    <p class="intro">{esc(intro_for(area, borough))}</p>
    <p class="count">{len(galleries)} galleries {'· green = new show this week' if any(is_new(g) for g in galleries) else ''}</p>
    <ul class="galleries">
      {chr(10).join('      ' + c for c in cards)}
    </ul>
    <a class="back" href="/">← See all of these on the interactive map</a>
    <nav class="areas">
      <p><strong>Browse other areas:</strong></p>
      {nav_html}
    </nav>
  </main>
</body>
</html>
"""


def build_sitemap(area_slugs):
    today = date.today().isoformat()
    urls = [
        (f"{BASE_URL}/", "daily", "1.0"),
        (f"{BASE_URL}/about.html", "monthly", "0.5"),
        (f"{BASE_URL}/privacy.html", "yearly", "0.3"),
    ]
    for slug in area_slugs:
        urls.append((f"{BASE_URL}/galleries/{slug}.html", "weekly", "0.7"))
    body = "\n".join(
        f"  <url>\n    <loc>{loc}</loc>\n    <lastmod>{today}</lastmod>\n"
        f"    <changefreq>{cf}</changefreq>\n    <priority>{pr}</priority>\n  </url>"
        for loc, cf, pr in urls
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{body}\n</urlset>\n")


def inject_index_nav(all_areas):
    """Fill the <!-- STATIC:AREAS --> block in index.html with area links."""
    if not INDEX_PATH.exists():
        return
    html = INDEX_PATH.read_text()
    if not AREAS_RE.search(html):
        print("  NOTE: no <!-- STATIC:AREAS --> markers in index.html; skipping nav injection")
        return
    groups = []
    for b in BOROUGHS:
        areas = sorted(a for a in all_areas if all_areas[a]["borough"] == b)
        if not areas:
            continue
        links = " · ".join(
            f'<a href="/galleries/{slugify(a)}.html">{esc(a)}</a>' for a in areas
        )
        groups.append(f'<p class="area-row"><strong>{esc(b)}:</strong> {links}</p>')
    block = ('\n<section class="browse-areas">\n'
             '<h2>Browse galleries by neighborhood</h2>\n'
             + "\n".join(groups) + "\n</section>\n")
    html = AREAS_RE.sub(lambda m: m.group(1) + block + m.group(3), html)
    INDEX_PATH.write_text(html)
    print("  Injected neighborhood nav into index.html")


def main():
    geojson = json.loads(DATA_PATH.read_text())
    features = geojson["features"]
    cutoff = (date.today() - timedelta(days=NEW_DAYS)).isoformat()

    # group galleries by borough and by neighborhood
    by_borough = {b: [] for b in BOROUGHS}
    by_hood = {}
    for g in features:
        b = g["properties"].get("borough", "")
        if b in by_borough:
            by_borough[b].append(g)
        hood = assign_neighborhood(g["geometry"]["coordinates"])
        if hood:
            by_hood.setdefault(hood, []).append(g)

    # decide which areas to generate: all non-empty boroughs + neighborhoods >= MIN
    all_areas = {}  # area name -> {"borough":..., "galleries":[...]}
    for b in BOROUGHS:
        if by_borough[b]:
            all_areas[b] = {"borough": b, "galleries": by_borough[b]}
    for hood, gs in by_hood.items():
        if len(gs) >= MIN_GALLERIES:
            all_areas[hood] = {"borough": NEIGHBORHOOD_BOROUGH[hood], "galleries": gs}

    OUT_DIR.mkdir(exist_ok=True)
    slugs = []
    for area, info in sorted(all_areas.items()):
        slug = slugify(area)
        slugs.append(slug)
        page = render_page(area, info["borough"], info["galleries"], all_areas, cutoff)
        (OUT_DIR / f"{slug}.html").write_text(page)
        kind = "borough" if area in BOROUGHS else f"neighborhood/{info['borough']}"
        print(f"  {area:22s} [{kind:22s}] {len(info['galleries']):3d} galleries -> galleries/{slug}.html")

    SITEMAP_PATH.write_text(build_sitemap(slugs))
    print(f"  Wrote sitemap.xml with {len(slugs) + 3} URLs")

    inject_index_nav(all_areas)
    print(f"Done. Generated {len(slugs)} area pages.")


if __name__ == "__main__":
    main()
