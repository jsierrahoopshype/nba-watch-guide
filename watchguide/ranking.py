"""Tonight's games, ranked by a score anyone can check.

score = the All-Star selections of every rostered player not listed Out or
Doubtful, plus a fixed number of points when the game is on national TV.
Nothing else goes in: no records (no reliable feed for them has been
confirmed), no odds, no predictions. Each game gets one plain line saying why
it sits where it does, built from templates in data/copy.json "tonight".
"""

from __future__ import annotations

from typing import Any

from . import config
from .model import Game
from .sources.careers import match_key


def team_stars(roster: list[dict[str, Any]], injuries: list[dict[str, str]]
               ) -> tuple[int, list[str], int]:
    """(selections available tonight, All-Stars listed out, All-Stars on the roster)."""
    unavailable = {match_key(p.get("player", "")) for p in injuries
                   if p.get("status") in config.RANK_UNAVAILABLE_STATUSES}
    total = 0
    absent: list[str] = []
    all_stars = 0
    for player in roster:
        if player["all_star"] <= 0:
            continue
        all_stars += 1
        if match_key(player["player"]) in unavailable:
            absent.append(player["player"])
        else:
            total += player["all_star"]
    return total, absent, all_stars


def _names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _line(text: dict[str, str], stars: int, absent: list[str], all_stars: int, game: Game) -> str:
    parts = [text["rank_stars"].format(stars=stars) if stars else text["rank_no_stars"]]
    if absent:
        shown = absent[:2]
        more = len(absent) - len(shown)
        names = _names(shown) + (text["rank_more"].format(count=more) if more else "")
        parts.append(text["rank_absent"].format(names=names))
    elif all_stars:
        parts.append(text["rank_all_playing"])
    if game.is_national:
        parts.append(text["rank_national"].format(channels=_names(game.national_codes)))
    line = ", ".join(parts)
    return line[:1].upper() + line[1:] + "."


def rank(games: list[Game], rosters: dict[str, list[dict[str, Any]]],
         injuries: dict[str, list[dict[str, str]]], team_name, text: dict[str, str]
         ) -> list[dict[str, Any]]:
    """Every game, best first. Ties go to the earlier tip-off."""
    rows = []
    for game in games:
        stars = absent_all = 0
        absent: list[str] = []
        for tricode in (game.away_tricode, game.home_tricode):
            got, out, count = team_stars(rosters.get(tricode, []), injuries.get(tricode, []))
            stars += got
            absent += out
            absent_all += count
        national = config.RANK_NATIONAL_POINTS if game.is_national else 0
        rows.append({
            "game": game,
            "away_name": team_name(game.away_tricode),
            "home_name": team_name(game.home_tricode),
            "stars": stars,
            "national_points": national,
            "score": stars + national,
            "line": _line(text, stars, absent, absent_all, game),
        })
    rows.sort(key=lambda r: (-r["score"], r["game"].tipoff_utc or "~", r["game"].game_id))
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows
