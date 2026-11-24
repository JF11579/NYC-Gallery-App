#!/usr/bin/env python3
"""
render_holiday_page.py — Builds /nyc-art-galleries-holidays.html.

A page for the people in New York between Thanksgiving and New Year's: which
galleries have said they're open or closed on each holiday, what the normal
week looks like, and which galleries are a short walk from the big holiday
sights (the Rockefeller Center tree, the Fifth Avenue windows, the holiday
markets).

Everything on it comes from our own data:
  * data/holiday_hours.json  (fetch_holiday_hours.py, run a few times a season)
  * data/galleries.json      (coordinates)
The build never calls an API, so this runs safely in the daily build.

Usage:
    python3 render_holiday_page.py
"""

import json
from datetime import date, timedelta
from pathlib import Path

from site_common import (BASE_URL, esc, fmt_distance, haversine_km, page_shell,
                         walking_minutes)

HOURS_PATH = Path("data/holiday_hours.json")
GALLERIES_PATH = Path("data/galleries.json")
OUT_PATH = Path("nyc-art-galleries-holidays.html")
URL = f"{BASE_URL}/{OUT_PATH.name}"

DAY_ABBR = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

# Holiday sights tourists head for, as [lon, lat].
SIGHTS = [
    ("The Rockefeller Center tree and the Fifth Avenue windows",
     [-73.9787, 40.7587],
     "The tree, the rink and the department-store windows along Fifth Avenue "
     "are the most crowded few blocks in the city in December. The galleries "
     "around 57th Street, a short walk north, are warm and quiet, and most are free."),
    ("Bryant Park Winter Village",
     [-73.9832, 40.7536],
     "The rink and the holiday shops fill the park. Midtown's galleries are "
     "mostly upstairs in office buildings, so check the lobby directory."),
    ("Columbus Circle Holiday Market",
     [-73.9819, 40.7681],
     "The market sits at the southwest corner of Central Park, a few minutes "
     "from the galleries on 57th Street and Central Park South."),
    ("Union Square Holiday Market",
     [-73.9911, 40.7359],
     "Union Square is the meeting point for galleries in Greenwich Village, "
     "Flatiron and the East Village."),
]
NEAR_KM = 0.8   # about a ten-minute walk
NEAR_SHOW = 8


def season_holidays(today):
    """(date, name, is_closing_day) for this season's holidays, Thanksgiving to New Year's."""
    year = today.year if today.month >= 6 else today.year - 1
    nov1 = date(year, 11, 1)
    thanksgiving = nov1 + timedelta(days=(3 - nov1.weekday()) % 7 + 21)
    return [
        (thanksgiving, "Thanksgiving", True),
        (thanksgiving + timedelta(days=1), "Black Friday", False),
        (thanksgiving + timedelta(days=2), "Saturday after Thanksgiving", False),
        (date(year, 12, 24), "Christmas Eve", False),
        (date(year, 12, 25), "Christmas Day", True),
        (date(year, 12, 26), "December 26", False),
        (date(year, 12, 31), "New Year's Eve", False),
        (date(year + 1, 1, 1), "New Year's Day", True),
    ]


def fmt_days(days):
    """Google days (0=Sun) -> 'Tue–Sat', 'Thu–Sun', 'daily'. Weeks run Monday-first."""
    if not days:
        return ""
    if len(days) == 7:
        return "daily"
    mon = sorted(d or 7 for d in days)          # Sunday becomes 7
    abbr = lambda d: DAY_ABBR[d % 7]
    if mon == list(range(mon[0], mon[-1] + 1)) and len(mon) > 2:
        return f"{abbr(mon[0])}–{abbr(mon[-1])}"
    return ", ".join(abbr(d) for d in mon)


def name_list(gs):
    """Names, with a gallery's several locations collapsed: 'Karma Gallery (2 locations)'."""
    from collections import Counter
    c = Counter(g["name"] for g in gs)
    return ", ".join(esc(n) + (f" ({k} locations)" if k > 1 else "") for n, k in c.items())


def nice_date(d):
    return d.strftime("%A, %B %-d")


