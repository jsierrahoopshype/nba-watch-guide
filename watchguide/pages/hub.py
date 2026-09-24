"""The hub page at /how-to-watch."""

from __future__ import annotations

from collections import Counter

from .. import config, seo
from ..context import SiteContext
from ..render import Page, format_block
from .common import crumb_trail


def national_partners(ctx: SiteContext) -> list[dict]:
    """Broadcaster codes the schedule feed lists on national games, with counts.

    Nothing is added to this list. When the league has not published national
    assignments yet it comes back empty and the page says so.
    """
    counts: Counter[str] = Counter()
    for game in ctx.games:
        for code in game.national_codes:
            counts[code] += 1
    return [{"code": code, "games": n} for code, n in counts.most_common()]


def faq_entries(ctx: SiteContext) -> list[dict[str, str]]:
    """FAQ text. Anything that states a fact is read out of the data files."""
    entries: list[dict[str, str]] = []
    for item in ctx.copy.get("faq", []):
        answer = item.get("a", "")
        if item.get("id") == "blackouts":
            rules = [b.label for b in ctx.services.blackouts if b.active and b.label]
            answer = f"{item['a_intro']} {' '.join(rules)}" if rules else item.get("a_fallback", "")
        elif item.get("id") == "free":
            free = [s.name for s in ctx.services.services if s.kind == "ota" or s.is_free]
            answer = f"{item['a_intro']} {', '.join(free)}." if free else item.get("a_fallback", "")
        if answer:
            entries.append({"q": item["q"], "a": answer})
    return entries


def build(ctx: SiteContext, env) -> list[Page]:
    text = format_block(ctx.copy["hub"], season=ctx.season)
    faq = faq_entries(ctx)
    url = config.public_url()

    blocks = [seo.breadcrumbs(crumb_trail(ctx))]
    faq_block = seo.faq_page([(e["q"], e["a"]) for e in faq])
    if faq_block:
        blocks.append(faq_block)

    page_meta = {
        "title": seo.title(text["title"], season=ctx.season),
        "description": seo.description(text["description"], season=ctx.season),
        "canonical": url,
        "og_title": seo.title(text["title"], season=ctx.season),
        "og_description": seo.description(text["description"], season=ctx.season),
        "jsonld": seo.jsonld(blocks),
    }

    html = env.get_template("hub.html").render(
        page=page_meta,
        copy=ctx.copy,
        labels=ctx.labels(),
        text=text,
        teams=ctx.teams,
        national_partners=national_partners(ctx),
        faq=faq,
        tonight_path=config.site_path("tonight"),
        trail=crumb_trail(ctx),
    )
    return [Page(out_path="index.html", url=url, html=html, lastmod=ctx.today)]
