# NBA how-to-watch guide

Generates the HoopsMatic guide at **https://hoopsmatic.com/how-to-watch**: a hub
page, one page per team, a page for tonight's games, and one page each for
the UK, Spain, France, Germany and Italy. Python plus Jinja2, no
front-end framework.

`main` holds the generator. The built site is force-pushed as a single fresh
commit to `gh-pages`, whose root the Cloudflare Worker serves at
`/how-to-watch`. Pages served straight from GitHub Pages will look unstyled,
because every internal link and asset URL starts with `/how-to-watch/`. That is
expected.

## The files you edit

| What you want to change | File |
| --- | --- |
| Subscription prices, billing notes, which channels a service carries, League Pass blackout rules | `data/services.json` |
| Local TV per team, in-market notes | `data/local_tv.json` |
| Affiliate links | `data/services.json`, the `affiliate_url` on each service |
| Page titles, descriptions, headings, FAQ wording | `data/copy.json` |
| Team names and slugs | `data/teams.json` |
| Whether search engines may index the site | `data/copy.json`, the top-level `noindex` flag |
| Country pages: TV partners, prices, League Pass prices, player overrides, the games in Europe | `data/countries.json` |
| Country page titles, descriptions and wording | `data/copy.json`, the `country` block |

`noindex` ships as `true`. While it is on, every page carries
`<meta name="robots" content="noindex,follow">`, `sitemap.xml` is still written
but lists no URLs, and `robots.txt` does not point at it. Canonicals do not
change either way. Set it to `false` when the Worker is live and you want the
guide in search results.

A service only shows a price once it has `monthly_price_usd`, a `source_url`, a
`last_verified` date and `verified: true`. Anything else renders as "Price not
confirmed" and stays out of the cheapest-combination maths. A price of `0` is a
real price and renders as "Free"; `null` is a missing one. A service with
`carries_verified: false` is still listed with its price and a line saying its
coverage is unconfirmed, but it counts for no games and stays out of the
cheapest-combination maths. The "Prices checked" line above the price list
comes from `_meta.all_prices_checked`. League Pass (`nba_league_pass`) gets its
coverage from `rules.league_pass_blackouts`; its `carries` list holds only
channels bundled with it (NBA TV), which share its in-market blackout. The
build fails if that service is missing.

Local TV follows `_meta.confidence_rules` and `_meta.coverage_rules` in
`data/local_tv.json`. Local options only cover a team's games with no national
broadcaster, and only in the in-market view. `high` and `moderate` teams count
(`moderate` adds a check-before-you-buy line under any combination that uses a
local option); `low` and `unknown` never count. Over the air counts as free
coverage only at `ota.status` `all`. A streaming option with a price covers
every local game at that price, a null price is listed but never priced, and
`shared_service` takes its price from `shared_services`. An option with
`requires_service` costs its own price plus that service's, and brings that
service's games with it. `exclude_from_us_maths` shows the team's notes instead
of an in-market combination. Every team page has a "Watching in" section built
from the file.

`affiliate_url` is empty everywhere. The affiliate disclosure sentence only
appears on a page once at least one service has a non-empty `affiliate_url`.

### Country pages

`data/countries.json` drives `/how-to-watch/<slug>` for each country in it. Each
page is prerendered with every time in the country's own zone, worked out at
build time, so the page script leaves it alone. The daily build writes these
pages; the 30-minute refresh does not.

- Prices render in the country's currency. `price_verified: false` adds "Check
  the current price before you buy."; a `null` price reads "Price not
  confirmed". A `moderate` country gets one check-before-you-buy line and a
  `low` one shows every price as not confirmed.
- League Pass prices sit in each country's `league_pass` block
  (`monthly_price`, `season_price`). While both are `null` the page says the
  prices are not published yet; fill one in and the next build shows it.
- "Players from" lists active players whose career-map `nationality` has a
  part (split on `/`) matching the country's `nationality_aliases`, so
  "American / Italian" counts for Italy. `player_overrides` adds players by
  name when the career map has no nationality for them. An override that
  matches nobody on a current roster is named in the build log. A country
  with no players gets no block.
- "Games at a watchable hour" is the next 14 days of games tipping off from
  12:00 to 23:59 local time.
- The Paris and Manchester games show until their date has passed.

## Running it

