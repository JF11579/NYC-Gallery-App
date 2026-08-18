#!/usr/bin/env python3
"""
render_guides.py — Builds the site's evergreen guide pages.

Two things live here:

  1. /visiting-nyc-galleries.html
     A first-timer's guide to actually walking into a New York gallery. The single
     most useful paragraph on this site was buried at the bottom of the homepage —
     the one explaining that commercial galleries are free and you do not need a
     ticket, an appointment or any intention to buy. That answers a real question
     that real people are too embarrassed to ask, and it deserved to be a page.

  2. /routes/<neighborhood>.html  (+ /routes/ index)
     Walking routes through each dense gallery district, ordered so you actually
     walk a sensible loop instead of criss-crossing the same three blocks. These
     are computed from the coordinates in data/galleries.json — a nearest-neighbour
     path improved with 2-opt — so they are derived from our own data rather than
     copied from anywhere.

Both are the kind of content that a directory of names and addresses cannot
produce: they answer a question rather than listing a fact.

Usage:
    python3 render_guides.py
"""

import json
from datetime import date
from pathlib import Path

from site_common import (BASE_URL, ROUTE_MIN_GALLERIES, esc, fmt_distance,
                         haversine_km, page_shell, slugify, walking_minutes)

DATA_PATH = Path("data/galleries.json")
ROUTES_DIR = Path("routes")
GUIDE_PATH = Path("visiting-nyc-galleries.html")

MAX_STOPS = 12          # a 40-stop "walk" is a list, not a route

# Neighborhood centroids, mirroring render_area_pages.py.
NEIGHBORHOODS = {
    "Chelsea": (-74.0014, 40.7465),
    "SoHo": (-74.0016, 40.7233),
    "Tribeca": (-74.0089, 40.7163),
    "Lower East Side": (-73.9857, 40.7150),
    "East Village": (-73.9843, 40.7265),
    "Upper East Side": (-73.9626, 40.7736),
    "Bushwick": (-73.9213, 40.6942),
    "Williamsburg": (-73.9571, 40.7141),
    "Greenpoint": (-73.9510, 40.7304),
    "DUMBO": (-73.9887, 40.7033),
}
RADIUS_KM = 1.4

# Accurate at the district level: which lines put you at the start of each walk.
TRANSIT = {
    "Chelsea": "C or E to 23rd St, 1 to 23rd St, or L/A/C/E to 14th St–8th Ave",
    "SoHo": "6 to Spring St, N/R/W to Prince St, or B/D/F/M to Broadway–Lafayette",
    "Tribeca": "1 to Franklin St, A/C/E to Canal St, or 1/2/3 to Chambers St",
    "Lower East Side": "F to Delancey St, J/M/Z to Essex St, or B/D to Grand St",
    "East Village": "6 to Astor Pl, L to 1st Ave, or F to 2nd Ave",
    "Upper East Side": "4/5/6 to 77th or 86th St, or Q to 72nd or 86th St",
    "Bushwick": "L to Jefferson St or Morgan Ave, or M to Central Ave",
    "Williamsburg": "L to Bedford Ave, G to Metropolitan Ave, or J/M/Z to Marcy Ave",
    "Greenpoint": "G to Greenpoint Ave or Nassau Ave, or the ferry to India St",
    "DUMBO": "F to York St, A/C to High St, or 2/3 to Clark St",
}

