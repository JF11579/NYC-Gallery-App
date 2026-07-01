#!/usr/bin/env python3
"""
render_gallery_html.py — Bakes static gallery card HTML into index.html.

The gallery directory used to exist only as JS-rendered DOM built after the
map's 'load' event and a fetch of data/galleries.json resolve. Crawlers that
don't wait on that (e.g. AdSense's reviewer) saw an empty shell with a
"Loading galleries..." placeholder instead of real content.

This script renders the same cards server-side (well, build-side) into the
STATIC:CARDS / STATIC:COUNT comment blocks in index.html, so the raw HTML
already contains the full directory. The existing client-side JS still runs
on top and replaces this content with an identical (or freshly filtered)
version once the map/data load, restoring click-to-fly-map interactivity.

Run this after data/galleries.json is updated (see .github/workflows/scrape.yml):

    python3 render_gallery_html.py
"""

import json
import re
from datetime import date, timedelta
from pathlib import Path

DATA_PATH = Path("data/galleries.json")
INDEX_PATH = Path("index.html")

COUNT_RE = re.compile(r"(<!-- STATIC:COUNT -->)(.*?)(<!-- /STATIC:COUNT -->)", re.S)
CARDS_RE = re.compile(r"(<!-- STATIC:CARDS -->)(.*?)(<!-- /STATIC:CARDS -->)", re.S)


def esc(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_card(props, is_new):
    parts = [f'<div class="gallery-card{" gallery-card--new" if is_new else ""}">']
    if is_new:
        parts.append('<span class="updated-badge">New show</span><br>')
    parts.append(f'<div class="card-name">{esc(props["name"])}</div>')
    meta = f'<span class="card-boro">{esc(props["borough"])}</span>'
    if props.get("address"):
        meta += f' · {esc(props["address"])}'
    parts.append(f'<div class="card-meta">{meta}</div>')
    if props.get("url"):
        parts.append(
            f'<a class="card-link" href="{esc(props["url"])}" '
            f'target="_blank" rel="noopener">Visit website ↗</a>'
        )
    parts.append("</div>")
    return "".join(parts)


def main():
    geojson = json.loads(DATA_PATH.read_text())
    features = geojson["features"]
    cutoff = (date.today() - timedelta(days=8)).isoformat()

    def is_new(feature):
        last_updated = feature["properties"].get("last_updated") or ""
        return bool(last_updated) and last_updated >= cutoff

    sorted_features = sorted(
        features,
        key=lambda f: (0 if is_new(f) else 1, f["properties"]["name"].lower()),
    )

    cards_html = "\n".join(
        render_card(f["properties"], is_new(f)) for f in sorted_features
    )
    count_html = f"{len(sorted_features)} galleries — all five boroughs"

    html = INDEX_PATH.read_text()
    html = COUNT_RE.sub(lambda m: m.group(1) + count_html + m.group(3), html)
    html = CARDS_RE.sub(lambda m: m.group(1) + "\n" + cards_html + "\n" + m.group(3), html)
    INDEX_PATH.write_text(html)
    print(f"Baked {len(sorted_features)} gallery cards into index.html")


if __name__ == "__main__":
    main()
