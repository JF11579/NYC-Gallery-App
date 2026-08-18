#!/usr/bin/env python3
"""
build_site.py — Runs every generator in the right order.

Order matters:

  1. render_gallery_html.py   bakes the gallery cards into index.html
  2. render_guides.py         writes the guide + walking routes
  3. render_digest_pages.py   writes this week's digest page + archive index
  4. render_area_pages.py     writes the area pages AND rebuilds sitemap.xml

render_area_pages.py goes last because its sitemap builder discovers the guide,
route and digest pages from disk. Run it first and they are missing from the
sitemap until the next build.

This does not run scraper.py — that hits ~230 external sites and belongs on its
own schedule. Run it separately, or let the daily GitHub Action do it.

Usage:
    python3 build_site.py
"""

import subprocess
import sys
from pathlib import Path

STEPS = [
    ("Baking gallery cards into index.html", "render_gallery_html.py"),
    ("Building guide + walking routes", "render_guides.py"),
    ("Publishing weekly digest archive", "render_digest_pages.py"),
    ("Building area pages + sitemap", "render_area_pages.py"),
]


def main():
    failed = []
    for label, script in STEPS:
        if not Path(script).exists():
            print(f"\n=== {label}\n  SKIP: {script} not found")
            continue
        print(f"\n=== {label}  ({script})")
        result = subprocess.run([sys.executable, script])
        if result.returncode != 0:
            print(f"  FAILED: {script} exited {result.returncode}")
            failed.append(script)

    print()
    if failed:
        print(f"Build finished with {len(failed)} failure(s): {', '.join(failed)}")
        sys.exit(1)
    print("Build complete.")


if __name__ == "__main__":
    main()
