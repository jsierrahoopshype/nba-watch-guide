# NBA how-to-watch guide

Generates the HoopsMatic guide at **https://hoopsmatic.com/how-to-watch**: a hub
page, one page per team, a page for tonight's games, one page per pair of
teams that meets this season, and one page each for the UK, Spain, France,
Germany and Italy. Python plus Jinja2, no
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
| Short names for long local channel names on channel chips | `data/local_tv.json`, each team's `short_names` |
| Live TV channel lineups (per package, per channel, with sources and check date; also what each live TV service counts for) | `data/services.json`, each live TV service's `lineup` |
| Team colors (logo rings, card edges) | `data/team_colors.json` |
| Affiliate links | `data/services.json`, the `affiliate_url` on each service |
| Page titles, descriptions, headings, FAQ wording | `data/copy.json` |
| Team names and slugs | `data/teams.json` |
| Whether search engines may index the site | `data/copy.json`, the top-level `noindex` flag |
| Country pages: TV partners, prices, League Pass prices, player overrides, the games in Europe | `data/countries.json` |
| Country page titles, descriptions and wording | `data/copy.json`, the `country` block |

`noindex` ships as `false`: the section has launched and every page is open to
search engines. Set it to `true` to hide the section again. While it is on, every page carries
`<meta name="robots" content="noindex,follow">`, `sitemap.xml` is still written
but lists no URLs, and `robots.txt` does not point at it. Each sitemap
`<lastmod>` is the date the page's content last changed, not the build date:
`data/sitemap_lastmod.json` in the published tree keeps a content hash and a
date per URL, and a date moves only when the hash does. The hash leaves out
anything marked `data-volatile` in the templates (the "Updated" stamp, the
out-of-date notice, the availability lists and badges, the injury-driven
ranking on the hub and tonight page) and the content hashes in asset names.
The file is kept up to date while `noindex` is on, so the dates are right the
day the sitemap starts listing pages. Canonicals do not
change either way.

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

The hub goes straight from its title and intro to the day's games. Each team
card carries a one-line local summary from
`data/local_tv.json` under the team pages' confidence rules. NBCSN and Telemundo
are explained in a footnote under the partners box rather than listed as
partners (`hub.national_footnote_codes` in `data/copy.json`).

