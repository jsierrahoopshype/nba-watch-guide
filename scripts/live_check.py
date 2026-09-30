"""After a publish, check that hoopsmatic.com serves this run's build.

First it polls data/build.json (BUILD_FILE, written by every build) with a
cache-buster until its "build" is this run's short commit. Then it fetches
each page in PAGES with a cache-buster and checks: HTTP 200, the same <title>
as the page this run built, and no noindex (robots meta or X-Robots-Tag).
Both steps retry every INTERVAL seconds within one TIMEOUT, and the result is
written to the job summary.

Requests go through curl_cffi with the same browser impersonation profile the
build uses for cdn.nba.com (watchguide.sources.http.IMPERSONATE).

    python scripts/live_check.py --site site --sha "$GITHUB_SHA"

Exits 0 when everything matched, 1 when it never did.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "https://hoopsmatic.com/how-to-watch"
BUILD_FILE = "data/build.json"
PAGES = ["", "miami-heat", "tonight", "spain"]      # hub, a team, tonight, a country
TIMEOUT = 600
INTERVAL = 20

TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
ROBOTS = re.compile(r'<meta name="robots" content="([^"]*)"', re.I)

Fetch = Callable[[str], "tuple[int, dict[str, str], str]"]


def fetch(url: str) -> tuple[int, dict[str, str], str]:
    """(status, lower-cased headers, body) from a browser-like request. Never
    raises: a network error is status 0 with the reason in headers["error"]."""
    from curl_cffi import requests
    from watchguide.sources.http import IMPERSONATE
    try:
        resp = requests.get(url, impersonate=IMPERSONATE, timeout=30,
                            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
    except Exception as exc:                      # DNS, TLS, timeout
        return 0, {"error": f"{type(exc).__name__}: {exc}"}, ""
    return resp.status_code, {k.lower(): v for k, v in resp.headers.items()}, resp.text


def page_url(base: str, page: str) -> str:
    return f"{base.rstrip('/')}/{page}" if page else base.rstrip("/")


def expected_title(site: Path, page: str) -> str:
    path = site / page / "index.html" if page else site / "index.html"
    found = TITLE.search(path.read_text(encoding="utf-8"))
    if not found:
        raise SystemExit(f"live-check: no <title> in {path}")
    return html.unescape(found.group(1).strip())


def served_build(status: int, body: str) -> str:
    """The "build" in a data/build.json response, or "" when there is none."""
    if status != 200:
        return ""
    try:
        return str(json.loads(body).get("build") or "")
    except (ValueError, AttributeError):
        return ""


def check_page(body: str, status: int, headers: dict[str, str], title: str) -> dict:
    seen_title = TITLE.search(body)
    seen_title = html.unescape(seen_title.group(1).strip()) if seen_title else ""
    robots = " ".join(ROBOTS.findall(body)) + " " + headers.get("x-robots-tag", "")
    result = {
        "status": status,
        "title": seen_title,
        "title_ok": seen_title == title,
        "robots_noindex": "noindex" in robots.lower(),
        "error": headers.get("error", ""),
    }
    result["ok"] = status == 200 and result["title_ok"] and not result["robots_noindex"]
    return result


def run(site: Path, sha: str, base: str = BASE, pages: list[str] | None = None, timeout: float = TIMEOUT,
        interval: float = INTERVAL, get: Fetch | None = None, sleep=None, clock=None) -> tuple[bool, dict]:
    """(all matched, report). `get`, `sleep` and `clock` are for tests."""
    get, sleep, clock = get or fetch, sleep or time.sleep, clock or time.monotonic
    pages = PAGES if pages is None else pages
    sha = sha[:7]
    titles = {p: expected_title(site, p) for p in pages}
    start = clock()
    report = {"sha": sha, "build_url": f"{base.rstrip('/')}/{BUILD_FILE}", "build_seen": "",
              "build_status": 0, "build_attempts": 0, "page_attempts": 0, "pages": {}, "elapsed": 0.0}

    def out_of_time() -> bool:
        report["elapsed"] = clock() - start
        return report["elapsed"] + interval > timeout

    # 1. Wait for this run's build.json to be served.
    while True:
        report["build_attempts"] += 1
        status, _, body = get(f"{report['build_url']}?v={sha}-{report['build_attempts']}")
        report["build_status"], report["build_seen"] = status, served_build(status, body)
        if report["build_seen"] == sha:
            break
        if out_of_time():
            return False, report
        sleep(interval)

    # 2. The pages: 200, the title this run built, no noindex.
    while True:
        report["page_attempts"] += 1
        for page in pages:
            status, headers, body = get(f"{page_url(base, page)}?v={sha}-{report['page_attempts']}")
            report["pages"][page] = check_page(body, status, headers, titles[page])
            report["pages"][page].update(url=page_url(base, page), expected_title=titles[page])
        if all(r["ok"] for r in report["pages"].values()):
            report["elapsed"] = clock() - start
            return True, report
        if out_of_time():
            return False, report
        sleep(interval)


def summary(ok: bool, report: dict) -> str:
    build_ok = report["build_seen"] == report["sha"]
    lines = [f"### Live check: {'passed' if ok else 'FAILED'}", "",
             f"Build `{report['sha']}`, {report['elapsed']:.0f}s.", "",
             f"- `{report['build_url']}`: {'serves' if build_ok else 'never served'} this build "
             f"(last seen: `{report['build_seen'] or 'none'}`, HTTP {report['build_status'] or 'no response'}, "
             f"{report['build_attempts']} attempt(s))"]
    if report["pages"]:
        lines += ["", f"Pages, {report['page_attempts']} attempt(s):", "",
                  "| Page | HTTP | Title | noindex | Result |", "|---|---|---|---|---|"]
        for r in report["pages"].values():
            title = "matches" if r["title_ok"] else f"expected “{r['expected_title']}”, got “{r['title'] or 'none'}”"
            status = str(r["status"] or r["error"] or "no response")
            lines.append(f"| {r['url']} | {status} | {title} | {'yes' if r['robots_noindex'] else 'no'} | "
                         f"{'ok' if r['ok'] else 'fail'} |")
    else:
        lines += ["", "Pages not checked: the build was never served."]
    return "\n".join(lines) + "\n"


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