# One paragraph of real character per route. Generic filler would defeat the point.
ROUTE_NOTES = {
    "Chelsea": [
        "This is the densest concentration of major galleries anywhere in the world, and the walk is almost embarrassingly easy: the district is a grid of long blocks between Tenth and Eleventh Avenues in the West 20s, and most of the buildings hold several galleries stacked on different floors. Look for building directories in the lobbies — you will often find four or five spaces at a single address.",
        "Budget more time than the walking distance suggests. The exhibitions here are frequently museum-scale, and the temptation to spend twenty minutes in a single room is real. Thursday evenings are when new shows open and the streets fill up; if you prefer quiet, come on a weekday afternoon.",
    ],
    "SoHo": [
        "SoHo's galleries are scattered among the cast-iron buildings and flagship stores rather than concentrated on one strip, so this route covers more ground than the Chelsea walk and rewards looking upward. Many spaces are on second and third floors behind an unmarked street door and a buzzer.",
        "The architecture is a genuine part of the visit. The cast-iron district is one of the largest surviving concentrations of the style anywhere, and the walk between stops is as much of the experience as the art.",
    ],
    "Tribeca": [
        "Tribeca's gallery scene grew fast over the past several years as spaces moved south from Chelsea, and it is still spread thinly enough that the walk between stops takes you past restaurants, lofts and cobblestoned side streets rather than a solid wall of galleries.",
        "This is the quietest of the major Manhattan districts on a weekend, which is precisely its appeal. You are unlikely to share a room with more than a handful of people.",
    ],
    "Lower East Side": [
        "The Lower East Side has the highest gallery-per-block density in the city outside Chelsea, and the spaces are small enough that you can see a show properly in five minutes. That makes this the single best route for anyone who wants to see a lot of art in one afternoon.",
        "The galleries here tend to show younger and less established artists than the uptown rooms, which means a higher variance in what you find and a better chance of seeing something before anyone else does.",
    ],
    "East Village": [
        "A short walk with only a handful of stops, best treated as the first half of an afternoon that continues south into the Lower East Side. The spaces here lean toward foundations and cultural institutions rather than commercial dealers.",
        "The neighborhood itself is the other half of the appeal — community gardens, secondhand bookshops and record stores fill the gaps between stops.",
    ],
    "Upper East Side": [
        "The most genteel of the routes, threading through townhouses and side streets off Madison Avenue. The galleries here deal largely in modern, postwar and secondary-market work, which means you will see more historically significant art and fewer surprises than downtown.",
        "The route sits within a few blocks of Museum Mile, so it combines naturally with the Met, the Guggenheim, the Frick or the Neue Galerie. Doing both in a day makes for a long but coherent walk.",
    ],
    "Bushwick": [
        "Check opening hours before you attempt this one. Many Bushwick spaces open only Friday to Sunday, and some by appointment, so a midweek attempt at this route will mostly show you closed shutters. Saturday afternoon is the reliable window.",
        "The walk runs through working industrial blocks, and the galleries are frequently on upper floors behind unmarked doors. Trust the address rather than the frontage. The street art between stops, especially around the Troutman Street corridor, is worth the trip on its own.",
    ],
    "Williamsburg": [
        "Williamsburg's spaces are spread between the waterfront and the blocks inland around Bedford, so this route covers a fair distance and passes through several quite different stretches of neighborhood along the way.",
        "The East River waterfront at the western end has some of the best skyline views in the city, and works well as either the start or the finish depending on the light.",
    ],
    "Greenpoint": [
        "A short route with few stops — Greenpoint is an art district still forming rather than an established one. Go for a specific space rather than to browse, and treat the neighborhood as the surrounding pleasure.",
        "Manhattan Avenue and Nassau Avenue still carry much of the Polish neighborhood that predates every gallery in the borough, and the waterfront at the western edge has an exceptional view back toward Midtown.",
    ],
    "DUMBO": [
        "The most compact route on the site: DUMBO packs its galleries and arts organizations into a few cobblestoned blocks under the bridges, so the entire walk takes less time than the subway ride to reach it.",
        "It is also the most photogenic. The route passes between the Manhattan and Brooklyn Bridge anchorages and along the waterfront park, and pairs easily with an hour spent doing nothing in particular by the river.",
    ],
}

