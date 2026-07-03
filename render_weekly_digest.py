#!/usr/bin/env python3
"""
render_weekly_digest.py — Sends the weekly "new shows" email via Buttondown.

Reads data/galleries.json, finds galleries whose last_updated falls in the
past 7 days, and sends an email to all subscribers via the Buttondown API.
If nothing changed this week, it skips creating an email entirely rather
than sending an empty digest.

Requires the BUTTONDOWN_API_KEY environment variable (Settings > API in
the Buttondown dashboard). Intended to run weekly via GitHub Actions,
after scraper.py has updated data/galleries.json for the week.

    export BUTTONDOWN_API_KEY='...'
    python3 render_weekly_digest.py
"""

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

DATA_PATH = Path("data/galleries.json")
API_URL = "https://api.buttondown.com/v1/emails"


def build_digest(features, window_days=7):
    cutoff = (date.today() - timedelta(days=window_days)).isoformat()
    new_shows = [
        f["properties"] for f in features
        if f["properties"].get("last_updated") and f["properties"]["last_updated"] >= cutoff
    ]
    new_shows.sort(key=lambda p: (p["borough"], p["name"].lower()))
    return new_shows


def render_body(new_shows):
    lines = [
        f"This week, {len(new_shows)} NYC gallery show{'s' if len(new_shows) != 1 else ''} "
        "changed or opened something new:",
        "",
    ]
    current_boro = None
    for props in new_shows:
        if props["borough"] != current_boro:
            current_boro = props["borough"]
            lines.append(f"### {current_boro}")
            lines.append("")
        entry = f"- **{props['name']}**"
        if props.get("address"):
            entry += f" — {props['address']}"
        if props.get("url"):
            entry += f" — [visit website]({props['url']})"
        lines.append(entry)
    lines.append("")
    lines.append("[See the full map and directory](https://nyc-gallery-app.netlify.app/)")
    return "\n".join(lines)


def main():
    api_key = os.environ.get("BUTTONDOWN_API_KEY", "").strip()
    if not api_key:
        print("BUTTONDOWN_API_KEY not set; skipping.", file=sys.stderr)
        sys.exit(1)

    geojson = json.loads(DATA_PATH.read_text())
    new_shows = build_digest(geojson["features"])

    if not new_shows:
        print("No new shows this week — skipping digest.")
        return

    subject = f"NYC Gallery Tracker: {len(new_shows)} new show{'s' if len(new_shows) != 1 else ''} this week"
    body = render_body(new_shows)

    resp = requests.post(
        API_URL,
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        },
        json={"subject": subject, "body": body, "status": "about_to_send"},
        timeout=30,
    )
    resp.raise_for_status()
    print(f"Sent: {subject} ({len(new_shows)} shows)")


if __name__ == "__main__":
    main()