```bash
pip install -r requirements.txt
python -m watchguide --out site build      # fetch the feeds and build everything
python -m watchguide --out site refresh    # availability only, plus the pages it touches
python -m watchguide --out site games-today # exit 0 when there are games today
python -m watchguide verify                # hit the live feeds and report
python -m pytest
```

`--today YYYY-MM-DD` overrides the Eastern date, which is handy for testing.

## Where the data comes from

**Schedule and broadcasters.** `https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json`.
Verified on 2026-09-24: `leagueSchedule.seasonYear` is `2026-27`, with 174 game
dates from 2026-10-03 to 2027-04-11 and 1206 regular-season games. The host
rejects non-browser TLS fingerprints, so the request goes through `curl_cffi`
with a Chrome profile and an `nba.com` Referer. Eastern tip-off times are worked
out from `gameDateTimeUTC` with `zoneinfo`, which keeps daylight saving right.

National TV sits under `broadcasters.nationalBroadcasters`. There is no
`nationalTvBroadcasters` key in this feed, and reading for one is why the first
version of the generator reported zero national games. `nationalBroadcasters`
can carry radio entries, and `nationalRadioBroadcasters` lists SiriusXM on all
1206 games, so anything whose `broadcasterMedia` is radio is skipped: radio is
not a way to watch. The codes to put in a service's `carries` list are listed
in `data/services.json` under `_meta.carries_note`, and the codes deliberately
left unmapped (NBCSN, Telemundo) under `_meta.unmapped_broadcaster_codes`.

Every build writes `data/broadcast-coverage.json` and prints a summary line, so
the count of games with national TV is visible on each run. That is how you see
the day the league fills in the rest of the season.

**Availability.** `https://aderoa.github.io/Injuries/injuries.json`, the keyless
public feed that hoopsmatic.com/depth-charts reads. Rows are
`{player, status, injury, date, prevStatus}`, a change log rather than a
snapshot, so the current status of a player is their latest row. The feed
carries no team, so players are matched to a team through the NBA's public
player index at `https://cdn.nba.com/static/json/staticData/playerIndex.json`.
Only the five published statuses are kept: Out, Doubtful, Questionable,
Probable, Available. Anything else, such as "Left Game", is left out rather than
reinterpreted.

Every run saves the raw response to `data/injuries-raw-latest.json` and commits
it. That file is both the fallback when the feed breaks and the baseline the
next run compares against. If a fetch fails, or the feed comes back more than
50% shorter than the last good copy, the run keeps the last good copy, marks the
pages out of date and exits 3. The workflow publishes those pages and then goes
red, so a broken feed is loud but the site does not go blank. When the feed has
no rows for the current season at all, which is the case right now, pages say
"No injury report yet." rather than showing an empty list.

**Tonight's ranking.** Three inputs, every number in
`data/star_power_weights.json`:

- *Rosters*: the nba-career-map repo's `nba_players_careers_READY.json` on
  raw.githubusercontent.com. That file has no `current_team`, so the team is the
  `career_history` stint running to "present". The full build keeps a slim copy
  at `data/star-rosters.json` in the published tree; the 30-minute refresh reuses
  it, and a failed or implausible fetch keeps the last good one.
- *Star power*: `data/recent_awards.json`, All-Star selections (injury
  replacements included) and All-NBA First, Second and Third Teams for the last
  three seasons, from Wikipedia's All-Star Game and All-NBA Team pages. Each
  player's score is the sum over seasons of season weight x points, awards in a
  season stacking; only players not listed Out or Doubtful count. Refresh it with
  the `fetch-recent-awards` workflow (run by hand; Wikipedia is not reachable from
  every sandbox) after moving the season window in the weights file.
