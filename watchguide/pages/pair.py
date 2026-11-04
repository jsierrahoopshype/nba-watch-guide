"""One page per pair of teams that meets this season, at
/how-to-watch/<slug-a>-vs-<slug-b> (see watchguide/pairs.py for the order).

The next meeting comes first, in full, through the same game block as the
tonight page; every meeting this season follows with its channels.
"""

from __future__ import annotations

import re
from datetime import date

from .. import seo, share
from ..context import SiteContext
from ..pairs import by_name, game_teams, meetings, ordered, pair_url
from ..render import Page, date_label, et_label, safe_format
from .common import all_channels, cable_note, chips, crumb_trail, game_view, share_channels, updated_label

JSONLD_GAME_LIMIT = 10


# AP style: five months are never abbreviated, September is "Sept."
AP_MONTHS = ("Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.",
             "Oct.", "Nov.", "Dec.")


def title_date(value: str) -> str:
    """'2026-11-06' becomes 'Fri, Nov. 6'."""
    parsed = date.fromisoformat(value)
    return f"{parsed:%a}, {AP_MONTHS[parsed.month - 1]} {parsed.day}"


def month_day(value: str) -> str:
    """'2026-11-15' becomes 'Nov. 15' (AP months, no weekday)."""
    parsed = date.fromisoformat(value)
    return f"{AP_MONTHS[parsed.month - 1]} {parsed.day}"


def pair_title(text: dict, a: str, b: str, next_date: str = "") -> str:
    """copy.json pair.title with the next meeting's date, or pair.title_done
    once the season's last meeting has passed. `a` and `b` are short names
    in URL order. Pair titles lead with the words people search and are
    deliberately longer than seo.TITLE_MAX (Google cuts the end, not the
    names or the date), so they are not run through seo.branded."""
    if next_date:
        return text["title"].format(a=a, b=b, date=month_day(next_date)) + seo.BRAND_SUFFIX
    return text["title_done"].format(a=a, b=b) + seo.BRAND_SUFFIX


def tip_time(game) -> str:
    """The Eastern tip-off in AP style, '7 p.m.', '7:30 p.m.' or 'noon';
    "" when the feed has no real time yet (see seo._tipoff)."""
    tip = seo._tipoff(game)
    if tip is None:
        return ""
    if (tip.hour, tip.minute) == (12, 0):
        return "noon"
    clock = str(tip.hour % 12 or 12) + (f":{tip.minute:02d}" if tip.minute else "")
    return f"{clock} {'a.m.' if tip.hour < 12 else 'p.m.'}"


def readable_channels(ctx: SiteContext, channels) -> list[str]:
    """Every channel's names as a fan reads them, national first
    (all_channels' order), joined across the whole list so each channel or
    service is named once (ctx.join_channels)."""
    parts = [p for channel in channels if channel["kind"] != "tba"
             for p in ctx.channel_parts(channel["name"], channel["kind"], channel.get("slug", ""))]
    return ctx.join_channels(parts)


def or_list(names: list[str]) -> str:
    """'A', 'A or B', 'A, B or C': alternatives, never joined with 'and'."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def and_list(items: list[str]) -> str:
    """'A', 'A and B', 'A, B and C': the parts of the page a description
    names (not alternatives, so not or_list)."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def pair_description(text: dict, a: str, b: str, nxt, view: dict | None,
                     done_fields: dict | None = None) -> str:
    """'<A> vs <B> on <Mon. D> at <time> ET: national TV, local channels in
    each market and streaming options, plus League Pass blackout rules.'

    Only what the next-game block (`view`, from game_view) actually shows is
    named: national TV only when the game has a national channel, local
    channels per team that has one, the blackout clause only when the
    block's "Why ...?" gives a League Pass rule. The time is left out when
    the feed has none. Never shortened: a long one runs past 155 and search
    engines trim the snippet. No meeting left: pair.description_done, as
    before (`done_fields` fills it)."""
    if nxt is None or view is None:
        return seo.description(safe_format(text["description_done"], **(done_fields or {})))
    clock = tip_time(nxt)
    channels = view["channels"]
    parts = []
    if any(c["kind"] == "national" for c in channels):
        parts.append(text["description_national"])
    local_teams = list(dict.fromkeys(c["team"] for c in channels if c["kind"] == "local" and c.get("team")))
    if len(local_teams) >= 2:
        parts.append(text["description_local_both"])
    elif local_teams:
        parts.append(text["description_local_one"].format(team=local_teams[0]))
    parts.append(text["description_streaming"])
    why = view["watch"]["why"]
    blackouts = text["description_blackouts"] if why and "league_pass" in why["kinds"] else ""
    return text["description"].format(
        a=a, b=b, date=month_day(nxt.date_et),
        time=text["description_time"].format(time=clock) if clock else "",
        parts=and_list(parts), blackouts=blackouts)


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
            "channels": chips(ctx, all_channels(ctx, g), game=g),
        } for g in games]

        # Title and description name the teams in URL order ("Pacers vs
        # 76ers" on indiana-pacers-vs-philadelphia-76ers); the page itself
        # keeps the alphabetical-by-name order above.
        url_a, url_b = ordered(a, b)
        title = pair_title(text, url_a.short_name, url_b.short_name, nxt.date_et if nxt else "")
        desc = pair_description(text, url_a.short_name, url_b.short_name, nxt, view,
                                {"a": a.short_name, "b": b.short_name, "season": ctx.season})
        leaf = safe_format(text["breadcrumb"], **fields)
        trail = crumb_trail(ctx, leaf, url)
        card = share.pair_card(
            ctx, slug, a, b,
            share.game_line(date_label(nxt.date_et), et_label(nxt),
                            share_channels(ctx, all_channels(ctx, nxt))) if nxt else "")
        blocks = [seo.breadcrumbs(trail)]
        for g in [g for g in games if g.date_et >= ctx.today][:JSONLD_GAME_LIMIT]:
            event = seo.sports_event(g, ctx.team_name(g.home_tricode), ctx.team_name(g.away_tricode),
                                     url, ctx.arenas.get(g.arena), card.url)
            if event:
                blocks.append(event)

        page_meta = {
            "title": title,
            "description": desc,
            "canonical": url,
            "og_title": title,
            "og_description": desc,
            "jsonld": seo.jsonld(blocks),
            **share.meta(card),
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
                          meta={"pair": slug, "title": title, "share": card,
                                "next_game_date": nxt.date_et if nxt else ""}))
    return pages
