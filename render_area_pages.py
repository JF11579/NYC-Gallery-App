#!/usr/bin/env python3
"""
render_area_pages.py — Generates SEO landing pages for boroughs and neighborhoods.

The homepage is one big interactive map; great for users, but for SEO it's a single
URL. People search "art galleries in Chelsea", "Bushwick galleries", "art galleries
Brooklyn" — long-tail queries a single-page app can't rank for. This script reads
data/galleries.json and bakes a static, crawlable page per AREA:

  • one page per borough (all 5)                          -> /galleries/manhattan.html ...
  • one page per major art neighborhood (>= MIN_GALLERIES) -> /galleries/chelsea.html ...

Each page carries a unique, original write-up (see AREA_CONTENT) plus the gallery list,
schema.org ItemList structured data, and internal links to sibling areas + the map. The
original editorial copy matters for two reasons: it's what ranks in search, and it's what
AdSense requires — the site was rejected 2026-07-28 for "low value content" (thin/aggregated
listings), and substantial original writing is the fix. It also:

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

from site_common import site_footer

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

# Original, hand-written copy for each area: a one-line "lead" (used for the intro and
# meta/OG description) plus "body" paragraphs shown in an "About" section. This is the
# original content that both ranks in search and satisfies AdSense's content bar.
AREA_CONTENT = {
    "Manhattan": {
        "lead": "From the blue-chip powerhouses of Chelsea to the artist-run storefronts of the Lower East Side, Manhattan holds the densest concentration of art galleries anywhere in the United States.",
        "body": [
            "Manhattan's gallery world is really several worlds stacked onto one island. Chelsea, in the West 20s, is the commercial heart, home to mega-galleries like Gagosian, Pace, David Zwirner, and Hauser & Wirth, whose museum-scale exhibitions are free and open to anyone who walks in. A short subway ride south, the Lower East Side and Tribeca host a younger, faster-moving scene of smaller rooms showing emerging and mid-career artists, while the Upper East Side leans toward established modern and postwar work near the museums.",
            "What surprises most people is how many of these galleries hide in plain sight, on upper floors, behind unmarked doors, or tucked between shopfronts you've walked past a hundred times. Almost all of them are free, and you are welcome to browse without buying anything at all. Thursday evenings are traditionally when new shows open, often with a crowd spilling onto the sidewalk.",
            "This page maps every Manhattan gallery we track. Use the interactive map to plot a walking route, or pick a neighborhood below to focus on one district at a time.",
        ],
    },
    "Brooklyn": {
        "lead": "Brooklyn's gallery scene has grown from a handful of Williamsburg lofts into one of the most exciting and experimental art landscapes in the country.",
        "body": [
            "Where Manhattan's galleries can feel polished and commercial, Brooklyn's tend to be scrappier, cheaper to run, and closer to the artists themselves. The energy is concentrated in a few districts: Bushwick, with its dense sprawl of artist-run project spaces; Williamsburg, the original Brooklyn art hub; and DUMBO, where galleries and non-profits cluster under the bridges. Greenpoint, Bed-Stuy, and Gowanus round out a scene that keeps spreading as rents shift.",
            "Because so many Brooklyn spaces are run by working artists and small collectives, the shows here often take more risks than their Manhattan counterparts, and the neighborhoods reward wandering. Weekend afternoons are the easiest time to visit, and events like Bushwick's open-studio weekends throw open dozens of doors at once.",
            "Below is every Brooklyn gallery we track, mapped and grouped by neighborhood so you can plan a route across the borough.",
        ],
    },
    "Queens": {
        "lead": "Queens punches far above its reputation, anchored by the Long Island City art district just one subway stop from Midtown Manhattan.",
        "body": [
            "Long Island City is the center of gravity, home to major institutions like MoMA PS1, one of the oldest and largest contemporary art spaces in the country, and SculptureCenter, along with the outdoor Socrates Sculpture Park and the Noguchi Museum a little further north. Together they make LIC a genuine destination, easily reached across the river yet far less crowded than Chelsea.",
            "Beyond the institutions, Queens has a quieter network of galleries and artist spaces reflecting the most diverse county in the United States. It rarely gets mentioned in the same breath as Manhattan or Brooklyn, which is exactly why it stays a scene hiding in plain sight.",
            "These are the galleries and art spaces we track across Queens. Use the map to find the ones near you.",
        ],
        "sections": [
            {
                "h": "Why Queens is worth the trip",
                "p": [
                    "The case for Queens is mostly about scale and quiet. The institutions here occupy former schools, factories and warehouses rather than purpose-built white boxes, which means the art gets more room and you get more space to look at it. A Saturday afternoon at MoMA PS1 will not feel like the crush of a Chelsea opening or the queue at a Midtown museum, and the work is frequently more experimental precisely because the spaces are not trying to sell it to you.",
                    "It is also the least self-conscious of the five boroughs about being an art destination. Long Island City has spent two decades as a place artists actually work, and the studios, foundries and fabricators that support the rest of the city's art world are still here. You feel that in the programming, which leans toward installation, sculpture and long-form projects that would be impractical in a rented storefront.",
                ],
            },
            {
                "h": "Getting there and planning a visit",
                "p": [
                    "Long Island City is genuinely close. From Midtown it is a single stop under the river, and the 7, E, M and G lines all converge around Court Square within a few minutes' walk of the main spaces. If you are coming from Brooklyn, the G runs straight up without touching Manhattan at all. Coming from Manhattan's east side, the ferry is slower but a considerably better view.",
                    "The practical thing to know is that the Queens spaces keep institutional hours rather than gallery hours, and several close on Tuesdays or Wednesdays rather than the usual Monday. Check before you set out; an unnecessary trip across the river is a bad way to spend an afternoon. Most of the LIC spaces sit within about fifteen minutes' walk of each other, so two or three in one visit is comfortable.",
                    "Socrates Sculpture Park and the Noguchi Museum are a separate cluster further north in Astoria, closer to the Broadway stop on the N and W. They pair naturally with each other and less naturally with Court Square, so treat them as a second, distinct outing rather than trying to force everything into one afternoon.",
                ],
            },
            {
                "h": "What to expect",
                "p": [
                    "Unlike the commercial galleries downtown, several of the Queens spaces are non-profits or museums and do charge admission, though the amounts are modest and some run free or pay-what-you-wish hours. That is the main way visiting Queens differs from gallery-hopping in Chelsea or the Lower East Side, where walking in free and unannounced is the norm.",
                    "The trade-off is worth it. Exhibitions here tend to run longer than the six-week commercial cycle, so there is less urgency about catching something before it closes, and the shows are often more ambitious than anything a dealer could justify hanging.",
                ],
            },
        ],
    },
    "Bronx": {
        "lead": "The Bronx doesn't have the gallery-scene reputation of the other boroughs, but there's a real, active art community here for anyone paying attention.",
        "body": [
            "The anchor is the Bronx Museum of the Arts on the Grand Concourse, which is free to visit and has long championed artists of color and work rooted in the borough's communities. Around it sits a network of non-profit spaces, artist studios, and community arts organizations that rarely make the citywide press but form a genuine, homegrown scene.",
            "The Bronx rewards curiosity more than any other borough on this map: the spaces here are fewer and more spread out, so a visit is as much about the neighborhoods as the art itself. These are the art spaces we currently track across the borough.",
        ],
        "sections": [
            {
                "h": "A different model from downtown",
                "p": [
                    "It is worth being clear about what the Bronx art scene is and is not. There is no dealer district here, no strip of commercial galleries selling work to collectors. What exists instead is a network of institutions and community arts organizations whose reason for being is the borough itself: showing artists who live here, teaching, running studio programs, and giving over wall space to work about the place it is made in.",
                    "That produces a genuinely different experience from a Chelsea afternoon. You are less likely to encounter a famous name and more likely to encounter work you cannot see anywhere else, often by artists early in their careers. If you go looking for a compressed version of the Manhattan gallery circuit you will be disappointed. If you go curious about what a borough of 1.4 million people makes of itself, you will not be.",
                ],
            },
            {
                "h": "The Grand Concourse spine",
                "p": [
                    "Most of what we track sits on or near the Grand Concourse, the wide boulevard laid out in imitation of the Champs-Élysées that runs the length of the west Bronx. The Bronx Museum of the Arts sits on it at 1040, and the Longwood Arts Project further south at 450, which makes the Concourse the natural axis for a visit.",
                    "The boulevard is also one of the great concentrations of Art Deco apartment buildings anywhere in the world, and walking between the two spaces along it is a substantial part of the appeal. Give yourself the walk rather than taking the train between stops; the architecture is the exhibition you did not pay for.",
                    "Further north, the Bronx River Art Center sits near Fordham Road, a busy commercial stretch that is one of the liveliest shopping districts in the city and a considerable change of register from the Concourse.",
                ],
            },
            {
                "h": "Getting there",
                "p": [
                    "The Bronx is easier to reach than most Manhattanites assume. The B and D run directly up the Grand Concourse, and the 4 runs parallel a few blocks east, so the Concourse spaces are a straightforward ride from Midtown or Harlem. The 2 and 5 serve the southern end near 149th Street.",
                    "The main planning constraint is that the spaces are far enough apart that you should pick a cluster rather than attempt the borough in one go. Two stops in an afternoon is realistic and unhurried. Check opening hours carefully: several of these organizations run on programming schedules rather than standard gallery hours, and some are closed for installation between shows.",
                ],
            },
        ],
    },
    "Staten Island": {
        "lead": "Staten Island's art scene is small but real, centered on the Snug Harbor Cultural Center on the borough's north shore.",
        "body": [
            "Snug Harbor, a former sailors' retirement community turned cultural campus, is home to the Newhouse Center for Contemporary Art and set among botanical gardens worth the trip on their own. The Staten Island Museum, near the ferry terminal in St. George, rounds out the borough's main art offerings.",
            "The ride over on the free Staten Island Ferry, with its views of the harbor and the Statue of Liberty, is half the appeal. These are the art spaces we track on the island.",
        ],
        "sections": [
            {
                "h": "Two spaces, and why that is the honest number",
                "p": [
                    "We track two art spaces on Staten Island, and we would rather say so plainly than pad the list. The borough has roughly half a million residents and no commercial gallery district; what it has instead is a cultural campus and a museum, both on the north shore within reach of the ferry, and both genuinely worth a visit on their own terms.",
                    "This makes Staten Island the one borough where the art is not really the reason to go — it is the structure around which a good day out is built. Treated that way, it is one of the better afternoons available in New York for the price of nothing.",
                ],
            },
            {
                "h": "The ferry is the point",
                "p": [
                    "The Staten Island Ferry is free, runs around the clock, and takes about twenty-five minutes each way across New York Harbor. It passes Governors Island, gives you the Statue of Liberty off the starboard side heading south, and delivers one of the best views of the Lower Manhattan skyline from the back rail on the way home. No ticket, no reservation, no queue for most of the day.",
                    "Take the right-hand side of the boat going out for the Statue, and the stern coming back for the skyline. Boats run at least every thirty minutes and more often at peak times, so a missed departure costs very little.",
                ],
            },
            {
                "h": "Making a day of it",
                "p": [
                    "The Staten Island Museum sits in St. George within a few minutes' walk of the ferry terminal, which makes it the natural first stop — you can see it and be back on a boat inside two hours if that is all you want.",
                    "Snug Harbor is the more substantial destination and requires a short bus ride west along Richmond Terrace from the terminal. The campus is a collection of nineteenth-century Greek Revival buildings set in eighty-odd acres of grounds, including botanical gardens and a Chinese Scholar's Garden. The Newhouse Center for Contemporary Art occupies part of it. Even if the exhibition on show does not grab you, the grounds justify the trip.",
                    "Budget around half a day door to door from Lower Manhattan, and check both spaces' opening hours before you go — this is the one borough where turning up to a locked door means a fifty-minute round trip for nothing. Both tend to keep afternoon hours and close at least one weekday.",
                ],
            },
        ],
    },
    "Chelsea": {
        "lead": "Chelsea is the center of gravity for the New York gallery world, with several hundred galleries packed into the West 20s between Tenth and Eleventh Avenues.",
        "body": [
            "If you visit one gallery district in New York, make it Chelsea. Within a few walkable blocks you'll find the flagship spaces of the industry's biggest names, Gagosian, Pace, David Zwirner, Hauser & Wirth, Gladstone, and Matthew Marks among them, alongside dozens of mid-size and specialist galleries. Shows rotate roughly every six weeks and are free to walk into; many feel closer to museum exhibitions than sales rooms.",
            "The neighborhood grew up alongside the High Line, the elevated park that threads through it, and the two pair naturally: an afternoon can easily combine a stroll above with a dozen gallery visits below. Openings cluster on Thursday evenings, when the streets fill and galleries stay open late. Don't be put off by the polished interiors, no one expects you to buy, and browsing is the whole point.",
            "Below is every Chelsea gallery we track. Tap any one to place it on the map and plan your route.",
        ],
    },
    "SoHo": {
        "lead": "SoHo was the epicenter of the New York art world in the 1970s and '80s, and after decades as a shopping district, galleries have been steadily returning to its cast-iron streets.",
        "body": [
            "This is where the modern gallery scene was effectively invented: dealers like Leo Castelli and a generation of artists who took over cheap industrial lofts turned SoHo into the center of contemporary art before Chelsea existed. The galleries largely left in the 1990s as luxury retail moved in, but the cast-iron architecture and the history remained.",
            "In recent years galleries have come back, sharing the neighborhood with flagship stores and design showrooms, which makes SoHo one of the more browsable districts in the city: art, architecture, and window-shopping on the same walk. These are the SoHo galleries we currently track.",
        ],
    },
    "Tribeca": {
        "lead": "Once quiet after dark, Tribeca has become one of the fastest-growing gallery districts in New York.",
        "body": [
            "Over the past several years, galleries priced out of Chelsea or looking for a change have migrated to Tribeca's ground floors and lofts, and the neighborhood now hosts a serious concentration of contemporary spaces. Because they're spread among restaurants, residences, and cobblestoned side streets rather than lined up on a single block, discovering them feels more like exploring than gallery-hopping.",
            "The mix ranges from established names to younger galleries showing emerging artists, and the relative quiet compared with Chelsea is part of the appeal. These are the Tribeca galleries we track.",
        ],
    },
    "Lower East Side": {
        "lead": "The Lower East Side is where much of New York's younger and more experimental gallery energy lives.",
        "body": [
            "Historically a dense immigrant neighborhood, the LES became an art destination as small galleries opened in former storefronts along Orchard, Henry, Broome, and Canal Streets. The spaces here are typically compact and independent, and they tend to show emerging and mid-career artists before the bigger uptown galleries catch on, which makes the neighborhood one of the best places in the city to see what's next.",
            "Everything is tightly packed and walkable, so you can see a dozen shows in an afternoon and still have time for the neighborhood's cafes and bars. These are the Lower East Side galleries we track.",
        ],
    },
    "East Village": {
        "lead": "The East Village gave the 1980s one of its defining art movements, and a handful of galleries keep that scrappy, independent spirit alive today.",
        "body": [
            "In the early 1980s, storefront galleries across the East Village launched careers and helped define a raw, street-connected downtown scene. Most of those spaces are long gone, but the neighborhood retains a do-it-yourself character, and the galleries here now tend to be small, independent, and unafraid of the offbeat.",
            "Visiting the East Village is as much about the neighborhood as the art, with its bookshops, record stores, and community gardens between stops. These are the galleries we track in the area.",
        ],
        "sections": [
            {
                "h": "What happened to the East Village scene",
                "p": [
                    "For about five years in the early 1980s the East Village was the most talked-about art neighborhood in the world. Dozens of galleries opened in former storefronts on East 10th Street, Avenue B and the surrounding blocks, run on almost no money by people in their twenties, and the scene that came out of them shaped a decade of American art. By the end of the decade nearly all of them had closed.",
                    "The usual explanation is rent, and rent is most of it, but the scene also collapsed under its own success as the artists it discovered were absorbed by bigger galleries in SoHo and later Chelsea. What remains is not a revival so much as a residue: a handful of independent spaces, several long-running non-profits and foundations, and a neighborhood that still thinks of itself as a place where things start.",
                ],
            },
            {
                "h": "What is here now",
                "p": [
                    "The spaces we track in the East Village skew toward foundations and cultural institutions rather than commercial dealers — organizations with a specific remit, showing work from particular communities or holding a single artist's estate. That gives the area an unusual character: less browsing, more depth, and shows that reward knowing a little about why the space exists.",
                    "The blocks around Great Jones Street, Bowery and Lafayette are the densest stretch, sitting on the border where the East Village runs into NoHo. A few of the spaces we list sit east of Avenue A or south toward Houston, which is a walk rather than a stroll but a pleasant one.",
                ],
            },
            {
                "h": "Planning a visit",
                "p": [
                    "The 6 to Astor Place, the F to Second Avenue and the L to First Avenue all put you within a few blocks of the main cluster. The neighborhood is small and flat, and you can cross the whole of it on foot in twenty minutes.",
                    "Because there are only a handful of spaces here, the East Village works best combined with something else rather than as a destination of its own. The Lower East Side begins a few blocks south and has far more galleries per block; a sensible afternoon starts in the East Village, works south across Houston, and finishes among the Orchard and Henry Street spaces.",
                    "Leave time for the neighborhood itself. The community gardens on the eastern avenues, the secondhand bookshops and the record stores are a substantial part of why people come here, and several of them are more interesting than an average commercial gallery.",
                ],
            },
        ],
    },
    "Upper East Side": {
        "lead": "The Upper East Side pairs world-class museums with a cluster of established galleries specializing in modern, postwar, and blue-chip work.",
        "body": [
            "This is the most genteel of the city's gallery districts, set among the townhouses and grand apartment buildings near Museum Mile. With the Met, the Guggenheim, the Frick, and the Neue Galerie all close by, the neighborhood's galleries lean toward the classical and the historical, secondary-market masterworks and established names rather than emerging experiments.",
            "It makes for a rewarding day that mixes museums and galleries in a single walk, especially along Madison Avenue and the side streets off it. These are the Upper East Side galleries we track.",
        ],
    },
    "Bushwick": {
        "lead": "Bushwick is Brooklyn's most concentrated artist-run gallery district, a sprawl of project spaces, studios, and non-profit galleries in former industrial buildings.",
        "body": [
            "If Chelsea is the polished, commercial face of the New York art world, Bushwick is its opposite: raw, affordable, and driven by working artists rather than dealers. Galleries here often occupy warehouse floors and share buildings with the studios of the artists they show, and the scene skews young, experimental, and community-minded.",
            "The best time to visit is during the neighborhood's open-studio weekends, when dozens of spaces throw open their doors at once, but there's plenty to see year-round. Come ready to wander; the industrial blocks aren't obviously arty until you find the right door. These are the Bushwick galleries we track.",
        ],
        "sections": [
            {
                "h": "How Bushwick actually works",
                "p": [
                    "Bushwick is the least legible gallery district in New York, and that is not an accident of geography so much as a consequence of how the spaces are funded. Most are run by artists, collectives or small non-profits operating on thin margins in rented industrial floors. They do not have street frontage, signage budgets or staff to sit at a desk all week, so many open only Friday through Sunday, some only by appointment, and a few only when there is a show up.",
                    "The practical consequence is that turning up unannounced on a Tuesday afternoon will get you a row of closed roller shutters and a bad impression of a genuinely good scene. Check the individual websites before you go — this is the one district on the map where that step is not optional.",
                    "The upside of the same economics is that the programming takes risks nothing in Chelsea can afford to take. Shows are put on because someone wanted to see them exist, not because they will sell, and the ratio of ambitious-to-safe is higher here than anywhere else in the city.",
                ],
            },
            {
                "h": "Finding your way around",
                "p": [
                    "The cluster sits mostly in the blocks around Jefferson Street and Morgan Avenue on the L, spilling east toward Knickerbocker and the M line, and north across the Queens border into Ridgewood, which functions as part of the same scene regardless of what the borough boundary says.",
                    "These are working industrial blocks: warehouses, auto shops, distribution depots, and long stretches with nothing obviously artistic about them. The galleries are frequently on upper floors behind unmarked metal doors, with a buzzer and a paper sign as the only indication. Trust the address rather than the frontage, and be prepared to press a bell and wait.",
                    "It is also worth knowing that Bushwick has one of the densest concentrations of large-scale street art in the city, particularly around the Troutman Street corridor. Even on a day when half the galleries are shut, the walk between them is worth doing.",
                ],
            },
            {
                "h": "When to go",
                "p": [
                    "Weekend afternoons are the reliable window — Saturday most of all, when the largest number of spaces are open at the same time and openings often run into the evening. A Saturday from about one o'clock gives you the best odds of finding doors unlocked.",
                    "The exception, and the best single time to visit, is the neighborhood's open-studio weekend, held annually, when dozens of galleries and hundreds of artist studios open at once. It turns a scattered district into a walkable festival for two days and is the easiest possible introduction to the area.",
                    "Come with layers and comfortable shoes. The distances between spaces are longer than they look on a map, the buildings are frequently unheated, and there is very little shelter on the industrial stretches.",
                ],
            },
        ],
    },
    "Williamsburg": {
        "lead": "Williamsburg helped launch Brooklyn's rise as an art destination, and it still holds a strong mix of galleries and creative spaces near the waterfront.",
        "body": [
            "In the late 1990s and early 2000s, Williamsburg was the frontier of the Brooklyn art scene, drawing artists across the river with cheap space and a DIY ethos. The neighborhood has changed enormously since, but a real gallery presence remains, now sharing the streets with music venues, design studios, and some of the best skyline views in the city.",
            "It pairs easily with a walk along the East River waterfront and is a short subway hop or ferry ride from Manhattan. These are the Williamsburg galleries we track.",
        ],
    },
    "DUMBO": {
        "lead": "DUMBO packs a dense cluster of galleries and arts organizations into a few cobblestoned blocks beneath the Manhattan and Brooklyn Bridges.",
        "body": [
            "Down Under the Manhattan Bridge Overpass, DUMBO is one of the most photogenic corners of New York, and one of the most walkable art districts: galleries, non-profit art organizations, and creative studios sit within a few short blocks, framed by the bridges and the river. The neighborhood has long positioned itself as an arts hub, and the concentration of spaces makes it easy to see a lot in a little time.",
            "Combine a gallery walk with the waterfront park and the bridge views and it's one of the more scenic art outings in the city. These are the DUMBO galleries we track.",
        ],
    },
    "Greenpoint": {
        "lead": "Greenpoint's gallery scene is younger and quieter than its neighbors', an emerging art district at the northern tip of Brooklyn.",
        "body": [
            "Long known as the city's Polish neighborhood, Greenpoint has gradually drawn artists and small galleries north from Williamsburg in search of space, and a low-key but growing scene has taken root among its warehouses and waterfront. The galleries here are still relatively few and far between, which is part of the appeal for anyone who likes discovering a district before it's on everyone's map.",
            "It rewards a relaxed wander, with strong food and coffee to break up the walk. These are the Greenpoint galleries we track.",
        ],
        "sections": [
            {
                "h": "An art district still forming",
                "p": [
                    "Greenpoint is at an earlier stage than the neighborhoods around it. Williamsburg to the south went through its gallery boom two decades ago; Bushwick to the east has a scene dense enough to sustain an annual festival. Greenpoint has neither, and what it has instead is a handful of serious spaces, some of them very serious indeed, spread across a neighborhood that has not organized itself around art.",
                    "That has a specific consequence for visitors: there is no gallery walk here. You are going for one or two particular spaces rather than to browse a district, and the right approach is to pick a destination and treat the neighborhood as the surrounding pleasure rather than the point.",
                    "It also means the spaces that are here tend to be the ones with a reason to be — research institutes, foundations, artist-run rooms with a specific programme — rather than dealers chasing footfall. The average quality of what is on the walls is high.",
                ],
            },
            {
                "h": "The neighborhood around the art",
                "p": [
                    "Greenpoint was for a century the centre of Polish New York, and much of that is still visible along Manhattan Avenue and Nassau Avenue: bakeries, butchers, delis and social clubs that predate every gallery in the borough. The area has changed a great deal, but not as completely as Williamsburg, and the older neighborhood is still the dominant one on most blocks.",
                    "The waterfront on the western edge has some of the best views of the Manhattan skyline anywhere in the city, particularly around sunset, and the streets in between are low-rise, quiet and pleasant to walk. Franklin Street is the spine for coffee and food.",
                ],
            },
            {
                "h": "Getting there",
                "p": [
                    "The G is the only subway that serves Greenpoint directly, stopping at Greenpoint Avenue and Nassau Avenue. The G is the one line in the system that never enters Manhattan, which is why the neighborhood can feel further away than it is — from most of Manhattan the quickest route is the L to Bedford Avenue and a fifteen-minute walk north, or the ferry to the India Street landing.",
                    "The ferry is the most pleasant option by a wide margin and lands you at the western edge near the waterfront. From Midtown or the Upper East Side it is often no slower than the subway once you count the transfers.",
                    "Check hours before travelling. With only a handful of spaces in the neighborhood, one closed door removes a large fraction of the reason you came.",
                ],
            },
        ],
    },
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


def lead_for(area, borough):
    if area in AREA_CONTENT:
        return AREA_CONTENT[area]["lead"]
    where = area if area in BOROUGHS else f"{area}, {borough}"
    return (
        f"A live map and directory of the art galleries we track in {where}. "
        "Green markers flag galleries that have posted something new in the past week."
    )


def sections_for(area):
    """Optional deeper sub-sections (heading + paragraphs) for an area.

    Pages carrying only a couple of paragraphs read as thin: every one of these
    area pages was sitting in Search Console under "Discovered - currently not
    indexed", which is Google declining to index them on quality grounds. Areas
    with FEW galleries need more original writing than the busy ones, not less,
    because there is less listing content to carry the page.
    """
    return AREA_CONTENT.get(area, {}).get("sections", [])


def body_for(area, borough):
    if area in AREA_CONTENT:
        return AREA_CONTENT[area]["body"]
    where = area if area in BOROUGHS else f"{area}, {borough}"
    return [
        f"This page collects the art galleries we track in {where}, mapped so you can "
        "see which ones are near you and plan a route between them. Almost every gallery "
        "in New York is free to enter, and you're welcome to browse without buying anything.",
        "Use the interactive map to explore, and check back as the list grows.",
    ]


def render_page(area, borough, galleries, all_areas, cutoff):
    slug = slugify(area)
    is_borough = area in BOROUGHS
    where = area if is_borough else f"{area}, {borough}"
    scene = f"art galleries in {where}" if is_borough else f"the {area} gallery scene"
    title = f"Art Galleries in {where} — Map & Directory | NYC Gallery Tracker"
    desc = (
        f"Find {len(galleries)} art galleries in {where}. "
        "An interactive, weekly-updated map and guide to NYC art galleries."
    )
    url = f"{BASE_URL}/galleries/{slug}.html"

    def is_new(g):
        lu = g["properties"].get("last_updated") or ""
        return bool(lu) and lu >= cutoff

    galleries = sorted(galleries, key=lambda g: (0 if is_new(g) else 1,
                                                 g["properties"]["name"].lower()))

    cards = []
    items = []
    for i, g in enumerate(galleries, 1):
        p = g["properties"]
        badge = '<span class="new">New show</span> ' if is_new(g) else ""
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

    body_html = "\n      ".join(f"<p>{esc(para)}</p>" for para in body_for(area, borough))

    section_blocks = []
    for sec in sections_for(area):
        paras = "\n      ".join(f"<p>{esc(p)}</p>" for p in sec["p"])
        section_blocks.append(f"<h3>{esc(sec['h'])}</h3>\n      {paras}")
    sections_html = "\n      ".join(section_blocks)

    nav_groups = []
    for b in BOROUGHS:
        sibs = [a for a in all_areas if all_areas[a]["borough"] == b and a != area]
        if not sibs:
            continue
        links = " · ".join(
            f'<a href="/galleries/{slugify(a)}.html">{esc(a)}</a>' for a in sorted(sibs)
        )
        nav_groups.append(f"<p><strong>{esc(b)}:</strong> {links}</p>")
    nav_html = "\n      ".join(nav_groups)

    ld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": f"Art Galleries in {where}",
        "url": url,
        "description": desc,
        "mainEntity": {"@type": "ItemList", "numberOfItems": len(galleries),
                       "itemListElement": items},
    }

    new_note = ' · green = new show this week' if any(is_new(g) for g in galleries) else ''

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
           line-height:1.6; color:#1a1a1a; margin:0; background:#fafafa; }}
    header {{ background:var(--blue); color:#fff; padding:14px 20px; }}
    header a {{ color:#fff; text-decoration:none; font-weight:600; }}
    main {{ max-width:820px; margin:0 auto; padding:24px 20px 60px; }}
    h1 {{ font-size:1.7rem; margin:.2em 0; }}
    h2 {{ font-size:1.25rem; margin:1.6em 0 .4em; }}
    .intro {{ font-size:1.1rem; color:#333; }}
    .count {{ color:#555; font-size:.95rem; margin:.5em 0 1.2em; }}
    section.about p {{ color:#333; }}
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
    <p class="intro">{esc(lead_for(area, borough))}</p>
    <p class="count">{len(galleries)} galleries{new_note}</p>
    <ul class="galleries">
      {chr(10).join('      ' + c for c in cards)}
    </ul>
    <a class="back" href="/">← See all of these on the interactive map</a>
    <section class="about">
      <h2>About {esc(scene)}</h2>
      {body_html}
      {sections_html}
    </section>
    <nav class="areas">
      <p><strong>Browse other areas:</strong></p>
      {nav_html}
    </nav>
{site_footer()}
  </main>
</body>
</html>
"""


