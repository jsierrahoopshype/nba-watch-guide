"""One page per team at /how-to-watch/<team-slug>.

Both market states are written into the HTML so a crawler reads them without
running any JavaScript. The toggle only changes which one is on screen.
"""

from __future__ import annotations

from .. import config, seo
from ..context import SiteContext
from ..coverage import (IN_MARKET, OUT_OF_MARKET, build_state_coverage, channels_for_game,
                        moderate_carries_in)
from ..model import CONFIDENCE_COUNTS, Team
from ..render import Page, date_label, et_label, format_block
from .common import (crumb_trail, empty_players_label, game_row,
                     has_affiliate_link, updated_label)

JSONLD_GAME_LIMIT = 10


def _confidence_lines(ctx: SiteContext, combo, games: list, tricode: str, local, state: str,
                      service_data) -> list[str]:
    """One plain line per moderate-confidence carrier the combination leans on."""
    labels = ctx.labels()
    template = labels.get("moderate_carries_line", "")
    lines: list[str] = []
    for hit in moderate_carries_in(combo, games, tricode, service_data, local, state):
        svc = hit["service"]
        if svc.carries_confidence_note:
            line = svc.carries_confidence_note
        elif svc.local_option:
            line = labels.get("local_moderate_note", "")
        else:
            line = template.format(channels=", ".join(hit["channels"]), service=svc.name)
        if line and line not in lines:
            lines.append(line)
    return lines


def _local_notice(ctx: SiteContext, local, text: dict) -> str:
    """The line at the top of the in-market panel, from the team's confidence."""
    if local is None:
        return text["local_missing"]
    if local.exclude_from_us_maths:
        return ""                    # its notes replace the combination instead
    if local.confidence == "low":
        return ctx.labels().get("local_low", "")
    if local.confidence not in CONFIDENCE_COUNTS:
        return local.notes or text["local_missing"]
    return ""


def _state_view(ctx: SiteContext, team: Team, games: list, state: str, text: dict) -> dict:
    local = ctx.local(team.slug)
    coverage = build_state_coverage(games, team.tricode, ctx.services, local, state)
    in_market = state == IN_MARKET
    # The coverage panel only lists services that carry at least one game. The
    # rest are counted in a single line, so a page with unfilled channel lists
    # does not read as thirty rows of zero.
    # League Pass is always listed: its carries list is empty on purpose (the
    # rules block drives it), so at zero games it would otherwise disappear.
    lp_id = ctx.services.league_pass_service_id
    covering = [c for c in coverage.per_service if c.covered or c.service.id == lp_id]
    full, ninety = coverage.cheapest_full, coverage.cheapest_ninety
    # A team whose local coverage is not for US readers gets its note, no maths.
    no_maths_note = local.notes if (in_market and local and local.exclude_from_us_maths) else ""
    if no_maths_note:
        full = ninety = None
    sd = coverage.service_data or ctx.services
    return {
        "state": state,
        "hidden": in_market,                      # out-of-market is the default view
        "label": text["in_market_label"] if in_market else text["out_of_market_label"],
        "per_service": coverage.per_service,
        "covering": covering,
        "not_covering_count": len(coverage.per_service) - len(covering),
        "cheapest_full": full,
        "cheapest_ninety": ninety,
        "full_notes": _confidence_lines(ctx, full, games, team.tricode, local, state, sd),
        "ninety_notes": _confidence_lines(ctx, ninety, games, team.tricode, local, state, sd),
        "priced_services": coverage.priced_services,
        "uncovered": coverage.uncovered,
        "no_maths_note": no_maths_note,
        "local_notice": _local_notice(ctx, local, text) if in_market else "",
    }


def _watching(ctx: SiteContext, local, text: dict) -> dict | None:
    """The 'Watching in' section, straight from data/local_tv.json."""
    if local is None:
        return None
    labels = ctx.labels()
    return {
        "heading": text["watching_heading"],
        "confidence": local.confidence,
        "low_line": labels.get("local_low", "") if local.confidence == "low" else "",
        "notes": local.notes,
        "broadcasters": local.local_broadcasters,
        "ota_note": local.ota.note,
        "streaming": local.streaming,
        "live_tv_carriers": local.live_tv_carriers,
        "territory": local.territory,
        "checked": local.last_checked,
        "sources": local.sources,
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
            prices_checked=ctx.services.prices_checked,
            watching=_watching(ctx, local, text),
            trail=crumb_trail(ctx, team.full_name, url),
        )
        pages.append(Page(out_path=f"{team.slug}/index.html", url=url, html=html,
                          lastmod=ctx.today, meta={"slug": team.slug,
                                                   "next_game_date": nxt.date_et if nxt else ""}))
    return pages
