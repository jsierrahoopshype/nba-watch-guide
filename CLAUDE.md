# CLAUDE.md

Standing rules for this repo (the HoopsMatic "how to watch" guide, published
under https://hoopsmatic.com/how-to-watch). Check every one of them before
reporting any PR.

## Standing rules

- **Game view order.** Where to watch comes first in every game view (pair
  pages, the tonight page, hub cards, the team pages' next game). "Also worth
  knowing" stays last, at most four lines (`watchguide/worth.py`).
- **Answer wording.** Alternatives join with "or", never "and". Free options
  say "(free over the air)".
- **Data claims.** Every claim needs an official page, or two independent
  sources dated in the current season, recorded with their URLs. Otherwise
  leave it unchecked. Never guess.
- **SEO fields.** Never change a URL, `<title>`, meta description, canonical
  or og:url unless the task says so. Confirm it in every report (compare
  every page against a build of main).
- **Sitemap lastmod.** It moves only on real content changes. Anything that
  changes during a game day is `data-volatile` (`watchguide/lastmod.py`).
- **No third-party requests.** No new request from the reader's browser to
  any other domain; everything is fetched at build time and prerendered.
  No HoopsHype branding.
- **Phone first.** Check at 375px. Lighthouse mobile stays at 100 for
  Performance and Accessibility, with zero layout shift.
- **Every report ends with** the tip SHA, the page-change count (pages whose
  lastmod content hash changes against main) and a section titled
  "Decisions for you" (or "None").

Never publish (push to gh-pages) from a session unless asked. Publishing is
the build workflow's job.

## Merge from chat

Merge a PR only when the user replies "merge" in the session. Never merge
without that word, and approval for one PR never carries over to another.
When they do:

1. Merge through the GitHub API (`merge_pull_request`), passing
   `expectedHeadSha` = the head SHA you last reported for that PR. If the tip
   moved since then, the API refuses; report that and do not retry with the
   new SHA without a fresh "merge".
2. The merge commit on main starts `build-watch-guide-daily` (push trigger;
   doc-only changes to README.md or CLAUDE.md don't). Find that run: list the
   workflow's runs filtered to event `push` on `main` and take the one whose
   head SHA is the merge commit.
3. If that run is cancelled, or never starts (none shows up within a few
   minutes of the merge), trigger `build-watch-guide-daily` manually
   (workflow_dispatch on main, publish on) and follow that run instead. Say
   in the report that the merge build was cancelled or missing and which run
   you started.
4. Wait for the run to finish, then report its conclusion and the live
   check: the "Live check" step's output (also in the job summary) says
   whether `data/build.json` served this commit and lists each page's HTTP
   status, title and noindex. A failed live check means hoopsmatic.com did
   not serve this commit within 10 minutes.
5. A green run is not proof of publishing. Read the job's steps and confirm
   in the report that "Publish to gh-pages" and "Live check" each ran and
   succeeded (conclusion `success`, not `skipped`). If either was skipped,
   the merge is not live: say so, then handle it as in step 3.
   `tests/test_publish_runs.py` fails if a publish or live-check condition
   would skip on push or schedule runs.

## How the loop works

- `build-watch-guide-daily` runs daily at 10:00 UTC, on manual dispatch and
  on every push to main except README.md and CLAUDE.md changes. The bots'
  own commits (raw availability copy, recent awards) are pushed with
  GITHUB_TOKEN, which never starts a run.
- Every build writes `data/build.json` with the short commit from
  `config.build_id()` (WATCH_GUIDE_BUILD, else GITHUB_SHA, else git HEAD).
  The commit is never written into the pages, so unchanged pages stay
  byte-identical between builds.
- After publishing, `scripts/live_check.py` (browser-like requests, the same
  curl_cffi profile the build uses for cdn.nba.com) polls
  `https://hoopsmatic.com/how-to-watch/data/build.json` with a cache-buster
  until it names this run's commit, then checks the hub, miami-heat, tonight
  and spain for HTTP 200, the title this run built and no noindex, all within
  10 minutes, and fails the run otherwise. The 30-minute refresh has no live
  check.

## Working here

- Tests: `python -m pytest` (Playwright tests use the preinstalled Chromium).
- Offline build of a published tree: `python -m watchguide --out <dir>
  --today YYYY-MM-DD build --offline`.
- Copy lives in `data/copy.json`; services and lineups in
  `data/services.json`; local TV in `data/local_tv.json`.
