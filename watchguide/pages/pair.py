"""One page per pair of teams that meets this season, at
/how-to-watch/<slug-a>-vs-<slug-b> (see watchguide/pairs.py for the order).

The next meeting comes first, in full, through the same game block as the
tonight page; every meeting this season follows with its channels.
"""

from __future__ import annotations

import re

from .. import seo
from ..context import SiteContext, long_date
from ..pairs import by_name, game_teams, meetings, pair_url
from ..render import Page, date_label, et_label, safe_format
from .common import all_channels, cable_note, chips, crumb_trail, game_view, updated_label

JSONLD_GAME_LIMIT = 10


def pair_title(text: dict, a: str, b: str) -> str:
    """The first template in copy.json pair.titles that fits TITLE_MAX with
    the brand suffix. The last one is short enough for any two names; if a
    rename ever breaks that, seo.branded still keeps it inside the limit."""
    budget = seo.TITLE_MAX - len(seo.BRAND_SUFFIX)
    candidates = [t.format(a=a, b=b) for t in text["titles"]]
    for candidate in candidates:
        if len(candidate) <= budget:
            return candidate + seo.BRAND_SUFFIX
    return seo.branded(candidates[-1])


def pair_description(ctx: SiteContext, text: dict, a: str, b: str, nxt, channels) -> str:
    """Unique per pair: both names, the next date and its channel. Long local
    channel names can crowd the 155 characters, so it tries two channels,
    then one, then copy.json pair.description_short, before cutting."""
    fields = {"a": a, "b": b, "season": ctx.season}
    if nxt is None:
        return seo.description(safe_format(text["description_done"], **fields))
    # Without the owner notes some local names carry ("WANF (Gray)").
    named = [re.sub(r"\s*\([^)]*\)", "", c["name"]) for c in channels if c["kind"] != "tba"]
    attempts = [(text["description"], 2), (text["description"], 1), (text["description_short"], 1)]
    candidates = [safe_format(template, date=long_date(nxt.date_et),
                              channel=" and ".join(named[:n]) if named else text["channel_tba"], **fields)
                  for template, n in attempts]
    return next((c for c in candidates if len(c) <= seo.DESCRIPTION_MAX),
                seo.description(candidates[-1]))


def final_label(ctx: SiteContext, game) -> dict | None:
    """A played game's score once the feed has it (gameStatus 3), away
    first as in the matchup; None before then."""
    if not game.is_final:
        return None
    sides = []
    for tricode, score in ((game.away_tricode, game.away_score), (game.home_tricode, game.home_score)):
        team = ctx.by_tricode.get(tricode)
        sides.append({"name": team.short_name if team else tricode, "score": score,
                      "won": game.winner == tricode})
    return {"label": ctx.copy["game"]["final"], "sides": sides}


def build(ctx: SiteContext, env) -> list[Page]:
    text = ctx.copy["pair"]
    game_text = ctx.copy["game"]
    labels = ctx.labels()
    pages: list[Page] = []

    for slug, games in meetings(ctx.games, ctx.teams).items():
        if ctx.render_pairs is not None and slug not in ctx.render_pairs:
            # Not rendered on this run: a placeholder that is never written.
            pages.append(Page(out_path=f"{slug}/index.html", url=pair_url(slug), html="",
                              lastmod=ctx.today, meta={"pair": slug, "placeholder": True}))
            continue
        a, b = by_name(*game_teams(games[0], ctx.by_tricode))
        fields = {"a": a.short_name, "b": b.short_name, "full_a": a.full_name,
                  "full_b": b.full_name, "season": ctx.season}
        url = pair_url(slug)

        nxt = next((g for g in games if g.date_et >= ctx.today), None)
        view = game_view(ctx, nxt) if nxt else None
        rows = [{
            "game": g,
            "is_next": nxt is not None and g.game_id == nxt.game_id,
            "is_past": g.date_et < ctx.today,
            "date_label": date_label(g.date_et),
            "matchup": f"{ctx.team_name(g.away_tricode)} at {ctx.team_name(g.home_tricode)}",
            "time_label": et_label(g),
            "final": final_label(ctx, g),
            "channels": chips(ctx, all_channels(ctx, g)),
        } for g in games]

        title = pair_title(text, a.short_name, b.short_name)
        desc = pair_description(ctx, text, a.short_name, b.short_name, nxt,
                                view["channels"] if view else [])
        leaf = safe_format(text["breadcrumb"], **fields)
        trail = crumb_trail(ctx, leaf, url)
        blocks = [seo.breadcrumbs(trail)]
        for g in [g for g in games if g.date_et >= ctx.today][:JSONLD_GAME_LIMIT]:
            event = seo.sports_event(g, ctx.team_name(g.home_tricode), ctx.team_name(g.away_tricode),
                                     all_channels(ctx, g), url)
            if event:
                blocks.append(event)

        page_meta = {
            "title": title,
            "description": desc,
            "canonical": url,
            "og_title": title,
            "og_description": desc,
            "jsonld": seo.jsonld(blocks),
        }
        html = env.get_template("pair.html").render(
            page=page_meta,
            copy=ctx.copy,
            labels=labels,
            text={k: safe_format(v, **fields) if isinstance(v, str) else v for k, v in text.items()},
            game_text=game_text,
            view=view,
            rows=rows,
            meetings_cable_note=cable_note(ctx, *[row["channels"] for row in rows]),
            show_pair_link=False,
            updated_label=updated_label(ctx),
            stale=ctx.availability_is_stale(),
            trail=trail,
        )
        pages.append(Page(out_path=f"{slug}/index.html", url=url, html=html, lastmod=ctx.today,
                          meta={"pair": slug, "title": title,
                                "next_game_date": nxt.date_et if nxt else ""}))
    return pages