# Per-route practical detail. Specific to each district on purpose — a shared
# "plan ahead and wear good shoes" block repeated on ten pages is exactly the
# near-duplicate boilerplate that got these pages passed over for indexing.
ROUTE_PRACTICAL = {
    "Chelsea": {
        "best": "Weekday afternoons for quiet, Thursday evenings for openings. Avoid Sunday and Monday, when nearly everything is shut.",
        "pair": "The High Line runs directly through the district and is the obvious way to break the walk in half. The Whitney sits at its southern end.",
        "note": "Several addresses on this route hold multiple galleries on different floors. Check the lobby directory before you leave a building — you can easily double your count without walking another block.",
    },
    "SoHo": {
        "best": "Saturday is busiest with shoppers; a weekday morning gives you the cast-iron streets nearly to yourself.",
        "pair": "The route ends within a few blocks of both Tribeca and the Lower East Side, either of which makes a natural second half.",
        "note": "Many SoHo galleries are on upper floors with only a buzzer at street level. If the address looks like a shop, look up.",
    },
    "Tribeca": {
        "best": "Weekend afternoons are unusually calm here compared with Chelsea or the Lower East Side.",
        "pair": "SoHo begins a few blocks north and the Financial District a few blocks south; the Hudson River Greenway is a short walk west.",
        "note": "Distances between Tribeca stops are longer than they look because the street grid breaks down below Canal. Allow more time than the mileage suggests.",
    },
    "Lower East Side": {
        "best": "Saturday afternoon, when the largest number of spaces are reliably open at once.",
        "pair": "The East Village is immediately north across Houston Street, and the New Museum sits on the Bowery at the district's western edge.",
        "note": "The spaces here are small, so each stop takes less time than it would in Chelsea. Twelve galleries in an afternoon is comfortable rather than ambitious.",
    },
    "East Village": {
        "best": "Weekday afternoons. Several of the spaces here keep institutional rather than gallery hours, so check individually.",
        "pair": "This is a short route by design — continue south across Houston into the Lower East Side, where the density picks up sharply.",
        "note": "The stops are spread across the neighborhood rather than clustered, so the walking between them is a larger share of the afternoon than usual.",
    },
    "Upper East Side": {
        "best": "Tuesday to Friday. Weekend hours are shorter here than downtown, and some spaces close Saturdays in summer.",
        "pair": "Museum Mile is a few blocks west. The Met, the Guggenheim, the Frick and the Neue Galerie are all within reach of this route.",
        "note": "Several galleries here occupy townhouses and upper floors and operate partly by appointment. A call ahead is more useful in this district than any other.",
    },
    "Bushwick": {
        "best": "Saturday afternoon, without much competition. Many spaces open only Friday to Sunday and some only by appointment.",
        "pair": "Ridgewood, across the Queens border, is functionally part of the same scene and adds several more spaces.",
        "note": "This is the longest route on the site at over two miles. The stops are genuinely spread out, so treat it as a walk through the neighborhood rather than a gallery crawl.",
    },
    "Williamsburg": {
        "best": "Weekend afternoons, though the neighborhood is busy then. Friday is a good compromise.",
        "pair": "The East River waterfront parks at the western end, and Greenpoint immediately to the north.",
        "note": "The route spans the waterfront and the inland blocks around Bedford, which are quite different in character. Starting at the water and walking inland works well in the afternoon.",
    },
    "DUMBO": {
        "best": "Any afternoon. This is the most compact route on the site and the least dependent on timing.",
        "pair": "Brooklyn Bridge Park runs along the waterfront, and walking back to Manhattan over either bridge is the natural finish.",
        "note": "The whole route covers about half a mile. You will spend longer getting here than walking it, so leave room for the park and the views.",
    },
    "Greenpoint": {
        "best": "Weekend afternoons, and check ahead — with few spaces, one closure removes much of the point.",
        "pair": "Williamsburg is a twenty-minute walk south, and the waterfront has the best Midtown skyline view in Brooklyn.",
        "note": "Greenpoint is an art district still forming. Go for a specific space rather than to browse.",
    },
}


# ------------------------------------------------------------------ route math

def assign_neighborhood(coords):
    best, best_d = None, RADIUS_KM
    for hood, centroid in NEIGHBORHOODS.items():
        d = haversine_km(coords, centroid)
        if d < best_d:
            best, best_d = hood, d
    return best


def route_length(points):
    return sum(haversine_km(points[i], points[i + 1]) for i in range(len(points) - 1))


def order_walk(galleries):
    """Order stops into a sensible walking path.

    Greedy nearest-neighbour from the south-westernmost stop, then 2-opt to undo
    the crossings greedy always leaves behind. For a dozen points this is instant
    and gets within a few percent of optimal, which is far beyond the precision
    anyone walking between galleries actually needs.
    """
    if len(galleries) <= 2:
        return galleries

    pts = [g["geometry"]["coordinates"] for g in galleries]
    start = min(range(len(pts)), key=lambda i: (pts[i][1], pts[i][0]))

    unvisited = set(range(len(pts)))
    order = [start]
    unvisited.remove(start)
    while unvisited:
        last = pts[order[-1]]
        nxt = min(unvisited, key=lambda i: haversine_km(last, pts[i]))
        order.append(nxt)
        unvisited.remove(nxt)

    # 2-opt: repeatedly reverse a segment if doing so shortens the path.
    improved = True
    while improved:
        improved = False
        for i in range(1, len(order) - 1):
            for j in range(i + 1, len(order)):
                a, b = order[i - 1], order[i]
                c = order[j]
                d = order[j + 1] if j + 1 < len(order) else None
                before = haversine_km(pts[a], pts[b])
                after = haversine_km(pts[a], pts[c])
                if d is not None:
                    before += haversine_km(pts[c], pts[d])
                    after += haversine_km(pts[b], pts[d])
                if after < before - 1e-9:
                    order[i:j + 1] = reversed(order[i:j + 1])
                    improved = True
    return [galleries[i] for i in order]


