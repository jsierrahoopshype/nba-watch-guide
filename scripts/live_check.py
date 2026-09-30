"""After a publish, check that hoopsmatic.com serves this run's pages.

For each page in PAGES it fetches the live URL with a cache-buster and checks:
HTTP 200, the same <title> as the page this run built, no noindex (robots
meta or X-Robots-Tag), and a <meta name="build"> equal to this run's short
commit. It retries every INTERVAL seconds until every page passes in the same
round or TIMEOUT runs out, and writes the last round to the job summary.

    python scripts/live_check.py --site site --sha "$GITHUB_SHA"

Exits 0 when everything matched, 1 when it never did.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable

BASE = "https://hoopsmatic.com/how-to-watch"
PAGES = ["", "miami-heat", "tonight", "spain"]      # hub, a team, tonight, a country
TIMEOUT = 600
INTERVAL = 20
USER_AGENT = "Mozilla/5.0 (compatible; watch-guide-live-check; +https://github.com/jsierrahoopshype/nba-watch-guide)"

TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
BUILD = re.compile(r'<meta name="build" content="([^"]*)"')
ROBOTS = re.compile(r'<meta name="robots" content="([^"]*)"', re.I)

Fetch = Callable[[str], "tuple[int, dict[str, str], str]"]


def fetch(url: str) -> tuple[int, dict[str, str], str]:
    """(status, lower-cased headers, body). Never raises: a network error is status 0."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache",
                                               "Pragma": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, \
                resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, ""
    except Exception as exc:                      # DNS, TLS, timeout
        return 0, {"error": f"{type(exc).__name__}: {exc}"}, ""


def page_url(base: str, page: str) -> str:
    return f"{base.rstrip('/')}/{page}" if page else base.rstrip("/")


def expected_title(site: Path, page: str) -> str:
    path = site / page / "index.html" if page else site / "index.html"
    found = TITLE.search(path.read_text(encoding="utf-8"))
    if not found:
        raise SystemExit(f"live-check: no <title> in {path}")
    return html.unescape(found.group(1).strip())


def check_page(body: str, status: int, headers: dict[str, str], title: str, sha: str) -> dict:
    seen_title = TITLE.search(body)
    seen_title = html.unescape(seen_title.group(1).strip()) if seen_title else ""
    robots = " ".join(ROBOTS.findall(body)) + " " + headers.get("x-robots-tag", "")
    build = BUILD.search(body)
    result = {
        "status": status,
        "title": seen_title,
        "title_ok": seen_title == title,
        "robots_noindex": "noindex" in robots.lower(),
        "build": build.group(1) if build else "",
        "error": headers.get("error", ""),
    }
    result["build_ok"] = result["build"] == sha
    result["ok"] = status == 200 and result["title_ok"] and not result["robots_noindex"] and result["build_ok"]
    return result


def run(site: Path, sha: str, base: str = BASE, pages: list[str] | None = None, timeout: float = TIMEOUT,
        interval: float = INTERVAL, get: Fetch | None = None, sleep=None, clock=None) -> tuple[bool, dict]:
    """(all matched, {page: last result}). `get`, `sleep` and `clock` are for tests."""
    get, sleep, clock = get or fetch, sleep or time.sleep, clock or time.monotonic
    pages = PAGES if pages is None else pages
    sha = sha[:7]
    titles = {p: expected_title(site, p) for p in pages}
    start = clock()
    attempt = 0
    results: dict[str, dict] = {}
    while True:
        attempt += 1
        for page in pages:
            url = f"{page_url(base, page)}?v={sha}-{attempt}"
            status, headers, body = get(url)
            results[page] = check_page(body, status, headers, titles[page], sha)
            results[page].update(url=page_url(base, page), expected_title=titles[page])
        elapsed = clock() - start
        if all(r["ok"] for r in results.values()):
            return True, {"attempts": attempt, "elapsed": elapsed, "pages": results, "sha": sha}
        if elapsed + interval > timeout:
            return False, {"attempts": attempt, "elapsed": elapsed, "pages": results, "sha": sha}
        sleep(interval)


def summary(ok: bool, report: dict) -> str:
    head = (f"### Live check: {'passed' if ok else 'FAILED'}\n\n"
            f"Build `{report['sha']}`, {report['attempts']} attempt(s) over {report['elapsed']:.0f}s.\n\n"
            "| Page | HTTP | Title | noindex | Build | Result |\n|---|---|---|---|---|---|\n")
    rows = []
    for r in report["pages"].values():
        title = "matches" if r["title_ok"] else f"expected “{r['expected_title']}”, got “{r['title'] or 'none'}”"
        build = r["build"] or "none"
        status = str(r["status"] or r["error"] or "no response")
        rows.append(f"| {r['url']} | {status} | {title} | {'yes' if r['robots_noindex'] else 'no'} | {build} | "
                    f"{'ok' if r['ok'] else 'fail'} |")
    return head + "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--site", default="site", help="the tree this run built and published")
    ap.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""), help="this run's commit")
    ap.add_argument("--base", default=os.environ.get("LIVE_CHECK_BASE", BASE))
    ap.add_argument("--timeout", type=float, default=TIMEOUT)
    ap.add_argument("--interval", type=float, default=INTERVAL)
    args = ap.parse_args(argv)
    if not args.sha:
        print("live-check: no commit given (--sha or GITHUB_SHA)", file=sys.stderr)
        return 1
    ok, report = run(Path(args.site), args.sha, args.base, timeout=args.timeout, interval=args.interval)
    text = summary(ok, report)
    print(text)
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
