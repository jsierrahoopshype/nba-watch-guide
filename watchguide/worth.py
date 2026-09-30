"""The "Also worth knowing" block under a game: one short line per item.

Each item is a function (ctx, game) -> list of lines (plain strings, or Line
for one with links), listed in ITEMS in priority order: rest, revenge,
referees, career head-to-head, season series. The block shows at most
MAX_LINES; when more apply, the first ones in that order are kept. Adding an
item means writing one more function and placing it in ITEMS; the templates
print whatever lines come back and skip the block when there are none.
Every sentence is a template in data/copy.json "game".

On game day every line is data-volatile: the referee crew arrives during the
day and the injury report can change who counts for a revenge line or who
the head-to-head is about, which can also change which lines the cap keeps.
The referee line only ever shows on game day. Any other day the block is
stable content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable

from .model import Game
from .ranking import player_star_power
from .sources import referees as referees_source
from .sources.careers import match_key

MAX_LINES = 4


@dataclass
class Line:
    """One line: text pieces, each with a link or "" for plain text."""
    parts: list[tuple[str, str]] = field(default_factory=list)
    kind: str = ""
    volatile: bool = False

    @property
    def text(self) -> str:
        return "".join(t for t, _ in self.parts)

    def __str__(self) -> str:
        return self.text


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


def _names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


REVENGE_LIMIT = 2
LONG_STINT = 5          # seasons with the old team for a non-star to count


def revenge_lines(ctx, game: Game) -> list[str]:
    """"Revenge game: Paul George faces the 76ers", for players on either
    roster with an earlier stint with the opponent (career map), when he is
    either in the recent-awards pool (All-Star or All-NBA in the seasons
    data/star_power_weights.json counts, the last three) or left that team in
    the offseason before this season after LONG_STINT or more seasons there.
    At most REVENGE_LIMIT, most recent departures first, then star power.
    Players listed Out on game day do not count."""
    template = _text(ctx).get("revenge", "")
    if not template:
        return []
    season_start = int(str(getattr(ctx, "season", "") or "0")[:4] or 0)
    pool = player_star_power(ctx.recent_awards, ctx.star_weights) if ctx.star_weights else {}
    game_day = game.date_et == ctx.today
    found = []
    for side, opponent in ((game.away_tricode, game.home_tricode), (game.home_tricode, game.away_tricode)):
        out = {match_key(n) for n in ctx.out_players(side)} if game_day else set()
        for player in ctx.star_rosters.get(side, []):
            name = player.get("player", "")
            key = match_key(name)
            if not name or key in out:
                continue
            for stint in player.get("past") or []:
                if stint.get("team") != opponent:
                    continue
                long_stint_just_ended = (bool(season_start) and stint.get("end") == season_start
                                         and stint.get("seasons", 0) >= LONG_STINT)
                if key in pool or long_stint_just_ended:
                    power = pool[key]["score"] if key in pool else 0.0
                    found.append((stint.get("end", 0), power, name, opponent))
    found.sort(key=lambda f: (-f[0], -f[1], f[2]))
    return [template.format(player=name, team=_short(ctx, opp)) for _, _, name, opp in found[:REVENGE_LIMIT]]


def referee_lines(ctx, game: Game) -> list[Line]:
    """"Referees: A, B and C" when the crews file is dated this game's day,
    each name linked to its referee page when that page exists. Names only:
    no figures."""
    crew = referees_source.crew_for(getattr(ctx, "crews", {}), game)
    template = _text(ctx).get("referees", "")
    if not crew or "{names}" not in template:
        return []
    slugs = getattr(ctx, "referee_slugs", set())
    head, tail = template.split("{names}", 1)
    parts: list[tuple[str, str]] = [(head, "")] if head else []
    for i, member in enumerate(crew):
        if i:
            parts.append((" and " if i == len(crew) - 1 else ", ", ""))
        slug = member.get("slug") or ""
        parts.append((member["name"], referees_source.page_url(slug) if slug in slugs else ""))
    if tail:
        parts.append((tail, ""))
    return [Line(parts, kind="referees", volatile=True)]


def _surname(name: str) -> str:
    bits = name.split()
    return " ".join(bits[1:]) if len(bits) > 1 else name


def head_to_head_lines(ctx, game: Game) -> list[Line]:
    """"Tatum vs. Cunningham: 1,240 possessions guarding each other through
    2025-26", linked to the matchup page, for the two players in Players to
    watch when that pair has a page and enough possessions."""
    matchups = getattr(ctx, "matchups", None)
    template = _text(ctx).get("head_to_head", "")
    if matchups is None or "{pair}" not in template:
        return []
    row = ctx.ranking_row(game)
    stars = [s for s in (row or {}).get("stars", []) if s]
    if len(stars) != 2:
        return []
    found = matchups.headline(stars[0], stars[1])
    if not found:
        return []
    label = f"{_surname(stars[0])} vs. {_surname(stars[1])}"
    head, tail = template.split("{pair}", 1)
    tail = tail.format(possessions=f"{found['possessions']:,}", season=found["season"])
    return [Line([(head, ""), (label, found["url"]), (tail, "")] if head else
                 [(label, found["url"]), (tail, "")], kind="head_to_head")]


ITEMS: tuple[Callable[[Any, Game], list], ...] = (
    rest_lines, revenge_lines, referee_lines, head_to_head_lines, series_lines)


def lines(ctx, game: Game) -> list[Line]:
    """The block's lines in priority order, at most MAX_LINES."""
    kinds = {rest_lines: "rest", revenge_lines: "revenge", series_lines: "series"}
    game_day = game.date_et == ctx.today
    out: list[Line] = []
    for item in ITEMS:
        for line in item(ctx, game):
            if not line:
                continue
            if not isinstance(line, Line):
                line = Line([(str(line), "")], kind=kinds.get(item, ""))
            line.volatile = line.volatile or game_day
            out.append(line)
    return out[:MAX_LINES]
