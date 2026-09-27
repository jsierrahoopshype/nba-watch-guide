"""data/recent_awards.json and the Wikipedia parser that builds it."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = json.loads((ROOT / "data" / "recent_awards.json").read_text(encoding="utf-8"))
WEIGHTS = json.loads((ROOT / "data" / "star_power_weights.json").read_text(encoding="utf-8"))

spec = importlib.util.spec_from_file_location("fetch_recent_awards", ROOT / "scripts" / "fetch_recent_awards.py")
fetcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetcher)


def test_every_list_has_a_source_url():
    kinds = {"all_star", "all_nba_first", "all_nba_second", "all_nba_third"}
    got = {(s["season"], s["award"]) for s in DATA["sources"]}
    assert got == {(season, k) for season in WEIGHTS["seasons"] for k in kinds}
    for s in DATA["sources"]:
        assert s["url"].startswith("https://en.wikipedia.org/wiki/")
        assert s["count"] >= (20 if s["award"] == "all_star" else 5)


def test_awards_are_in_the_window_and_well_formed():
    assert set(DATA["seasons"]) == set(WEIGHTS["seasons"])
    for a in DATA["awards"]:
        assert a["season"] in WEIGHTS["seasons"] and a["award"] in WEIGHTS["points"] and a["player"]
    per_list = {}
    for a in DATA["awards"]:
        per_list.setdefault((a["season"], a["award"]), []).append(a["player"])
    for players in per_list.values():
        assert len(players) == len(set(players))          # nobody twice in one list


ALL_STAR_PAGE = """
===Rosters===
{| class="wikitable"
|+Eastern Conference All-Stars
|-
!Pos!!Player!!Team!!No.
|-
|G
|style="text-align:left"|[[Jalen Brunson]]
|style="text-align:left"|[[New York Knicks]]
|3
|-
|F
|style="text-align:left"|''[[Joel Embiid]]''{{ref|inj1|INJ1}}
|style="text-align:left"|[[Philadelphia 76ers]]
|7
|-
|G
|style="text-align:left"|[[Trae Young]]{{ref|rep1|REP1}}
|style="text-align:left"|[[Atlanta Hawks]]
|4
|-
|style="text-align:left" colspan="5"|'''Head coach''': [[Doc Rivers]] ([[Milwaukee Bucks]])
|}
===Game===
"""

ALL_NBA_PAGE = """
===From 2023–24===
{| class="wikitable"
|-
| rowspan="5" |{{anchor|2023–24}}{{nbay|2023}}
| {{flagicon|CAN}} [[Shai Gilgeous-Alexander]]^ || [[Oklahoma City Thunder]] || [[Anthony Edwards (basketball)|Anthony Edwards]]^ || [[Minnesota Timberwolves]] || [[LeBron James]] || [[Los Angeles Lakers]]
|-style="border-top:3px solid black"
|rowspan=5| {{nbay|2024}}
| [[Nikola Jokić]] || [[Denver Nuggets]] || [[Stephen Curry]] || [[Golden State Warriors]] || [[James Harden]] || [[Los Angeles Clippers]]
|}
"""


def test_all_star_parser_counts_replacements_and_skips_coaches():
    assert fetcher.parse_all_stars(ALL_STAR_PAGE) == ["Jalen Brunson", "Joel Embiid", "Trae Young"]


def test_all_nba_parser_maps_nbay_to_seasons_and_columns_to_teams():
    got = fetcher.parse_all_nba(ALL_NBA_PAGE)
    assert got["2023-24"] == {"all_nba_first": ["Shai Gilgeous-Alexander"],
                              "all_nba_second": ["Anthony Edwards"], "all_nba_third": ["LeBron James"]}
    assert got["2024-25"]["all_nba_third"] == ["James Harden"]


def test_all_star_game_year_maps_to_the_season_it_is_played_in():
    assert fetcher.all_star_page("2025-26") == "2026_NBA_All-Star_Game"
    assert fetcher.all_star_page("2023-24") == "2024_NBA_All-Star_Game"
