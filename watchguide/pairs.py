"""Team-vs-team pages: one per pair of teams that meets this season.

The URL is /how-to-watch/<slug-a>-vs-<slug-b>, the two slugs from
data/teams.json in alphabetical order. That order is the only one that
exists: the Worker cannot redirect the reversed URL, so nothing may link to
it and no page is written for it. Every link to a pair page goes through
pair_path() or pair_url() here.

Titles name the teams by short name, also alphabetically ("76ers vs.
Knicks"), which can differ from the slug order ("new-york-knicks-vs-
philadelphia-76ers"). Both orders are fixed, so each pair still has exactly
one URL and one title.
"""

from __future__ import annotations

from .model import Game, Team
from . import config

SEPARATOR = "-vs-"


def ordered(a: Team, b: Team) -> tuple[Team, Team]:
    """The two teams in URL order: alphabetical by slug."""
    return (a, b) if a.slug <= b.slug else (b, a)


def by_name(a: Team, b: Team) -> tuple[Team, Team]:
    """The two teams in title order: alphabetical by short name."""
    return (a, b) if (a.short_name.casefold(), a.slug) <= (b.short_name.casefold(), b.slug) else (b, a)


def pair_slug(a: Team, b: Team) -> str:
    first, second = ordered(a, b)
    return f"{first.slug}{SEPARATOR}{second.slug}"


def game_teams(game: Game, by_tricode: dict[str, Team]) -> tuple[Team, Team] | None:
    away, home = by_tricode.get(game.away_tricode), by_tricode.get(game.home_tricode)
    if away is None or home is None or away.slug == home.slug:
        return None
    return away, home


def game_pair_slug(game: Game, by_tricode: dict[str, Team]) -> str:
    """The pair page a game lives on, or "" for a team not in data/teams.json."""
    teams = game_teams(game, by_tricode)
    return pair_slug(*teams) if teams else ""


def pair_path(game: Game, by_tricode: dict[str, Team]) -> str:
    """Root-relative link to the game on its pair page, anchored at the game."""
    slug = game_pair_slug(game, by_tricode)
    return f"{config.site_path(slug)}#game-{game.game_id}" if slug else ""


def pair_url(slug: str) -> str:
    return config.public_url(slug)


def meetings(games: list[Game], teams: list[Team]) -> dict[str, list[Game]]:
    """Pair slug to that pair's games in tip-off order, for every pair that
    meets in the schedule. Sorted by slug so the output is stable."""
    by_tricode = {t.tricode: t for t in teams}
    out: dict[str, list[Game]] = {}
    for game in games:
        slug = game_pair_slug(game, by_tricode)
        if slug:
            out.setdefault(slug, []).append(game)
    for rows in out.values():
        rows.sort(key=lambda g: (g.date_et, g.tipoff_utc or "~", g.game_id))
    return dict(sorted(out.items()))


def pair_slugs(games: list[Game], teams: list[Team]) -> list[str]:
    return list(meetings(games, teams))
