# NBA how-to-watch guide

Generates the HoopsMatic guide at **https://hoopsmatic.com/how-to-watch**: a hub
page, one page per team, and a page for tonight's games. Python plus Jinja2, no
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

A service only shows a price once it has `monthly_price_usd`, a `source_url`, a
`last_verified` date and `verified: true`. Anything else renders as "Price not
confirmed" and stays out of the cheapest-combination maths. A team only shows
local TV once its `local_tv.json` entry is `verified: true`; until then the
in-market view says "Local details coming".

`affiliate_url` is empty everywhere. The affiliate disclosure sentence only
appears on a page once at least one service has a non-empty `affiliate_url`.

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

**Availability.** `https://aderoa.github.io/Injuries/injuries.json`, the keyless
public feed that hoopsmatic.com/depth-charts reads. Rows are
`{player, status, injury, date}`. The feed carries no team, so players are
matched to a team through the NBA's public player index at
`https://cdn.nba.com/static/json/staticData/playerIndex.json`. Only the five
published statuses are kept: Out, Doubtful, Questionable, Probable, Available.
Anything else, such as "Left Game", is left out rather than reinterpreted.

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

## Automation

- `build-watch-guide-daily.yml` runs at 10:00 UTC and rebuilds everything.
- `refresh-watch-guide-injuries.yml` runs every 30 minutes from 16:00 to 04:30
  UTC. It reads the published schedule first and stops within seconds when there
  are no games on the Eastern date.
- Both use `permissions: contents: write` and share the `watch-guide-publish`
  concurrency group, so they never push over each other.

## Adding a page type later

Write a module in `watchguide/pages/` exposing `build(ctx, env) -> list[Page]`
and add it to `BUILDERS` in `watchguide/pages/__init__.py`. It gets the same
`SiteContext` as everything else: teams, games, services, local TV, copy and
availability. Player pages, sit-risk labels and calendar feeds fit this shape.