def pick_core(galleries, centroid, limit=MAX_STOPS):
    """The `limit` galleries closest to the district centroid — its walkable core."""
    ranked = sorted(galleries, key=lambda g: haversine_km(g["geometry"]["coordinates"], centroid))
    return ranked[:limit]


# ------------------------------------------------------------------- rendering

def render_route_page(hood, ordered, total_count):
    slug = slugify(hood)
    url = f"{BASE_URL}/routes/{slug}.html"
    pts = [g["geometry"]["coordinates"] for g in ordered]
    dist = route_length(pts)
    mins = walking_minutes(dist)
    stops = len(ordered)

    title = f"A walking route through {hood}'s art galleries"
    desc = (f"A {stops}-stop walking route through the art galleries of {hood}, "
            f"ordered so you walk {fmt_distance(dist)} instead of doubling back.")

    items = []
    for i, g in enumerate(ordered):
        p = g["properties"]
        leg = ""
        if i + 1 < len(ordered):
            d = haversine_km(pts[i], pts[i + 1])
            leg = (f'<span class="leg">↓ {fmt_distance(d)} to the next stop '
                   f"— about {walking_minutes(d)} min on foot</span>")
        link = (f' — <a href="{esc(p["url"])}" target="_blank" rel="noopener">website ↗</a>'
                if p.get("url") else "")
        addr = f'<span class="meta">{esc(p["address"])}</span>' if p.get("address") else ""
        items.append(f'        <li><strong>{esc(p["name"])}</strong>{link}{addr}{leg}</li>')
    route_html = "\n".join(items)

    notes = "\n      ".join(f"<p>{esc(n)}</p>" for n in ROUTE_NOTES.get(hood, []))
    transit = TRANSIT.get(hood, "")
    transit_html = (f'<p><strong>Getting to the start:</strong> {esc(transit)}.</p>'
                    if transit else "")

    prac = ROUTE_PRACTICAL.get(hood)
    practical_html = ""
    if prac:
        practical_html = f"""<h2>Practical notes for this walk</h2>
      <p><strong>Best time to go.</strong> {esc(prac['best'])}</p>
      <p><strong>Worth knowing.</strong> {esc(prac['note'])}</p>
      <p><strong>Combine it with.</strong> {esc(prac['pair'])}</p>"""

    coverage = ""
    if total_count > len(ordered):
        coverage = (
            f"<p>{hood} has {total_count} galleries on our map. This route takes the "
            f"{len(ordered)} that sit closest together — the walkable core of the district — "
            f"because a {total_count}-stop walk is a list, not a route. "
            f'The <a href="/galleries/{slug}.html">full {esc(hood)} directory</a> has the rest.</p>'
        )

    ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "HowTo",
        "name": title,
        "description": desc,
        "url": url,
        "totalTime": f"PT{mins}M",
        "step": [
            {"@type": "HowToStep", "position": i + 1, "name": g["properties"]["name"],
             "text": f'Visit {g["properties"]["name"]}'
                     + (f' at {g["properties"]["address"]}' if g["properties"].get("address") else "")}
            for i, g in enumerate(ordered)
        ],
    }, indent=2)

    body = f"""    <p style="font-size:.9rem;color:#666;margin-bottom:0">
      <a href="/routes/">← All walking routes</a></p>
    <h1>{esc(title)}</h1>
    <p class="intro">{esc(desc)}</p>
    <ul class="stats">
      <li><strong>{stops}</strong><span>galleries</span></li>
      <li><strong>{fmt_distance(dist)}</strong><span>total walking</span></li>
      <li><strong>{mins} min</strong><span>walking time, not counting stops</span></li>
    </ul>
      {notes}
    {transit_html}
    {coverage}
    {practical_html}
    <h2>The route</h2>
    <ol class="route">
{route_html}
    </ol>
    <div class="callout">
      <p><strong>How this route was built.</strong> We ordered these stops by their
      actual coordinates, using a nearest-neighbour path improved with a 2-opt pass, so
      the sequence is close to the shortest walk that visits every stop once. The walking
      times assume a steady city pace of about 4.5 km/h including traffic lights, and
      count only the walking — not the time you will spend inside.</p>
      <p>Galleries close, move and change their hours. Check before you set out, and
      treat this as a suggested order rather than a schedule.</p>
    </div>
    <p><a class="back" href="/">← See all of these on the interactive map</a></p>"""

    return page_shell(title=f"{title} | NYC Gallery Tracker", description=desc,
                      url=url, body=body, ld_json=ld)


