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
  changes during a game day is `data-volatile`, and the build marker is left
  out of the hash (`watchguide/lastmod.py`).
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
3. Wait for it to finish, then report its conclusion and the live check: the
   "Live check" step's output (also in the job summary) lists each page's
   HTTP status, title, noindex and build marker. A failed live check means
   hoopsmatic.com did not serve this commit's pages within 10 minutes.

## How the loop works

- `build-watch-guide-daily` runs daily at 10:00 UTC, on manual dispatch and
  on every push to main except README.md and CLAUDE.md changes. The bots'
  own commits (raw availability copy, recent awards) are pushed with
  GITHUB_TOKEN, which never starts a run.
- Every page carries `<meta name="build" content="<short sha>">` from
  `config.build_id()` (WATCH_GUIDE_BUILD, else GITHUB_SHA, else git HEAD).
- After publishing, `scripts/live_check.py` fetches the hub, miami-heat,
  tonight and spain pages with a cache-buster until each returns 200, the
  title this run built, no noindex and this run's build marker, for up to
  10 minutes, and fails the run otherwise.

## Working here

- Tests: `python -m pytest` (Playwright tests use the preinstalled Chromium).
- Offline build of a published tree: `python -m watchguide --out <dir>
  --today YYYY-MM-DD build --offline`.
- Copy lives in `data/copy.json`; services and lineups in
  `data/services.json`; local TV in `data/local_tv.json`.