**Layout rule for every game view** (pair pages, the tonight page, the team
pages' next game, hub game cards): where to watch comes first and nothing may push it down. Under the
matchup head (both logos, both names linking to the team pages, a date chip
with "Tonight", "Tomorrow" or "In 21 days") the order is
(1) where to watch: channel chips with the cheapest way to get each channel
from `data/services.json` ("ESPN Unlimited · $31.99/mo", "NBC · free over the
air"), the out-of-market and in-market answer for both fan bases, collapsed to
one "Everyone in the US" line when all four match. Each answer lists the
standalone options first, as alternatives joined with "or" ("NBA League Pass
(includes NBA TV)" on NBA TV games, "NBA TV through cable" when the
NBA TV channel is the only standalone option), then the live TV services
grouped by service ("or on
live TV with YouTube TV, Hulu + Live TV, Sling, Fubo or DirecTV"), naming a
specific plan only when the plans of one service differ for that game (Fubo
Elite on NBA TV games); `family` in `data/services.json` groups the plans.
An answer that names a live TV service only through a ZIP-dependent local ABC
or NBC ends "Local ABC and NBC availability varies by ZIP code.", and one
check-before-you-buy line follows the answers when a live TV service is named
on a moderate lineup entry (see below). Then "Why ...?" only when a
fan base is actually blocked (a League Pass blackout, or a team's local TV not
carrying a national game in its own market), worded for the case;
(2) tip time, the reader's own time big and ET small beside it, one format
everywhere ("9:00 pm EDT"); (3) players to watch, the two players the ranking
line names with headshot and team; (4) who's out, as chips; (5) "Also worth
knowing", last. The full-size version is one
partial, `templates/partials/game_block.html`; no CSS may reorder its parts,
and `tests/test_pairs.py` checks the order in the HTML and in a 375px-wide
browser (that test needs the `playwright` package and skips without it).
Players to watch never sits inside who's out
(`tests/test_game_block_redesign.py`). The date chip's countdown is
`data-volatile` and the page script recounts it from the reader's clock.

**Live TV lineups.** Each live TV service in `data/services.json` (kind
`live_tv`) has a `lineup` with one entry per package (Sling Orange and Sling
Blue apart) and, in each, one entry per channel in
`_meta.lineup_channels`: ESPN, ESPN2, ABC, NBC, NBA TV and every US regional
network in `data/local_tv.json`. `status` is `carried`, `not_carried`,
`zip_dependent` (sources say it depends on the ZIP code or market; recorded,
never guessed) or `unchecked`. `confidence` is `high` when the entry comes
from the service's own lineup page, `moderate` when at least two sources on
different sites, each published in 2026 (or the service's own page), say the
same about that channel in that plan; `sources` lists each URL with its
publication date and `checked` is the day they were read. One source, older
sources or disagreeing sources leave it `unchecked`, with a `note` saying why.
`_meta.lineup_method` records how the last check was done.
`tests/test_live_tv_lineups.py` enforces every rule. For live TV services the lineup is also the coverage: a service covers a
national game when one of the game's channels is `carried` at high or moderate
confidence in one of its packages (Sling's Orange and Blue together make the
one Orange + Blue service), and local ABC and NBC marked `zip_dependent` count
for national ABC and NBC games. Live TV entries have no service-level `carries`
or `carries_verified`; `model.apply_lineup` derives them. Regional networks,
`unchecked` and `not_carried` never count. The per-service counts, the
cheapest combinations, "What am I missing?" and the in-market and
out-of-market answers all follow. A count or combination that leans on a
moderate entry gets the check-before-you-buy line, and one that reaches a game
only through a ZIP-dependent local ABC or NBC adds "Local ABC and NBC
availability varies by ZIP code." (`tests/test_live_tv_coverage.py`).

Team colors come from `data/team_colors.json` and only draw the logo rings
and the two-tone strip on a card's top edge, never text; a color under 3:1
against the white card (the Spurs' silver) is darkened for that
(`watchguide/colors.py`). A local channel with an entry in its team's
`short_names` shows the short name on chips, with the full name in the
`title` attribute; titles, descriptions and JSON-LD keep the full name.

The hub lists every game of the day in tip-off order, earliest first, with a
"Top pick" badge on the three highest-ranked, one compact card each: both
teams linked to their pages, then the same where-to-watch part as the game
block (the fan-base answers in a collapsed detail unless they collapse to one
line), then the tip time (ET, shown in the reader's zone by the page script),
then players to watch with the ranking line, with players
listed Out in a collapsed detail, then any "Also worth knowing" lines. The
card itself links to the game on its pair page. The tonight page is one list
of full game cards in ranking order, each linking its pair page; no page shows
the numeric score. The 30-minute refresh rewrites the hub with the
tonight page, so an injury that changes a line or the order shows on both. On a
day with no games, the hub and the tonight page show the next day with games
instead, headed "Next games: <weekday, date>", ranked without availability
(the league's report only covers today's games).

**Team-vs-team pages.** `/how-to-watch/<slug-a>-vs-<slug-b>` for every pair
of teams in the schedule, the two slugs from `data/teams.json` in alphabetical
order (`new-york-knicks-vs-philadelphia-76ers`). The reversed order has no
page and nothing links to it, since the Worker cannot redirect it; every link
goes through `watchguide/pairs.py`. Titles name the teams by short name, also
alphabetically ("76ers vs. Knicks"), trying each of `pair.titles` in
`data/copy.json` until one fits 60 characters. Each page shows the next
meeting in full (the game block above) and then every meeting this season
with its channels (compact cards on phones, the next meeting highlighted and
played games showing the final score once the feed has it; a table from
700px); each game has one `#game-<id>` anchor, which the hub and
tonight cards and the team pages' schedule rows link to. The pages are in the
sitemap and the manifest. The 30-minute refresh renders and writes only the
pair pages of today's games, with the latest report; the others stay as
published and keep their sitemap dates. Who's out, the ranking line, the
"Updated" stamp and the out-of-date notice are `data-volatile`, so a new
report never moves a pair page's `<lastmod>`.

"Also worth knowing" comes from `watchguide/worth.py`: a list of item
functions, each returning lines, in priority order. The block stays last and
shows at most four lines; when more apply, the first ones in this order are
kept:

1. Rest: "Knicks on the second night of a back-to-back", only when the team
   played the day before.
2. Revenge games: "Revenge game: Paul George faces the 76ers", for players on
   either roster with an earlier stint with the opponent in the career map
   (the same file as the rosters; its slim copy keeps each player's `past`
   teams, the year each stint ended and how many seasons it lasted). Only
   players in the recent-awards pool (All-Star or All-NBA in the last three
   seasons, `data/recent_awards.json`) against a team they left in the year
   this season starts or the year before (2026 or 2025 for 2026-27, the
   career map's stint end year), and players who left that team in the
   offseason before this season after five or more seasons there. At most
   two, most recent departures first. Players listed Out on game day don't
   count.
3. Referees, game day only: "Referees: A, B and C" from
   jsierrahoopshype/nbareferees' `data/tonights-crews.json`, used only when
   its `date` is the game's Eastern date. Each name links to
   `https://hoopsmatic.com/referees/referee/<slug>/index.html` when that slug
   is in the site's `data/referees.json` (the list its pages are built from);
   any other name is plain text. Names only, no figures.
4. Career head-to-head for the two players in "Players to watch", from
   jsierrahoopshype/nba-matchups: "Surname vs. Surname: N possessions
   guarding each other through 2025-26", linked to
   `https://hoopsmatic.com/matchups/m/<slug-a>-vs-<slug-b>.html` (slugs in
   alphabetical order). Only when that page is in the matchups sitemap and
   the two guarded each other for at least 300 possessions in total
   (`MIN_POSSESSIONS` in `watchguide/sources/matchups.py`).
5. Season series, once the schedule feed has final scores for an earlier
   meeting (the feed's `score` counts only on `gameStatus` 3).

Referee crews and matchup data are read server side, in the daily build and
in the 30-minute refresh (crews usually arrive after the morning build), and
cached in the published tree (`data/tonights-crews.json`,
`data/referee-pages.json`, `data/matchups/`); a failed fetch keeps the last
copy and never fails the build. `REFEREE_CREWS_URL`, `REFEREES_URL` and
`MATCHUPS_BASE` override the sources. On game day every line is
`data-volatile` (crews arrive and the injury report can change which lines
apply, which moves the cap); any other day the block is stable content. Add
an item by writing one function and listing it in `ITEMS`.

**Injury safety net.** From 3 pm ET to midnight on a game day, if none of the
day's teams has a single listing and the availability feed's newest date is
not today, today's games say "Injury report not available yet" instead of
listing nobody, and the build summary gets a `WARNING injury report not
available yet` line. The warning does not fail the job.

**Logos, flags, headshots and fonts.** Nothing on a page loads from another
domain. Team logos (`assets/logos/<tricode>.svg`) and the player silhouette
come from jsierrahoopshype/nba-headshots; the country flags
(`assets/flags/`, flag-icons, MIT) and the self-hosted DM Sans and JetBrains
Mono fonts (`assets/fonts/`, SIL OFL) from jsierrahoopshype/nba-born-died,
whose design language the pages follow. All are in the repo and published
under `/how-to-watch/assets/` with content-hashed names (the fonts keep plain
names because the stylesheet names them). Player headshots for the game cards'
"Players to watch" (hub, tonight, each team's next game, each pair's next
meeting) are fetched at build time: `players/metadata/players_all.json` gives each
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
  one page per team in `data/teams.json`, one per country in
  `data/countries.json` and one per pair of teams in the schedule.
  `scripts/publish.sh` refuses to publish unless the
  tree's `index.html` files are exactly those paths, and lists any missing or
  unexpected ones. Adding a team or a country needs no change to a script or
  a test. `PUBLISH_CHECK_ONLY=1 ./scripts/publish.sh site` runs the check alone.
- Old content-hashed CSS and JS copies are kept for 7 days so cached HTML still
  finds them, then deleted on publish. `data/asset-first-seen.json` in the
  published tree records when each copy first appeared; any copy a page still
  names, or that is the current build's, is never deleted.
- `data/how-to-watch-links.html` is written on every build: a plain block of
  absolute links to the hub, the tonight page, all 30 teams and every country
  page, for pasting into
  the Worker so the guide has an internal crawl path.

## Automation

- `build-watch-guide-daily.yml` runs at 10:00 UTC, on manual dispatch and on
  every push to main (except changes to README.md or CLAUDE.md only), and
  rebuilds everything. After publishing, its "Live check" step
  (`scripts/live_check.py`) fetches the hub, miami-heat, tonight and spain on
  hoopsmatic.com with a cache-buster until each returns 200, the title this
  run built, no noindex and this run's `<meta name="build">` commit, for up to
  10 minutes, and fails the run otherwise. The result is in the job summary.
- Every page carries `<meta name="build" content="<short sha>">`; the sitemap
  lastmod hash ignores it.
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
