"""One page per team at /how-to-watch/<team-slug>.

Both market states are written into the HTML so a crawler reads them without
running any JavaScript. The toggle only changes which one is on screen.
"""

from __future__ import annotations

from .. import config, seo
from ..context import SiteContext
from ..coverage import IN_MARKET, OUT_OF_MARKET, build_state_coverage, channels_for_game
from ..model import Team
from ..render import Page, date_label, et_label, format_block
from .common import (crumb_trail, empty_players_label, game_row,
                     has_affiliate_link, updated_label)

JSONLD_GAME_LIMIT = 10


def _state_view(ctx: SiteContext, team: Team, games: list, state: str, text: dict) -> dict:
    local = ctx.local(team.slug)
    coverage = build_state_coverage(games, team.tricode, ctx.services, local, state)
    in_market = state == IN_MARKET
    # The coverage panel only lists services that carry at least one game. The
    # rest are counted in a single line, so a page with unfilled channel lists
    # does not read as thirty rows of zero.
    covering = [c for c in coverage.per_service if c.covered]
    return {
        "state": state,
        "hidden": in_market,                      # out-of-market is the default view
        "label": text["in_market_label"] if in_market else text["out_of_market_label"],
        "per_service": coverage.per_service,
        "covering": covering,
        "not_covering_count": len(coverage.per_service) - len(covering),
        "cheapest_full": coverage.cheapest_full,
        "cheapest_ninety": coverage.cheapest_ninety,
        "priced_services": coverage.priced_services,
        "uncovered": coverage.uncovered,
        "local_verified": bool(local and local.verified),
        "local_names": local.names if local else [],
        "local_note": local.in_market_note if local else "",
        "local_missing": in_market and not (local and local.verified),
    }


def build(ctx: SiteContext, env) -> list[Page]:
    raw = ctx.copy["team"]
    labels = ctx.labels()
    tba = labels.get("tba", "TBA")
    pages: list[Page] = []
    show_disclosure = has_affiliate_link(ctx)

    for team in ctx.teams:
        fields = {"team": team.short_name, "full_team": team.full_name, "season": ctx.season}
        text = format_block(raw, **fields)

        remaining = ctx.remaining_games(team.tricode)
        local = ctx.local(team.slug)
        url = team.url

        schedule = [{
            "date_label": date_label(g.date_et),
            "opponent_label": ("vs " if g.is_home_for(team.tricode) else "at ")
                              + ctx.team_name(g.opponent_of(team.tricode)),
            "time_label": et_label(g),
            "channels": channels_for_game(g, team.tricode, local, tba),
        } for g in remaining]

        nxt = remaining[0] if remaining else None
        next_card = None
        if nxt:
            next_card = game_row(ctx, nxt, channels_for_game(nxt, team.tricode, local, tba))

        views = [_state_view(ctx, team, remaining, state, text)
                 for state in (OUT_OF_MARKET, IN_MARKET)]

        blocks = [seo.breadcrumbs(crumb_trail(ctx, team.full_name, url))]
        for game in remaining[:JSONLD_GAME_LIMIT]:
            event = seo.sports_event(
                game,
                ctx.team_name(game.home_tricode),
                ctx.team_name(game.away_tricode),
                channels_for_game(game, team.tricode, local, tba),
                url,
            )
            if event:
                blocks.append(event)

        page_meta = {
            "title": seo.title(text["title"]),
            "description": seo.description(text["description"]),
            "canonical": url,
            "og_title": seo.title(text["title"]),
            "og_description": seo.description(text["description"]),
            "jsonld": seo.jsonld(blocks),
        }

        html = env.get_template("team.html").render(
            page=page_meta,
            copy=ctx.copy,
            labels=labels,
            text=text,
            team=team,
            views=views,
            schedule=schedule,
            next_game=next_card,
            updated_label=updated_label(ctx),
            stale=ctx.availability_is_stale(),
            empty_players_label=empty_players_label(ctx),
            show_affiliate_disclosure=show_disclosure,
            trail=crumb_trail(ctx, team.full_name, url),
        )
        pages.append(Page(out_path=f"{team.slug}/index.html", url=url, html=html,
                          lastmod=ctx.today, meta={"slug": team.slug,
                                                   "next_game_date": nxt.date_et if nxt else ""}))
    return pages