def build_sitemap(area_slugs):
    """Build sitemap.xml.

    Area pages come from the slugs we just generated; guides, walking routes and
    weekly digests are discovered from disk so this stays correct no matter which
    order the generators are run in (and so a digest published last week is never
    silently dropped from the sitemap by a later area-page rebuild).
    """
    today = date.today().isoformat()
    urls = [
        (f"{BASE_URL}/", "daily", "1.0"),
        (f"{BASE_URL}/about.html", "monthly", "0.5"),
        (f"{BASE_URL}/privacy.html", "yearly", "0.3"),
    ]
    for slug in area_slugs:
        urls.append((f"{BASE_URL}/galleries/{slug}.html", "weekly", "0.7"))

    # Evergreen guide.
    if Path("visiting-nyc-galleries.html").exists():
        urls.append((f"{BASE_URL}/visiting-nyc-galleries.html", "monthly", "0.9"))

    # Walking routes.
    routes_dir = Path("routes")
    if (routes_dir / "index.html").exists():
        urls.append((f"{BASE_URL}/routes/", "monthly", "0.8"))
    for path in sorted(routes_dir.glob("*.html")):
        if path.stem != "index":
            urls.append((f"{BASE_URL}/routes/{path.name}", "monthly", "0.7"))

    # Weekly digest archive: the index changes often, the dated pages never again.
    digest_dir = Path("new-shows")
    if (digest_dir / "index.html").exists():
        urls.append((f"{BASE_URL}/new-shows/", "weekly", "0.8"))
    for path in sorted(digest_dir.glob("*.html"), reverse=True):
        if path.stem != "index":
            urls.append((f"{BASE_URL}/new-shows/{path.name}", "yearly", "0.5"))

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
    # Also surface the guides, routes and weekly archive from the homepage. These
    # pages are useless if nothing links to them: Search Console had every area page
    # sitting under "Discovered - currently not indexed", and orphaned pages fare
    # worse still. The homepage is the most-crawled URL on the site, so the new
    # content gets linked from it directly.
    guide_links = []
    if Path("visiting-nyc-galleries.html").exists():
        guide_links.append(
            '<p class="area-row"><strong>New to galleries?</strong> '
            '<a href="/visiting-nyc-galleries.html">How to visit New York galleries</a> '
            '— they\'re free, and you don\'t need an appointment.</p>')
    if Path("routes/index.html").exists():
        guide_links.append(
            '<p class="area-row"><strong>Walking routes:</strong> '
            '<a href="/routes/">Gallery walks by district</a>, ordered so you cover the '
            'ground once instead of doubling back.</p>')
    if Path("new-shows/index.html").exists():
        guide_links.append(
            '<p class="area-row"><strong>What changed this week:</strong> '
            '<a href="/new-shows/">The weekly archive</a> of galleries that posted '
            'something new.</p>')
    guides_block = ""
    if guide_links:
        guides_block = ('<h2>Guides &amp; walking routes</h2>\n'
                        + "\n".join(guide_links) + "\n")

    block = ('\n<section class="browse-areas">\n'
             '<h2>Browse galleries by neighborhood</h2>\n'
             + "\n".join(groups) + "\n"
             + guides_block + "</section>\n")
    html = AREAS_RE.sub(lambda m: m.group(1) + block + m.group(3), html)
    INDEX_PATH.write_text(html)
    print("  Injected neighborhood nav into index.html")


def main():
    geojson = json.loads(DATA_PATH.read_text())
    features = geojson["features"]
    cutoff = (date.today() - timedelta(days=NEW_DAYS)).isoformat()

    by_borough = {b: [] for b in BOROUGHS}
    by_hood = {}
    for g in features:
        b = g["properties"].get("borough", "")
        if b in by_borough:
            by_borough[b].append(g)
        hood = assign_neighborhood(g["geometry"]["coordinates"])
        if hood:
            by_hood.setdefault(hood, []).append(g)

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

    sitemap = build_sitemap(slugs)
    SITEMAP_PATH.write_text(sitemap)
    print(f"  Wrote sitemap.xml with {sitemap.count('<loc>')} URLs")

    inject_index_nav(all_areas)
    print(f"Done. Generated {len(slugs)} area pages.")


if __name__ == "__main__":
    main()
