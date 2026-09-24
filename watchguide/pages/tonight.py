"""The tonight page at /how-to-watch/tonight."""

from __future__ import annotations

from .. import config, seo
from ..context import SiteContext
from ..coverage import channels_for_game
from ..render import Page
from .common import crumb_trail, empty_players_label, game_row, updated_label

SLUG = "tonight"


def build(ctx: SiteContext, env) -> list[Page]:
    text = ctx.copy["tonight"]
    labels = ctx.labels()
    url = config.public_url(SLUG)
    games = ctx.games_today()

    rows = []
    for game in games:
        channels = channels_for_game(game, game.home_tricode,
                                     ctx.local(ctx.by_tricode[game.home_tricode].slug)
                                     if game.home_tricode in ctx.by_tricode else None,
                                     labels.get("tba", "TBA"))
        rows.append(game_row(ctx, game, channels))

    blocks = [seo.breadcrumbs(crumb_trail(ctx, text["h1"], url))]
    for row in rows:
        event = seo.sports_event(row["game"], row["home_name"], row["away_name"], row["channels"], url)
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

    html = env.get_template("tonight.html").render(
        page=page_meta,
        copy=ctx.copy,
        labels=labels,
        text=text,
        games=rows,
        updated_label=updated_label(ctx),
        empty_players_label=empty_players_label(ctx),
        trail=crumb_trail(ctx, text["h1"], url),
    )
    return [Page(out_path=f"{SLUG}/index.html", url=url, html=html, lastmod=ctx.today)]
