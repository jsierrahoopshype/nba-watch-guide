"""Bits shared by more than one page type."""

from __future__ import annotations

from .. import config, worth
from ..context import SiteContext
from ..coverage import IN_MARKET, OUT_OF_MARKET, channels_for_game, with_local_options
from ..pairs import by_name, game_teams, pair_path
from ..why import explain


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


# --------------------------------------------------------------------------
# One game, laid out the same way everywhere
# --------------------------------------------------------------------------

def all_channels(ctx: SiteContext, game) -> list[dict[str, str]]:
    """Every channel for both fan bases: national first, then each side's
    local channels (home, then away). TBA only when there is nothing else."""
    tba = ctx.labels().get("tba", "TBA")
    out: list[dict[str, str]] = []
    for tricode in (game.home_tricode, game.away_tricode):
        team = ctx.by_tricode.get(tricode)
        for channel in channels_for_game(game, tricode, ctx.local(team.slug) if team else None, tba):
            if channel["kind"] != "tba" and channel["name"] not in {c["name"] for c in out}:
                out.append(channel)
    return out or [{"name": tba, "kind": "tba"}]


def fan_answers(ctx: SiteContext, game) -> tuple[list[dict], list[str]]:
    """(fans, why): for the away and then the home fan base, the out-of-market
    and in-market answer, plus the blackout reasons behind them.

    Built from why.explain, the same sentences as the team pages' "Why can't
    I watch this game?". Its first line is the answer; any further line is a
    reason a service cannot show it, collected once into `why`."""
    text = ctx.copy.get("game", {})
    why_text = ctx.copy.get("why", {})
    fans: list[dict] = []
    why: list[str] = []
    for tricode in (game.away_tricode, game.home_tricode):
        team = ctx.by_tricode.get(tricode)
        if team is None:
            continue
        local = ctx.local(team.slug)
        states = []
        for state, label in ((OUT_OF_MARKET, text["outside"]), (IN_MARKET, text["inside"])):
            sd = with_local_options(ctx.services, local, state)
            lines = explain(game, tricode, sd, local, state, why_text)
            states.append({"state": state, "label": label.format(team=team.short_name),
                           "answer": lines[0] if lines else ""})
            for line in lines[1:]:
                if line not in why:
                    why.append(line)
        fans.append({"team": team, "label": text["fans"].format(team=team.short_name),
                     "states": states})
    return fans, why or [text["why_nothing"]]


def out_block(ctx: SiteContext, game) -> dict:
    """Who's out, in the order the game block shows it.

    On game day: each side's listings, unless the safety net says the report
    has not arrived. Any other day: the game-day line."""
    labels = ctx.labels()
    text = ctx.copy.get("game", {})
    today = game.date_et == ctx.today
    message, sides = "", []
    if not today:
        message = labels.get("availability_on_game_day", "")
    elif ctx.injury_report_missing():
        message = text["injury_report_missing"]
    else:
        empty = empty_players_label(ctx)
        sides = [{"name": ctx.team_name(t), "players": ctx.players_for(t), "empty": empty}
                 for t in (game.away_tricode, game.home_tricode)]
    return {"is_today": today, "message": message, "sides": sides}


def game_view(ctx: SiteContext, game, line: str | None = None) -> dict:
    """Everything the game block partial prints, in its fixed order:
    where to watch, then date and tip time, then who's out with the ranking
    line, then "Also worth knowing"."""
    teams = game_teams(game, ctx.by_tricode)
    away, home = (teams if teams else (ctx.by_tricode.get(game.away_tricode),
                                       ctx.by_tricode.get(game.home_tricode)))
    fans, why = fan_answers(ctx, game)
    text = ctx.copy.get("game", {})
    pair_label = ""
    if teams:
        a, b = by_name(*teams)
        pair_label = text["pair_link"].format(a=a.short_name, b=b.short_name)
    return {
        "game": game,
        "away": away, "home": home,
        "away_name": ctx.team_name(game.away_tricode),
        "home_name": ctx.team_name(game.home_tricode),
        "pair_path": pair_path(game, ctx.by_tricode),
        "pair_label": pair_label,
        "channels": all_channels(ctx, game),
        "fans": fans,
        "why": why,
        "out": out_block(ctx, game),
        "line": ctx.ranking_line(game) if line is None else line,
        "worth": worth.lines(ctx, game),
    }
