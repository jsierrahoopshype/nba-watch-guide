#!/usr/bin/env python3
"""Build data/recent_awards.json from Wikipedia.

All-Star selections come from each All-Star Game page (the two conference
tables under "Rosters"; injury replacements are in those tables and count as
selections, head coaches are skipped). All-NBA First, Second and Third Teams
come from the "From 2023–24" table on the All-NBA Team page, where each
season is marked {{nbay|YYYY}} with YYYY the year the season started.

Season mapping: the All-Star Game played in February YYYY belongs to season
(YYYY-1)-YY; {{nbay|YYYY}} is season YYYY-(YY+1). Only the seasons listed in
data/star_power_weights.json are kept.

    python scripts/fetch_recent_awards.py                 # fetch and write
    python scripts/fetch_recent_awards.py --from-dir DIR  # parse saved wikitext

Wikipedia is not reachable from every sandbox; the fetch-recent-awards
workflow runs this on a GitHub runner.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "recent_awards.json"
WIKI = "https://en.wikipedia.org/wiki/"
RAW = "https://en.wikipedia.org/w/index.php?title={title}&action=raw"
USER_AGENT = "hoopsmatic-watch-guide/1.0 (github.com/jsierrahoopshype/nba-watch-guide)"
ALL_NBA_PAGE = "All-NBA_Team"
TEAMS = ("all_nba_first", "all_nba_second", "all_nba_third")
LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def season_label(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def all_star_page(season: str) -> str:
    """'2025-26' -> '2026_NBA_All-Star_Game'."""
    return f"{int(season[:4]) + 1}_NBA_All-Star_Game"


def fetch(title: str) -> str:
    req = urllib.request.Request(RAW.format(title=title), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def _name(link: tuple[str, str]) -> str:
    target, shown = link
    return (shown or target).strip()


def parse_all_stars(text: str) -> list[str]:
    """Every player in the conference tables under ===Rosters===."""
    start = text.index("===Rosters===")
    end = text.index("\n===", start + len("===Rosters==="))
    players: list[str] = []
    for table in re.findall(r"\{\|.*?\n\|\}", text[start:end], re.S):
        for row in table.split("\n|-")[1:]:
            if re.search(r"coach", row, re.I):
                continue
            links = LINK.findall(row)
            if len(links) >= 2:                # player, then team
                name = _name(links[0])
                if name not in players:
                    players.append(name)
    return players


def parse_all_nba(text: str) -> dict[str, dict[str, list[str]]]:
    """{season: {all_nba_first: [...], all_nba_second: [...], all_nba_third: [...]}}"""
    start = text.index("===From 2023–24===")
    table = re.search(r"\{\|.*?\n\|\}", text[start:], re.S).group(0)
    out: dict[str, dict[str, list[str]]] = {}
    season = None
    for row in table.split("\n|-"):
        marker = re.search(r"\{\{nbay\|(\d{4})\}\}", row)
        if marker:
            season = season_label(int(marker.group(1)))
        if season is None:
            continue
        links = LINK.findall(row)
        # Cells run player, team, player, team, player, team.
        for i, kind in enumerate(TEAMS):
            if 2 * i < len(links):
                out.setdefault(season, {k: [] for k in TEAMS})[kind].append(_name(links[2 * i]))
    return out


def build(pages: dict[str, str], seasons: list[str]) -> dict:
    awards: list[dict[str, str]] = []
    sources: list[dict[str, str]] = []
    all_nba = parse_all_nba(pages[ALL_NBA_PAGE])
    for season in sorted(seasons):
        page = all_star_page(season)
        players = parse_all_stars(pages[page])
        sources.append({"season": season, "award": "all_star", "url": WIKI + page, "count": len(players)})
        awards += [{"player": p, "season": season, "award": "all_star"} for p in players]
        for kind in TEAMS:
            names = all_nba.get(season, {}).get(kind, [])
            sources.append({"season": season, "award": kind, "url": WIKI + ALL_NBA_PAGE, "count": len(names)})
            awards += [{"player": p, "season": season, "award": kind} for p in names]
    return {
        "_note": ("All-Star selections (injury replacements included) and All-NBA First, Second and "
                  "Third Team selections for the seasons in data/star_power_weights.json, from "
                  "Wikipedia. Built by scripts/fetch_recent_awards.py."),
        "fetched": date.today().isoformat(),
        "seasons": sorted(seasons),
        "sources": sources,
        "counts": dict(Counter(f"{a['season']} {a['award']}" for a in awards)),
        "awards": awards,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-dir", type=Path, help="read <title>.wiki files instead of fetching")
    args = parser.parse_args(argv)
    weights = json.loads((ROOT / "data" / "star_power_weights.json").read_text(encoding="utf-8"))
    seasons = list(weights["seasons"])
    titles = [ALL_NBA_PAGE] + [all_star_page(s) for s in seasons]
    if args.from_dir:
        pages = {t: (args.from_dir / f"{t}.wiki").read_text(encoding="utf-8") for t in titles}
    else:
        pages = {t: fetch(t) for t in titles}
    data = build(pages, seasons)
    problems = [s for s in data["sources"]
                if s["count"] < (20 if s["award"] == "all_star" else 5)]
    if problems:
        print(f"refusing to write: lists look incomplete: {problems}", file=sys.stderr)
        return 1
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(data['awards'])} awards to {OUT.relative_to(ROOT)}")
    for s in data["sources"]:
        print(f"  {s['season']} {s['award']:15} {s['count']:3}  {s['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
