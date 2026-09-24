"""Bits shared by more than one page type."""

from __future__ import annotations

from .. import config
from ..context import SiteContext


def crumb_trail(ctx: SiteContext, leaf_name: str = "", leaf_url: str = "") -> list[tuple[str, str]]:
    labels = ctx.labels()
    trail = [(labels.get("breadcrumb_home", "How to watch"), config.public_url())]
    if leaf_name and leaf_url:
        trail.append((leaf_name, leaf_url))
    return trail


def updated_label(ctx: SiteContext) -> str:
    """Server-side fallback. JS replaces it with 'Updated N min ago'."""
    labels = ctx.labels()
    if not ctx.injuries_updated_at:
        return ""
    return f"{labels.get('updated_prefix', 'Updated')} {ctx.injuries_updated_at[:16].replace('T', ' ')} ET"


def game_row(ctx: SiteContext, game, channels: list[dict[str, str]]) -> dict:
    """Shape a game for the game card partial.

    Availability is only shown for a game being played today. The league's
    report is written for that day's games, so carrying a status onto a game
    three days out would put a stale label next to a player's name.
    """
    today = game.date_et == ctx.today
    return {
        "game": game,
        "is_today": today,
        "home_name": ctx.team_name(game.home_tricode),
        "away_name": ctx.team_name(game.away_tricode),
        "home_players": ctx.players_for(game.home_tricode) if today else [],
        "away_players": ctx.players_for(game.away_tricode) if today else [],
        "channels": channels,
    }


def has_affiliate_link(ctx: SiteContext) -> bool:
    return any(s.affiliate_url for s in ctx.services.services)


def empty_players_label(ctx: SiteContext) -> str:
    """Tell apart 'we have the report and this team has nobody on it' from
    'there is no report for this season yet'. Neither case is an error, and
    neither renders as a bare empty list."""
    labels = ctx.labels()
    if ctx.has_injury_data:
        return labels.get("no_players_listed", "Nobody listed.")
    return labels.get("no_injury_report", "No injury report yet.")
