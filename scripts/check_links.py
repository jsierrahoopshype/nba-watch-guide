#!/usr/bin/env python3
"""Weekly check of the outbound "where to watch" links.

Requests one sample URL per link template in data/services.json (a level's
`sample`, or its `url` when it has no placeholders), data/local_tv.json and
data/countries.json, verified or not, with the same browser-like requests
the build uses for cdn.nba.com (watchguide.sources.http.IMPERSONATE), and
writes a table to the run summary:

- ok: HTTP 2xx. The title is listed so a person can see it is the right page.
- broken: 404 or 410, or the host does not resolve. Fix or unverify it.
- unverifiable: anything else (401, 403, 429, 5xx, a bot wall, a timeout).
  Many streaming sites block automated requests; that is not a broken link.

It reads the data and never changes it, and it always exits 0: it reports,
it never fails a build. Run it by hand with

    python scripts/check_links.py [--json results.json]
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
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA = ROOT / "data"
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
BOT_WALL = re.compile(r"captcha|are you a robot|access denied|attention required|just a moment|"
                      r"verify you are human|request blocked|pardon our interruption", re.I)
BROKEN = {404, 410}


def targets(data_dir: Path = DATA) -> list[dict[str, str]]:
    """[{where, url, verified}] for every link entry, sample URL for templates."""
    out: list[dict[str, str]] = []

    def add(where: str, entry: dict) -> None:
        url = entry.get("sample") or entry.get("url") or ""
        if url and "{" not in url:
            out.append({"where": where, "url": url, "verified": bool(entry.get("verified"))})

    services = json.loads((data_dir / "services.json").read_text(encoding="utf-8"))
    for svc in services.get("services") or []:
        for level, entry in (svc.get("links") or {}).items():
            if isinstance(entry, dict):
                add(f"{svc['id']} · {level}", entry)
    local = json.loads((data_dir / "local_tv.json").read_text(encoding="utf-8"))
    for slug, team in (local.get("teams") or {}).items():
        for entry in team.get("links") or []:
            if isinstance(entry, dict):
                add(f"{slug} · {(entry.get('names') or ['?'])[0]}", entry)
    countries = json.loads((data_dir / "countries.json").read_text(encoding="utf-8"))
    for slug, country in (countries.get("countries") or {}).items():
        for name, entry in (country.get("links") or {}).items():
            if isinstance(entry, dict):
                add(f"{slug} · {name}", entry)
    return out


def fetch(url: str) -> tuple[int, str, str, str]:
    """(status, final url, body, error). Never raises; status 0 on a
    network error."""
    from curl_cffi import requests

    from watchguide.sources.http import IMPERSONATE
    try:
        resp = requests.get(url, impersonate=IMPERSONATE, timeout=25, allow_redirects=True)
    except Exception as exc:                      # DNS, TLS, timeout
        return 0, url, "", f"{type(exc).__name__}: {exc}"
    return resp.status_code, str(resp.url), resp.text[:400_000], ""


def classify(status: int, body: str, error: str) -> str:
    if status == 0:
        unresolved = re.search(r"resolve host|name or service not known|nodename nor servname|"
                               r"could not resolve", error, re.I)
        return "broken" if unresolved else "unverifiable"
    if status in BROKEN:
        return "broken"
    if 200 <= status < 300:
        title = page_title(body)
        return "unverifiable" if BOT_WALL.search(title) else "ok"
    return "unverifiable"


def page_title(body: str) -> str:
    m = TITLE.search(body or "")
    return " ".join(html.unescape(m.group(1)).split())[:120] if m else ""


def note(url: str, final: str) -> str:
    """"redirected to the homepage" when a deep link lands on "/"."""
    a, b = urlparse(url), urlparse(final)
    if a.path not in ("", "/") and b.path in ("", "/"):
        return "redirected to the homepage"
    if a.netloc != b.netloc:
        return f"redirected to {b.netloc}"
    return ""


def run(items: list[dict], get=fetch, pause: float = 1.0) -> list[dict]:
    cache: dict[str, tuple] = {}
    rows = []
    for item in items:
        url = item["url"]
        if url not in cache:
            status, final, body, error = get(url)
            cache[url] = (status, final, body, error)
            time.sleep(pause)
        status, final, body, error = cache[url]
        rows.append({**item, "status": status, "final": final, "title": page_title(body),
                     "verdict": classify(status, body, error), "note": note(url, final) or error[:120]})
    return rows


def summary(rows: list[dict]) -> str:
    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in ("ok", "broken", "unverifiable")}
    lines = [f"### Outbound links: {counts['broken']} broken, {counts['unverifiable']} unverifiable, "
             f"{counts['ok']} ok",
             "",
             "Broken means 404/410 or a host that does not resolve. Unverifiable means the site "
             "blocked the check (403, bot wall, timeout); it is not counted as broken. "
             "This job never changes the data.",
             "",
             "| Verdict | Link | Used | Status | Title | Note |",
             "|---|---|---|---|---|---|"]
    order = {"broken": 0, "unverifiable": 1, "ok": 2}
    for r in sorted(rows, key=lambda r: (order[r["verdict"]], r["where"])):
        title = r["title"].replace("|", "\\|")
        lines.append(f"| {r['verdict']} | {r['where']}<br>{r['url']} | {'yes' if r['verified'] else 'no'} | "
                     f"{r['status'] or '-'} | {title} | {r['note'].replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", help="also write the rows to this file")
    args = parser.parse_args(argv)
    try:
        rows = run(targets())
    except Exception as exc:                      # a report, never a failure
        print(f"link check could not run: {exc}")
        return 0
    text = summary(rows)
    print(text)
    for r in rows:
        print("ROW " + json.dumps({k: r[k] for k in ("where", "url", "status", "final", "title", "verdict")},
                                  ensure_ascii=False))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(text)
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