def main():
    if not HOURS_PATH.exists():
        print(f"  SKIP: {HOURS_PATH} not found (run fetch_holiday_hours.py)")
        return
    hours = json.loads(HOURS_PATH.read_text())
    runs = hours.get("runs", [])
    hours = hours["galleries"]
    feats = json.loads(GALLERIES_PATH.read_text())["features"]

    galleries = []
    for f in feats:
        p = f["properties"]
        h = hours.get(f"{p['name']}|{p['address']}", {})
        galleries.append({"name": p["name"], "address": p["address"].split(", New York")[0]
                          .split(", Brooklyn")[0], "borough": p.get("borough", ""),
                          "url": p.get("url", ""), "coords": f["geometry"]["coordinates"],
                          "open_days": h.get("open_days", []),
                          "special": h.get("special", {})})
    total = len(galleries)
    today = date.today()

    def link(g):
        name = esc(g["name"])
        return (f'<a href="{esc(g["url"])}" target="_blank" rel="noopener">{name}</a>'
                if g["url"] else name)

    # ------------------------------------------------ holiday-by-holiday
    sections, earlier = [], []
    for day, label, closing_day in season_holidays(today):
        iso = day.isoformat()
        posted = [g for g in galleries if iso in g["special"]]
        opened = sorted((g for g in posted if g["special"][iso]), key=lambda g: g["name"].lower())
        closed = sorted((g for g in posted if not g["special"][iso]), key=lambda g: g["name"].lower())
        if day < today:
            if posted:
                earlier.append(f"<li><strong>{esc(label)}</strong> ({day.strftime('%B %-d')}): "
                               f"{len(closed)} galleries said they were closed, "
                               f"{len(opened)} said they were open.</li>")
            continue
        head = f"<h3>{esc(label)}: {nice_date(day)}</h3>"
        if not posted:
            if (day - today).days <= 6 and str(today) in runs:
                body = ("<p>No gallery we track has posted special hours for this day on "
                        "Google. Expect most to keep their usual hours, and check before "
                        "you go.</p>")
            else:
                body = ("<p>Galleries post holiday hours on Google about a week ahead. "
                        "We'll fill this in around "
                        f"{(day - timedelta(days=6)).strftime('%B %-d')}. Until then, "
                        "assume many galleries will be closed.</p>")
            sections.append(head + "\n" + body)
            continue
        lines = [head,
                 f'<ul class="stats"><li><strong>{len(closed)}</strong><span>said they are '
                 f'closed</span></li><li><strong>{len(opened)}</strong><span>said they are '
                 f'open</span></li><li><strong>{total - len(posted)}</strong><span>have not '
                 f'posted holiday hours</span></li></ul>']
        if opened:
            lines.append("<p><strong>Open, with the hours they posted:</strong></p>"
                         '<ul class="galleries">')
            lines += [f'<li><strong>{link(g)}</strong> <span class="meta">{esc(g["address"])}, '
                      f'{esc(g["borough"])} · {esc(", ".join(g["special"][iso]))}</span></li>'
                      for g in opened]
            lines.append("</ul>")
        elif closing_day:
            lines.append("<p><strong>Not one gallery we track has told Google it will be "
                         "open.</strong> Plan on galleries being closed, and spend the day "
                         "on a museum or the holiday sights instead.</p>")
        if closed:
            lines.append(f"<details><summary>The {len(closed)} galleries that said they are "
                         "closed</summary><p>" + name_list(closed) + "</p></details>")
        if closing_day:
            lines.append("<p>Galleries that haven't posted anything are listed on Google "
                         "with their usual hours, which may not hold on a holiday. Check a "
                         "gallery's own website or call before making a special trip.</p>")
        else:
            lines.append("<p>Galleries keeping their usual hours don't post anything, so "
                         f"most of the other {total - len(posted)} are probably open as "
                         "normal. Still, check a gallery's own website before making a "
                         "special trip.</p>")
        sections.append("\n".join(lines))

    # ------------------------------------------------ normal week
    with_hours = [g for g in galleries if g["open_days"]]
    pct = {d: round(100 * sum(d in g["open_days"] for g in with_hours) / len(with_hours))
           for d in range(7)}
    week_rows = "".join(f"<tr><td>{['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'][d]}</td>"
                        f"<td>{pct[d]}%</td></tr>" for d in [1, 2, 3, 4, 5, 6, 0])

    # ------------------------------------------------ near the sights
    sight_blocks = []
    for title, point, blurb in SIGHTS:
        near = sorted(((haversine_km(point, g["coords"]), g) for g in galleries
                       if g["borough"] == "Manhattan"), key=lambda t: t[0])
        near = [(km, g) for km, g in near if km <= NEAR_KM]
        if not near:
            continue
        items = "".join(
            f'<li><strong>{link(g)}</strong><span class="meta">{esc(g["address"])} · '
            f'{walking_minutes(km)} min walk ({fmt_distance(km)})'
            f'{" · open " + fmt_days(g["open_days"]) if g["open_days"] else ""}</span></li>'
            for km, g in near[:NEAR_SHOW])
        more = (f"<p class=\"count\">{len(near) - NEAR_SHOW} more within a ten-minute walk "
                "are on the <a href=\"/\">map</a>.</p>" if len(near) > NEAR_SHOW else "")
        sight_blocks.append(
            f"<h3>Near {esc(title)}</h3>\n<p>{esc(blurb)} <strong>{len(near)} galleries</strong> "
            f"are within about ten minutes on foot. The closest:</p>\n"
            f'<ul class="galleries">{items}</ul>{more}')

    season_year = season_holidays(today)[0][0].year
    title = f"NYC art galleries over the holidays ({season_year}): what's open, Thanksgiving to New Year's"
    desc = ("Which New York art galleries are open or closed on Thanksgiving, Christmas and "
            "New Year's, from the hours galleries post on Google, plus free galleries within "
            "a short walk of the Rockefeller Center tree and the holiday markets.")

    body = f"""    <h1>NYC art galleries over the holidays</h1>
    <p class="intro">If you're in New York between Thanksgiving and New Year's, the city's
    art galleries are one of the best free things to do: warm, quiet, never ticketed, and
    often a few blocks from the crowds. The catch is the calendar. Galleries close on the
    holidays, and plenty take a longer break between Christmas and New Year's.</p>
    <p>This page tracks it. We follow {total} walk-in galleries across the five boroughs,
    and we check the holiday hours each one posts on Google. Google only shows holiday hours
    about a week ahead, so each holiday below fills in as it gets close.</p>

    <h2>Holiday by holiday</h2>
{chr(10).join(sections)}
{"<p><strong>Earlier this season:</strong></p><ul>" + "".join(earlier) + "</ul>" if earlier else ""}

    <h2>What to expect</h2>
    <p><strong>Thanksgiving weekend.</strong> Treat Thanksgiving Day as closed. Many
    galleries also take Black Friday off, and some stay closed through the weekend.
    Museums are the better bet on Thursday and Friday.</p>
    <p><strong>December.</strong> The first three weeks are a good time to go. Shows are
    up, openings slow down and the rooms are quiet. Many exhibitions close around the middle
    of the month, and some galleries spend the last weeks of December between shows.</p>
    <p><strong>Christmas to New Year's.</strong> This is when the most galleries are closed.
    Some shut for the whole week. The ones that stay open often run shorter hours. Check
    before you make a special trip.</p>
    <p><strong>January.</strong> The new season starts in the second week of January, with
    a run of openings, usually on Thursday evenings.</p>

    <h2>Which days galleries are open in a normal week</h2>
    <p>From the regular hours of the {len(with_hours)} galleries on our map that list them
    on Google. If your free day is a Sunday or Monday, most galleries will be closed.</p>
    <table class="digest"><tr><th>Day</th><th>Galleries open</th></tr>{week_rows}</table>

    <h2>Galleries near the holiday sights</h2>
    <p>Distances are straight-line walking estimates from each spot.</p>
{chr(10).join(sight_blocks)}

    <div class="callout">
      <p>New to gallery-going? Read <a href="/visiting-nyc-galleries.html">how to visit
      New York galleries</a>: they're free, you don't need to buy anything, and nobody
      will mind if you stay for thirty seconds. To see whole districts, try the
      <a href="/routes/">walking routes</a>, or check <a href="/new-shows/">what opened
      this week</a>.</p>
    </div>"""

    ld = json.dumps({
        "@context": "https://schema.org", "@type": "Article", "headline": title,
        "description": desc, "url": URL, "dateModified": today.isoformat(),
        "author": {"@type": "Organization", "name": "NYC Gallery Tracker"},
        "publisher": {"@type": "Organization", "name": "NYC Gallery Tracker"},
    }, indent=2)
    OUT_PATH.write_text(page_shell(title=f"{title} | NYC Gallery Tracker", description=desc,
                                   url=URL, body=body, ld_json=ld))
    print(f"  Wrote {OUT_PATH} ({len(sections)} upcoming holidays, {len(sight_blocks)} sights)")


if __name__ == "__main__":
    main()