def render_routes_index(routes):
    """routes: list of (hood, stops, dist_km, total_count)."""
    url = f"{BASE_URL}/routes/"
    title = "Gallery walking routes in New York"
    desc = ("Walking routes through New York's gallery districts, ordered by map "
            "coordinates so you cover the ground once instead of doubling back.")

    rows = "\n".join(
        f'        <tr><td><a href="/routes/{slugify(h)}.html">{esc(h)}</a></td>'
        f"<td>{s}</td><td>{fmt_distance(d)}</td><td>{walking_minutes(d)} min</td></tr>"
        for h, s, d, _ in routes
    )

    shortest = min(routes, key=lambda r: r[2]) if routes else None
    longest = max(routes, key=lambda r: r[2]) if routes else None

    body = f"""    <h1>Gallery walking routes</h1>
    <p class="intro">New York's galleries cluster into a handful of dense districts, and
    the difference between a good afternoon and an exhausting one is usually the order you
    walk them in.</p>
    <p>Each of these routes takes the galleries we track in a district and orders them by
    their actual coordinates, so you walk a sensible path instead of crossing the same
    block four times. Distances and times are calculated from those coordinates; the times
    assume a normal city walking pace and count only the walking, not the looking.</p>
    <table class="digest">
      <thead><tr><th>District</th><th>Stops</th><th>Distance</th><th>Walking time</th></tr></thead>
      <tbody>
{rows}
      </tbody>
    </table>

    <h2>Which route should you pick?</h2>
    <p>If this is your first time, take Chelsea. It has the highest concentration of major
    galleries anywhere in the world, the walk between them is short, and several of the
    addresses hold four or five galleries stacked on different floors — so the stop count
    understates how much you will actually see. The exhibitions are frequently
    museum-scale, and all of it is free.</p>
    <p>If large white rooms and blue-chip names are not the appeal, take the Lower East
    Side instead. The spaces are small, independent and show younger artists, so you move
    through them faster and see work that has not been filtered by a large gallery's
    commercial judgement yet.</p>
    <p>For the shortest possible outing, {esc(shortest[0]) if shortest else 'DUMBO'} covers
    {esc(fmt_distance(shortest[2])) if shortest else 'half a mile'} and takes about
    {walking_minutes(shortest[2]) if shortest else 12} minutes of walking end to end. For
    the most demanding, {esc(longest[0]) if longest else 'Bushwick'} runs
    {esc(fmt_distance(longest[2])) if longest else 'over two miles'} — that one is a walk
    through a neighborhood as much as a gallery route, and worth checking opening hours
    before you commit to it.</p>

    <h2>How to use these</h2>
    <p>Nobody finishes a gallery route. Twelve stops is a full afternoon if you actually
    look at things, and stopping after six because you found a show you wanted to sit with
    is a better outcome than completing the list. Treat the order as the useful part and
    the length as optional.</p>
    <p>Two constraints apply almost everywhere. Most commercial galleries are closed
    Sunday and Monday, which catches out a lot of weekend visitors. And August is the
    quietest month of the year, with reduced hours, group shows and outright closures —
    the season restarts in September.</p>
    <p>Each route page lists the subway lines that put you at the first stop, the walking
    distance between each pair of galleries, and district-specific notes on when to go and
    what to combine it with.</p>

    <div class="callout">
      <p><strong>New to this?</strong> Commercial galleries in New York are free, and you
      do not need a ticket, an appointment, or any intention to buy anything. If that is
      reassuring to hear, read
      <a href="/visiting-nyc-galleries.html">how to visit New York galleries</a> first —
      it covers what to expect when you walk in, what the unwritten rules are, and what to
      do when you have no idea what you are looking at.</p>
    </div>
    <p><a class="back" href="/">← Back to the interactive map</a></p>"""

    ld = json.dumps({
        "@context": "https://schema.org", "@type": "CollectionPage",
        "name": title, "url": url, "description": desc,
    }, indent=2)
    return page_shell(title=f"{title} | NYC Gallery Tracker", description=desc,
                      url=url, body=body, ld_json=ld)


