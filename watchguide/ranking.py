"""Tonight's ranking: star power, plus stakes once the season is under way.

Every number lives in data/star_power_weights.json:

- Star power. A player's is the sum over the seasons listed there of
  (season weight x points for each award that season); awards in one season
  stack. Awards come from data/recent_awards.json (All-NBA First, Second and
  Third Team and All-Star selections). A team counts the players on its
  current roster who are not listed Out or Doubtful.
- Stakes. Each team's current record comes from the schedule feed. A game
  gets a stakes score only when both teams have played min_games:
  win_pct_points x (combined win percentage), plus close_bonus when the two
  win percentages are within close_within. Before that the ranking is star
  power only.

National TV is shown as a badge and adds nothing. No odds, no predictions.
Each game gets one plain line built from data/copy.json "tonight".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import config
from .model import Game
from .sources.careers import match_key

AWARD_KINDS = ("all_nba_first", "all_nba_second", "all_nba_third", "all_star")
ALL_NBA = ("all_nba_first", "all_nba_second", "all_nba_third")
STARS, STAKES = "stars", "stakes"      # the two heading modes
TOP_FOR_OUT_NOTE = 3                   # a roster's top three by star power get "(Name out)"
LINE_LIMIT = 80                        # characters a game's line aims to stay under


# --------------------------------------------------------------------------
# Data files
# --------------------------------------------------------------------------

def load_weights(data_dir: Path | None = None) -> dict[str, Any]:
    raw = json.loads(((data_dir or config.DATA_DIR) / "star_power_weights.json").read_text(encoding="utf-8"))
    seasons = {str(k): float(v) for k, v in raw["seasons"].items()}
    points = {k: float(raw["points"][k]) for k in AWARD_KINDS}
    s = raw["stakes"]
    return {
        "seasons": seasons,
        "points": points,
        "stakes": {"min_games": int(s["min_games"]), "win_pct_points": float(s["win_pct_points"]),
                   "close_bonus": float(s["close_bonus"]), "close_within": float(s["close_within"])},
        "stakes_heading_share": float(raw["stakes_heading_share"]),
    }


def load_awards(data_dir: Path | None = None) -> list[dict[str, str]]:
    """[{player, season, award}] from data/recent_awards.json, or [] if absent."""
    path = (data_dir or config.DATA_DIR) / "recent_awards.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [a for a in raw.get("awards", []) if a.get("award") in AWARD_KINDS]


# --------------------------------------------------------------------------
# Star power
# --------------------------------------------------------------------------

def player_star_power(awards: list[dict[str, str]], weights: dict[str, Any]
                      ) -> dict[str, dict[str, Any]]:
    """match_key -> {name, score, all_nba, all_star}, seasons outside the
    weights file ignored, awards within one season stacked."""
    out: dict[str, dict[str, Any]] = {}
    for a in awards:
        season_weight = weights["seasons"].get(a.get("season", ""))
        if not season_weight:
            continue
        key = match_key(a["player"])
        rec = out.setdefault(key, {"name": a["player"], "score": 0.0, "all_nba": False, "all_star": False})
        rec["score"] += season_weight * weights["points"][a["award"]]
        if a["award"] in ALL_NBA:
            rec["all_nba"] = True
        else:
            rec["all_star"] = True
    return out


def team_star_power(roster: list[dict[str, Any]], injuries: list[dict[str, str]],
                    power: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Star power of the players in uniform, the best of them by star power,
    and which of the roster's top three by star power are listed Out."""
    status = {match_key(p.get("player", "")): p.get("status") for p in injuries}
    ranked = sorted(((power[k], k) for k in {match_key(p["player"]) for p in roster} if k in power),
                    key=lambda item: (-item[0]["score"], item[0]["name"]))
    result = {"score": 0.0, "best": None, "out": []}
    for i, (rec, key) in enumerate(ranked):
        if status.get(key) in config.RANK_UNAVAILABLE_STATUSES:
            if i < TOP_FOR_OUT_NOTE and status.get(key) == "Out":
                result["out"].append(rec["name"])
            continue
        result["score"] += rec["score"]
        if result["best"] is None:
            result["best"] = rec["name"]
    return result


# --------------------------------------------------------------------------
# Records and stakes
# --------------------------------------------------------------------------

