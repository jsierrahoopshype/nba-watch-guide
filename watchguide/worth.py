"""The "Also worth knowing" block under a game: one short line per item.

Each item is a function (ctx, game) -> list of lines, listed in ITEMS in the
order they show. Adding an item means writing one more function and adding
it to ITEMS; the templates print whatever lines come back and skip the block
when there are none. Every sentence is a template in data/copy.json "game".
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

from .model import Game


def _text(ctx) -> dict[str, str]:
    return ctx.copy.get("game", {})


def _short(ctx, tricode: str) -> str:
    team = ctx.by_tricode.get(tricode)
    return team.short_name if team else tricode


def played_on(games: list[Game], tricode: str, day: str) -> bool:
    return any(g.date_et == day and g.involves(tricode) for g in games)


def back_to_back(games: list[Game], game: Game, tricode: str) -> bool:
    """True when the team also played the day before this game (Eastern dates)."""
    before = (date.fromisoformat(game.date_et) - timedelta(days=1)).isoformat()
    return played_on(games, tricode, before)


def rest_lines(ctx, game: Game) -> list[str]:
    """"Knicks on the second night of a back-to-back", only when true, away first."""
    template = _text(ctx).get("back_to_back", "")
    return [template.format(team=_short(ctx, t)) for t in (game.away_tricode, game.home_tricode)
            if template and back_to_back(ctx.games, game, t)]


def season_series(games: list[Game], game: Game) -> dict[str, int] | None:
    """Wins per tricode in this pair's final games before this one, or None
    when the feed has no final score for any of them yet."""
    pair = {game.away_tricode, game.home_tricode}
    before = [g for g in games
              if {g.away_tricode, g.home_tricode} == pair and g.is_final and g.winner
              and (g.date_et, g.tipoff_utc or "") < (game.date_et, game.tipoff_utc or "")
              and g.game_id != game.game_id]
    if not before:
        return None
    wins = {t: 0 for t in pair}
    for g in before:
        wins[g.winner] += 1
    return wins


def series_lines(ctx, game: Game) -> list[str]:
    """"Knicks lead the season series 2-1" or "Season series tied 1-1"."""
    wins = season_series(ctx.games, game)
    if wins is None:
        return []
    text = _text(ctx)
    (lead, lw), (trail, tw) = sorted(wins.items(), key=lambda kv: (-kv[1], kv[0]))
    if lw == tw:
        return [text["series_tied"].format(w=lw, l=tw)]
    return [text["series_lead"].format(team=_short(ctx, lead), w=lw, l=tw)]


ITEMS: tuple[Callable[[Any, Game], list[str]], ...] = (rest_lines, series_lines)


def lines(ctx, game: Game) -> list[str]:
    out: list[str] = []
    for item in ITEMS:
        out.extend(line for line in item(ctx, game) if line)
    return out