def render_guide():
    url = f"{BASE_URL}/visiting-nyc-galleries.html"
    title = "How to visit New York art galleries (when you've never done it before)"
    desc = ("Commercial art galleries in New York are free and open to anyone. A plain "
            "guide to walking in, what to expect, when to go, and what nobody tells you.")

    body = """    <h1>How to visit New York art galleries</h1>
    <p class="intro">Almost every commercial art gallery in New York is free. You do not
    need a ticket, an appointment, a reservation, or any intention of buying anything. You
    can walk in off the street, look at the art for as long or as short a time as you like,
    and walk out again without speaking to anyone.</p>

    <p>That sentence is the single most useful thing on this website, and it surprises a
    remarkable number of people. Galleries look like private businesses — often quiet ones,
    with an unsmiling person at a desk and no prices on the wall — and the natural
    assumption is that they are not for you unless you are buying. They are. Walking in and
    looking is the entire point, and it is how the overwhelming majority of people in any
    gallery on any given day are using it.</p>

    <h2>Galleries and museums are different things</h2>
    <p>A museum owns a collection, charges admission, and shows work it intends to keep.
    A commercial gallery represents living artists, shows work that is for sale, and makes
    its money when something sells. Because the gallery's income comes from sales rather
    than admissions, there is no reason to charge you at the door — and every reason to
    want as many people through it as possible.</p>
    <p>The practical upshot is that a Saturday spent in Chelsea can put you in front of
    more significant contemporary art than a museum visit, for nothing, with no queue. The
    exhibitions in the largest galleries are frequently museum-scale, with catalogues and
    press coverage to match.</p>
    <p>Some spaces on this map are not commercial galleries — museums, non-profits and
    foundations, particularly in Queens, the Bronx and Staten Island. Those may charge
    admission. Everything in the main Manhattan and Brooklyn gallery districts almost
    certainly will not.</p>

    <h2>What actually happens when you walk in</h2>
    <p>Usually nothing, and that is the correct outcome. There is normally a desk near the
    entrance with someone behind it working. They may glance up. They will not usually
    greet you, follow you, or ask what you are looking for. This is not rudeness — the
    convention is that visitors are left alone unless they signal otherwise, and being
    ignored is the gallery treating you like a regular.</p>
    <p>There is often a printed sheet near the door with the artist's name, the titles of
    the works, and sometimes a short essay about the show. Take one. It is free, and it is
    frequently the difference between a confusing room and an interesting one.</p>
    <p>Prices are usually not on the wall. If you want to know, you can ask for the price
    list and you will be handed one without comment. Asking commits you to nothing.</p>

    <h2>The unwritten rules, such as they are</h2>
    <ul class="galleries">
      <li><strong>Do not touch anything.</strong> The obvious one, and the only rule
      nobody will forgive you for breaking. Stand further back from sculpture than feels
      necessary.</li>
      <li><strong>Photography is usually fine.</strong> Most galleries allow it for
      personal use. If there is a sign saying otherwise, or you are unsure, ask. Turn the
      flash off regardless.</li>
      <li><strong>You can stay for thirty seconds.</strong> Walking into a room, deciding
      it is not for you, and leaving immediately is completely normal behaviour and nobody
      will think anything of it.</li>
      <li><strong>You can talk, quietly.</strong> Galleries are not libraries. Normal
      conversation is fine.</li>
      <li><strong>Bags and coats.</strong> Larger galleries may ask you to check a big
      bag. Smaller ones will not have anywhere to put it.</li>
      <li><strong>Children and dogs.</strong> Children are generally welcome if
      supervised. Dogs vary enormously; ask rather than assume.</li>
    </ul>

    <h2>When to go</h2>
    <p>Most commercial galleries open Tuesday to Saturday, roughly ten or eleven in the
    morning until six in the evening. <strong>Sunday and Monday are the two days most
    galleries are closed</strong>, which catches out a lot of weekend visitors — if you
    have one day free and it is Sunday, plan around museums instead.</p>
    <p>Thursday evening is traditionally when new exhibitions open. Openings are free and
    usually unticketed, the gallery stays open late, there is often a drink, and the crowd
    spills onto the pavement. They are sociable and busy and a poor way to actually look at
    art, but an excellent way to feel the scene. If you want to see the work properly, go
    back on a weekday afternoon when the room is empty.</p>
    <p>Two seasonal warnings. <strong>August is the quietest month</strong> — many
    galleries run reduced summer hours, group shows, or close entirely for part of the
    month. And the season restarts in September, which is when the most ambitious shows of
    the year tend to open.</p>

    <h2>How to plan a first visit</h2>
    <p>Pick one district and walk it. Do not try to cross the city; the galleries cluster
    tightly, and the whole appeal is being able to see a dozen shows without getting on a
    train between them.</p>
    <p>For a first time, Chelsea is the obvious answer: the highest concentration of major
    galleries anywhere in the world, laid out on a handful of long blocks in the West 20s,
    with several galleries stacked inside single buildings. Check the lobby directory when
    you enter a building — you will often find four or five spaces on different floors.</p>
    <p>If you would rather see smaller, younger, less intimidating rooms, the Lower East
    Side is the better choice: the spaces are compact, the work is more experimental, and
    the density per block is nearly as high.</p>
    <p>Two hours is a good first outing. Six or eight galleries in that time is a
    comfortable pace, and you will know quickly whether you want to keep going.</p>
    <p>We have <a href="/routes/">walking routes for each district</a> with the stops put
    in a sensible order, and a <a href="/">live map of every gallery we track</a> across
    all five boroughs.</p>

    <h2>What to do when you do not understand the work</h2>
    <p>Nobody understands all of it, including the people who work there. Contemporary art
    is a field with a great deal of context behind it, and a lot of what is on the walls
    assumes you have some of that context. You are allowed not to.</p>
    <p>The most useful question is not "what does this mean" but "would I want to look at
    this again". Move through the room quickly, notice which pieces make you slow down, and
    then go back to those. Reading the printed sheet after you have looked, rather than
    before, tends to produce a more honest reaction.</p>
    <p>And if a whole show does nothing for you, leave. There is another gallery about
    forty seconds' walk away.</p>"""

    ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": desc,
        "url": url,
        "dateModified": date.today().isoformat(),
        "author": {"@type": "Organization", "name": "NYC Gallery Tracker"},
        "publisher": {"@type": "Organization", "name": "NYC Gallery Tracker"},
    }, indent=2)

    return page_shell(title=f"{title} | NYC Gallery Tracker", description=desc,
                      url=url, body=body, ld_json=ld)