def team_records(games: list[Game]) -> dict[str, tuple[int, int]]:
    """Each team's current record: the most games played that the feed lists
    for it on any game, so it works whether the feed updates every row or
    only the ones already played."""
    best: dict[str, tuple[int, int]] = {}
    for g in games:
        for tricode, wins, losses in ((g.home_tricode, g.home_wins, g.home_losses),
                                      (g.away_tricode, g.away_wins, g.away_losses)):
            if wins is None or losses is None:
                continue
            if tricode not in best or wins + losses > sum(best[tricode]):
                best[tricode] = (wins, losses)
    return best


def stakes_score(away: tuple[int, int] | None, home: tuple[int, int] | None,
                 weights: dict[str, Any]) -> float | None:
    """None until both teams have played min_games."""
    rules = weights["stakes"]
    if not away or not home or min(sum(away), sum(home)) < rules["min_games"]:
        return None
    pct_a, pct_h = away[0] / sum(away), home[0] / sum(home)
    score = rules["win_pct_points"] * (pct_a + pct_h)
    if abs(pct_a - pct_h) <= rules["close_within"]:
        score += rules["close_bonus"]
    return score


# --------------------------------------------------------------------------
# The line and the ranking
# --------------------------------------------------------------------------

def _surname(name: str) -> str:
    parts = name.split()
    return " ".join(parts[1:]) if len(parts) > 1 else name


def _line(text: dict[str, str], sides: list[dict[str, Any]],
          records: list[tuple[int, int]] | None) -> str:
    """'9-1 vs. 8-2: Shai Gilgeous-Alexander vs. Nikola Jokić (Luka Dončić out)'.

    Away first, as in the game title. Surnames, then fewer out names, keep it
    under LINE_LIMIT characters where they can."""
    best = [s["best"] for s in sides if s["best"]]
    outs = [name for s in sides for name in s["out"]]
    prefix = text["rank_records"].format(a=f"{records[0][0]}-{records[0][1]}",
                                         b=f"{records[1][0]}-{records[1][1]}") if records else ""

    def build(names: list[str], out: list[str]) -> str:
        if len(names) == 2:
            core = text["rank_matchup"].format(a=names[0], b=names[1])
        elif names:
            core = names[0]
        else:
            core = text["rank_no_stars"]
        line = prefix + core
        if out:
            line += " " + text["rank_out"].format(names=", ".join(out))
        return line[:1].upper() + line[1:]

    candidates = [(best, outs), ([_surname(n) for n in best], outs)]
    candidates += [([_surname(n) for n in best], outs[:k]) for k in range(len(outs) - 1, -1, -1)]
    for names, out in candidates:
        line = build(names, out)
        if len(line) <= LINE_LIMIT:
            return line
    return build(*candidates[-1])


def rank(games: list[Game], rosters: dict[str, list[dict[str, Any]]],
         injuries: dict[str, list[dict[str, str]]], team_name, text: dict[str, str],
         weights: dict[str, Any], awards: list[dict[str, str]],
         all_games: list[Game] | None = None) -> list[dict[str, Any]]:
    """Every game, best first. Ties go to the earlier tip-off.

    all_games is the whole schedule, where current records are read from;
    it defaults to `games`."""
    power = player_star_power(awards, weights)
    records = team_records(all_games if all_games is not None else games)
    rows = []
    for game in games:
        sides = [team_star_power(rosters.get(t, []), injuries.get(t, []), power)
                 for t in (game.away_tricode, game.home_tricode)]
        star_score = sides[0]["score"] + sides[1]["score"]
        away, home = records.get(game.away_tricode), records.get(game.home_tricode)
        stakes = stakes_score(away, home, weights)
        score = star_score + (stakes or 0.0)
        rows.append({
            "game": game,
            "away_name": team_name(game.away_tricode),
            "home_name": team_name(game.home_tricode),
            "star_power": round(star_score, 2),
            "stakes": None if stakes is None else round(stakes, 2),
            "score": round(score, 2),
            "score_label": f"{score:.1f}",
            "national": list(game.national_codes),
            "line": _line(text, sides, [away, home] if stakes is not None else None),
            # The same line without "(Name out)": the hub lists Out players in
            # a collapsed detail under the row instead.
            "line_core": _line(text, [{**s, "out": []} for s in sides],
                               [away, home] if stakes is not None else None),
        })
    rows.sort(key=lambda r: (-r["score"], r["game"].tipoff_utc or "~", r["game"].game_id))
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


def mode(rows: list[dict[str, Any]], weights: dict[str, Any]) -> str:
    """STAKES when stakes are on for more than the configured share of games."""
    if not rows:
        return STARS
    on = sum(1 for r in rows if r["stakes"] is not None)
    return STAKES if on > weights["stakes_heading_share"] * len(rows) else STARS
