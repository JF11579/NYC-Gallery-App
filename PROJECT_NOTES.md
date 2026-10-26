# NYC Gallery Tracker — Project Notes

A running log of decisions, findings, and follow-ups that aren't obvious from the
code or the commit history. Newest status first within each section. Update this
file when something changes rather than starting a new one.

**Next check-in: ~2026-10-30** — see [Open follow-ups](#open-follow-ups).

---

## Where things stand (2026-10-23)

The site has one core problem, not two: it doesn't yet give a visitor enough reason
to stay. Google's indexing decisions and visitor behaviour are both measuring that.

- **Google Search:** sitemap accepted, but only 3 of ~33 pages indexed.
- **Visitors:** ~470/month, almost all new, ~12s average engagement, about half from paid ads.
- **Tracking:** until 2026-10-23 only the homepage was tracked and nothing on it
  beyond page loads, so the numbers above understate real engagement. Full tracking
  is now live — the first week of real data is the next thing to read.

---

## Google Search Console / indexing

**Property:** `https://nycgallerytracker.com/` (URL-prefix, verified via Google Analytics).
The old `nyc-gallery-app.netlify.app` property will fade out as Google follows the
301 redirects in `netlify.toml`.

| Date | Sitemap | Indexed | Not indexed | Notes |
|---|---|---|---|---|
| 2026-10-23 | Success, last read Oct 19, 33 discovered | 3 | 30 | All 30 = "Discovered – currently not indexed" |
| 2026-10-12 | Submitted on new domain; "Couldn't fetch" (normal for a new property) | — | — | Moved to nycgallerytracker.com |
| 2026-10-12 (old domain) | Last read Oct 11, 32 discovered | 3 | 36 | 29 discovered-not-indexed, 7 alternate canonical |
| 2026-09-25 (old domain) | Resubmitted — Google hadn't re-read it since Jul 29 | 3 | 23 | Discovered jumped 18 → 31 immediately |

**Read on it:** nothing is technically broken — robots.txt allows everything, no
noindex, pages return 200, sitemap is valid. "Discovered – currently not indexed"
means Google knows the pages exist and is choosing not to crawl them. That is a
site-quality/priority judgement, the same one behind the AdSense "low value content"
rejection.

**What would help:** more original, page-specific writing on the area, route and
new-shows pages; Request Indexing on a few key pages (daily quota); inbound links
from other sites.

---

## Google Analytics (GA4)

**Baseline, 28 days Sep 25 – Oct 22, 2026** (before full tracking):

- 471 active users, 469 new — about 2 returning
- 12s average engagement per user, 39% engagement rate
- Sessions by channel: Cross-network (ads) 244 · Direct 203 · Organic 19 · Paid Search 17 · Referral/social/AI/email 12
- ~100 users from New York; ~97 from Council Bluffs / Ashburn / Boardman / Glenview
  (Google/AWS data-center cities — very likely bots)
- Only 18 users clicked out to a gallery site; 15 scrolled to the bottom
- Email digest drove 1 session in the month

**Caveat on that baseline:** only `index.html` had the GA tag. A visitor who went
from the homepage to any other page vanished from Analytics and could be counted as
a bounce. Visitors landing directly on an inner page were never counted at all.

### Tracking added 2026-10-23 (commit a93b8d7)

- GA4 tag on all pages. Generated pages get it from `GA_HEAD` in `site_common.py`
  (used by `page_shell` and `render_area_pages.py`). `about.html`, `privacy.html` and
  the already-published `new-shows/YYYY-MM-DD.html` pages were tagged by hand —
  new digest pages pick it up automatically.
- Homepage custom events (`track()` in `index.html`):

| Event | Fires when | Params |
|---|---|---|
| `map_move` | first user pan/zoom of the map | — |
| `map_pin_click` | gallery pin clicked | gallery_name, borough, new_show |
| `gallery_card_click` | directory card clicked | gallery_name, borough, new_show |
| `gallery_website_click` | "Visit website" clicked | gallery_name, borough, new_show, source (`map_popup` / `directory_card`) |
| `borough_filter` | borough button or dropdown | borough |
| `scroll_past_map` | visitor scrolls below the map | — |
| `digest_signup` | email form submitted | — |
| `install_click` / `app_installed` | PWA install prompt | — |
| `notify_click` / `notify_enabled` | push-notification opt-in | — |

- GA4 custom dimensions registered (Admin → Custom definitions, event scope):
  **Gallery name** (`gallery_name`), **Borough** (`borough`), **Click source** (`source`).
  These only apply to data from 2026-10-23 on.

---

## Google Ads

- **2026-10-26:** Google emailed a "Destination mismatch" policy notice. Cause: the
  asset group's Final URL and all 6 sitelinks still pointed at
  `nyc-gallery-app.netlify.app`, which 301s to the new domain since 2026-10-12.
  The asset group was "Eligible (Limited)" and impressions had fallen to near zero
  from ~Oct 20. Updated every URL to `https://nycgallerytracker.com/…` (the "About
  the App" sitelink now goes to `about.html`; it had pointed at `privacy.html`).
  All are back under review. **After any future domain change, update the URLs in
  Ads as well.**
- **2026-10-23 (commit 8de553f):** the conversion used to fire on every homepage
  load, so Ads was optimizing for page loads — consistent with the 12-second visits
  and bot traffic. It now fires once per page view on the visitor's first real
  action: `map_pin_click`, `gallery_card_click`, `gallery_website_click`,
  `digest_signup`, `notify_enabled`, or `app_installed`. Same conversion label as
  before; only when it fires changed.
- Expect reported conversions to drop sharply (from ~490/month to dozens) and
  automated bidding to relearn for a week or two. Avoid other campaign changes
  meanwhile.
- In the Ads UI the conversion action is still named "Page view conversion" —
  worth renaming (e.g. "Gallery interaction"). Bidding strategy not yet reviewed.
- Earlier (July 2026): targeting fixed; landing page changed so the map leads and
  signup asks only appear after the visitor scrolls (addressing an ~89% instant bounce).

---

## AdSense

- **2026-06-15:** first application rejected (reason unspecified). Likely cause: the
  gallery directory was rendered entirely by JavaScript, so crawlers saw an empty
  page. Fixed 2026-07-01 by baking static gallery cards into `index.html`
  (`render_gallery_html.py`, runs in the daily build).
- **2026-07-15:** second rejection — "Low value content." A content-depth problem,
  not a code bug.
- **2026-07-16:** added `about.html` and per-borough write-ups on the homepage. Since
  then: walking routes, visitor guide, area pages, and the weekly new-shows archive.
- **Status unknown** — not confirmed whether a re-review was requested after the new
  content shipped. Check AdSense → Sites.
- Monetization ideas parked until approval: paid gallery sponsorships (pinned/starred
  listing, ~$50/month) and featured-artist banner slots.

---

## Open follow-ups

- [ ] **~2026-10-30:** read GA4 Reports → Engagement → Events with a week of real
      data. What do engaged visitors do? Which galleries/boroughs? Map or list?
- [ ] **~2026-10-30:** check Google Ads spend, CPC and conversions after the
      conversion change.
- [ ] **~2026-10-28:** confirm the asset group and 6 sitelinks passed review
      (Assets → status column) and impressions recovered.
- [ ] Rename the Ads conversion action; review the campaign's bidding strategy.
- [ ] Check AdSense status; request re-review if still "Low value content."
- [ ] Re-check Search Console indexed count.
- [ ] Review the homepage as a first-time visitor (phone) — why do people leave in seconds?
- [x] 2026-10-23: homepage Queens note claimed "nearly as many galleries as Brooklyn";
      data showed 5 vs 55 (data correct, no mis-tagged boroughs). Rewrote the note.