def main():
    geojson = json.loads(DATA_PATH.read_text())
    features = geojson["features"]

    by_hood = {}
    for g in features:
        hood = assign_neighborhood(g["geometry"]["coordinates"])
        if hood:
            by_hood.setdefault(hood, []).append(g)

    ROUTES_DIR.mkdir(exist_ok=True)
    routes = []
    for hood, gs in sorted(by_hood.items()):
        if len(gs) < ROUTE_MIN_GALLERIES:
            print(f"  skipping {hood}: only {len(gs)} galleries")
            continue
        core = pick_core(gs, NEIGHBORHOODS[hood])
        ordered = order_walk(core)
        dist = route_length([g["geometry"]["coordinates"] for g in ordered])
        (ROUTES_DIR / f"{slugify(hood)}.html").write_text(
            render_route_page(hood, ordered, len(gs)))
        routes.append((hood, len(ordered), dist, len(gs)))
        print(f"  {hood:18s} {len(ordered):2d} stops  {fmt_distance(dist):>7}  "
              f"{walking_minutes(dist):3d} min -> routes/{slugify(hood)}.html")

    (ROUTES_DIR / "index.html").write_text(render_routes_index(routes))
    print(f"  Wrote routes/index.html ({len(routes)} routes)")

    GUIDE_PATH.write_text(render_guide())
    print(f"  Wrote {GUIDE_PATH}")


if __name__ == "__main__":
    main()
