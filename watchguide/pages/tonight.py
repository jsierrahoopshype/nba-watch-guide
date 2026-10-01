"""The tonight page at /how-to-watch/tonight."""

from __future__ import annotations

from .. import config, seo, share
from ..context import SiteContext
from ..render import Page
from .common import crumb_trail, game_view, updated_label

SLUG = "tonight"


def build(ctx: SiteContext, env) -> list[Page]:
    text = ctx.copy["tonight"]
    labels = ctx.labels()
    url = config.public_url(SLUG)
    # On an off day the page leads with the next day that has games. One list
    # of game cards, in ranking order; each card carries its ranking line.
    show = ctx.showcase()
    cards = [{"rank": r["rank"], "stakes": r["stakes"], "national": r["national"],
              "view": game_view(ctx, r["game"], line=r["line"])} for r in show["rows"]]

    share_card = share.tonight_card(ctx)
    blocks = [seo.breadcrumbs(crumb_trail(ctx, text["h1"], url))]
    for card in cards:
        view = card["view"]
        event = seo.sports_event(view["game"], view["home_name"], view["away_name"], url,
                                 ctx.arenas.get(view["game"].arena), share_card.url)
        if event:
            blocks.append(event)

    page_meta = {
        "title": seo.title(text["title"]),
        "description": seo.description(text["description"]),
        "canonical": url,
        "og_title": seo.title(text["title"]),
        "og_description": seo.description(text["description"]),
        "jsonld": seo.jsonld(blocks),
        **share.meta(share_card),
    }

    html = env.get_template("tonight.html").render(
        cards=cards,
        rank_text={"heading": show["heading"], "basis": show["basis"]},
        page=page_meta,
        copy=ctx.copy,
        labels=labels,
        text=text,
        game_text=ctx.copy.get("game", {}),
        show_pair_link=True,
        is_today=show["is_today"],
        updated_label=updated_label(ctx),
        stale=ctx.availability_is_stale(),
        trail=crumb_trail(ctx, text["h1"], url),
    )
    return [Page(out_path=f"{SLUG}/index.html", url=url, html=html, lastmod=ctx.today,
                 meta={"share": share_card})]