- *Stakes*: each team's current record from the schedule feed. A game gets a
  stakes score once both teams have played `min_games`; before that the ranking
  is star power only. Every full build's summary, and `python -m watchguide
  verify`, has a "team records probe" line showing whether the feed's records are
  filled in yet.

National TV is a badge, not points. The heading reads "Most star power tonight"
until stakes are on for most of the day's games, then "Tonight's best games".

The hub opens with a strip of stat cards (days to opening night, or tonight's
game count; national TV games; teams free over the air; countries covered), all
computed on each build. Each team card carries a one-line local summary from
`data/local_tv.json` under the team pages' confidence rules. NBCSN and Telemundo
are explained in a footnote under the partners box rather than listed as
partners (`hub.national_footnote_codes` in `data/copy.json`).

The hub lists every game of the day in tip-off order, earliest first, with a
"Top pick" badge on the three highest-ranked, one compact row each: tip
time (ET, shown in the reader's zone by the page script), both teams linked to
their pages, channel badges and the ranking line, with players listed Out in a
collapsed detail under the row. The 30-minute refresh rewrites the hub with the
tonight page, so an injury that changes a line or the order shows on both. On a
day with no games, the hub and the tonight page show the next day with games
instead, headed "Next games: <weekday, date>", ranked without availability
(the league's report only covers today's games).

**Logos, flags, headshots and fonts.** Nothing on a page loads from another
domain. Team logos (`assets/logos/<tricode>.svg`) and the player silhouette
come from jsierrahoopshype/nba-headshots; the country flags
(`assets/flags/`, flag-icons, MIT) and the self-hosted DM Sans and JetBrains
Mono fonts (`assets/fonts/`, SIL OFL) from jsierrahoopshype/nba-born-died,
whose design language the pages follow. All are in the repo and published
under `/how-to-watch/assets/` with content-hashed names (the fonts keep plain
names because the stylesheet names them). Player headshots for the hub's game
cards are fetched at build time: `players/metadata/players_all.json` gives each
player's file name, the 160px WebP comes from `players/headshots/face2-160/`,
and it is saved to `assets/faces/` in the published tree, which the restore
step brings back, so each face is downloaded once. A player with no headshot,
or a failed download, gets the silhouette. `HEADSHOTS_BASE` points the fetch at
another copy of that repo.

**Prices, local TV and blackout rules.** Hand-edited data files. Nothing is
guessed. See the table above.

No API keys are used anywhere and none belong in this repo.

### If a host ever refuses the runner

Set the repository variable `NBA_PROXY_BASE` to the origin of a plain
pass-through proxy (a Cloudflare Worker, for example) and requests to
`cdn.nba.com` are sent there with the same path. `INJURY_FEED_URL` points the
availability feed somewhere else. Both are optional and neither is a secret.

## What the build guarantees

- Every canonical, `og:url`, JSON-LD URL and sitemap entry starts with
  `https://hoopsmatic.com/how-to-watch`. A test fails if `github.io` turns up
  anywhere in the output.
- Every reader-facing fact is in the prerendered HTML. JavaScript only switches
  the market toggle, converts tip-off times to the reader's zone and refreshes
  availability badges.
- Both market states are in the HTML of every team page, so a crawler reads both.
- A failed fetch keeps the last published data and makes the job go red rather
  than publishing an empty page.
- Every build and refresh writes `data/expected-pages.txt`: the hub, tonight,
  one page per team in `data/teams.json` and one per country in
  `data/countries.json`. `scripts/publish.sh` refuses to publish unless the
  tree's `index.html` files are exactly those paths, and lists any missing or
  unexpected ones. Adding a team or a country needs no change to a script or
  a test. `PUBLISH_CHECK_ONLY=1 ./scripts/publish.sh site` runs the check alone.
- `data/how-to-watch-links.html` is written on every build: a plain block of
  absolute links to the hub, the tonight page, all 30 teams and every country
  page, for pasting into
  the Worker so the guide has an internal crawl path.

## Automation

- `build-watch-guide-daily.yml` runs at 10:00 UTC and rebuilds everything.
- `refresh-watch-guide-injuries.yml` runs every 30 minutes from 16:00 to 04:30
  UTC. It reads the published schedule first and stops within seconds when there
  are no games on the Eastern date.
- Both use `permissions: contents: write` and share the `watch-guide-publish`
  concurrency group, so they never push over each other.
- Both commit `data/injuries-raw-latest.json` back to the working branch when it
  changes, and both fail at the end of the run if the availability feed could not
  be trusted.

## Adding a page type later

Write a module in `watchguide/pages/` exposing `build(ctx, env) -> list[Page]`
and add it to `BUILDERS` in `watchguide/pages/__init__.py`. It gets the same
`SiteContext` as everything else: teams, games, services, local TV, copy and
availability. Player pages, sit-risk labels and calendar feeds fit this shape.
