"""The hub page at /how-to-watch."""

from __future__ import annotations

from collections import Counter

from .. import config, seo, share, worth
from ..context import SiteContext
from ..pairs import pair_path
from ..render import Page, format_block, usd
from .common import accent_style, crumb_trail, face, players_to_watch, watch_view


def national_partners(ctx: SiteContext) -> list[dict]:
    """Broadcaster codes the schedule feed lists on national games, with counts.

    Nothing is added to this list. When the league has not published national
    assignments yet it comes back empty and the page says so. Codes listed in
    copy.json hub.national_footnote_codes (simulcasts such as NBCSN and
    Telemundo) are left out here and explained in a footnote instead.
    """
    skip = set(ctx.copy["hub"].get("national_footnote_codes", []))
    counts: Counter[str] = Counter()
    for game in ctx.games:
        for code in game.national_codes:
            counts[code] += 1
    return [{"code": code, "games": n} for code, n in counts.most_common() if code not in skip]


def national_footnote(ctx: SiteContext) -> str:
    """The simulcast footnote, only when one of its codes is in the feed."""
    hub = ctx.copy["hub"]
    codes = set(hub.get("national_footnote_codes", []))
    in_feed = any(code in codes for g in ctx.games for code in g.national_codes)
    return hub.get("national_footnote", "") if in_feed else ""


def team_summary(ctx: SiteContext, team) -> dict[str, str]:
    """One line on how to watch a team locally, from data/local_tv.json and
    the shared services in it, under the same confidence rules as the team
    pages: low and unknown are never stated as fact, and a moderate claim
    carries a check-before-you-buy note."""
    labels = ctx.copy["hub"]["team_summary"]
    local = ctx.local(team.slug)
    if local is None or local.confidence not in ("high", "moderate", "low"):
        return {"text": labels["missing"], "note": "", "kind": "missing"}
    if local.confidence == "low":
        return {"text": labels["unconfirmed"], "note": "", "kind": "unconfirmed"}
    stations = local.local_broadcasters
    check = labels["check"] if local.confidence == "moderate" else ""
    if local.exclude_from_us_maths:
        return {"text": labels["on"].format(station=" and ".join(stations)), "note": "", "kind": "on"}
    if local.ota.status == "all" and stations:
        return {"text": labels["free_ota"].format(station=stations[0]), "note": check, "kind": "ota"}
    priced = [o for o in local.streaming if o.price_verified and o.monthly_price_usd is not None
              and not o.requires_service]
    if priced:
        best = min(priced, key=lambda o: o.monthly_price_usd)
        line = labels["free_stream"].format(name=best.name) if best.monthly_price_usd == 0 else \
            labels["price"].format(name=best.name, price=usd(best.monthly_price_usd))
        return {"text": line, "note": check, "kind": "price"}
    if stations:
        return {"text": labels["on"].format(station=stations[0]), "note": "", "kind": "on"}
    return {"text": labels["missing"], "note": "", "kind": "missing"}


def team_cards(ctx: SiteContext) -> list[dict]:
    return [{"team": t, "summary": team_summary(ctx, t)} for t in ctx.teams]


def country_cards(ctx: SiteContext) -> list[dict]:
    """Each country with its flag file (when there is one) and TV partner."""
    cards = []
    for c in ctx.countries.countries:
        flag = f"assets/flags/{c.flag}.svg" if c.flag else ""
        if flag and not (config.ASSET_DIR / flag[len("assets/"):]).is_file():
            flag = ""
        cards.append({"country": c, "flag": flag, "partner": c.partner.get("name", "")})
    return cards


def free_ota_teams(ctx: SiteContext) -> list:
    """Teams whose local games are all free over the air, from data/local_tv.json."""
    return [t for t in ctx.teams if (local := ctx.local(t.slug)) and local.ota.status == "all"]


TOP_PICKS = 3     # the highest-ranked games get the "Top pick" badge on the hub


def showcase_rows(ctx: SiteContext) -> dict:
    """Today's games (or the next day's, on an off day) in tip-off order,
    earliest first, one compact row each: tip time, both teams, channels,
    the ranking line and, on a game day, the players listed Out for a
    collapsed detail. The TOP_PICKS highest-ranked games carry a badge; the
    tonight page keeps the full ranking order."""
    show = ctx.showcase()
    rows = []
    for r in show["rows"]:
        game = r["game"]
        home, away = ctx.by_tricode.get(game.home_tricode), ctx.by_tricode.get(game.away_tricode)
        out = []
        if show["is_today"]:
            out = [{"team": ctx.team_name(t), "players": ctx.out_players(t)}
                   for t in (game.away_tricode, game.home_tricode)]
            out = [side for side in out if side["players"]]
        watch = watch_view(ctx, game)
        rows.append({
            "game": game,
            "away": away, "home": home,
            "away_name": r["away_name"], "home_name": r["home_name"],
            "away_accent": ctx.team_accent(game.away_tricode),
            "home_accent": ctx.team_accent(game.home_tricode),
            "accent_style": accent_style(ctx, game),
            # Both fan bases' channels with the way to get each, the fan-base
            # answer (one line when it is the same everywhere) and "Why ...?"
            # only when someone is blocked: the game block's watch part.
            "watch": watch,
            "pair_path": pair_path(game, ctx.by_tricode),
            "worth": worth.lines(ctx, game),
            # Only the safety net's message: on a normal day the Out list is
            # the collapsed detail, and a day with nobody out shows nothing.
            "out_message": (ctx.copy["game"]["injury_report_missing"]
                            if show["is_today"] and ctx.injury_report_missing() else ""),
            "line": r["line_core"],
            "out": out,
            "out_count": sum(len(side["players"]) for side in out),
            "top_pick": r["rank"] <= TOP_PICKS,
            "players": players_to_watch(ctx, game, r.get("stars")),
        })
    rows.sort(key=lambda row: (row["game"].tipoff_utc or "~", row["game"].game_id))
    return {**show, "rows": rows}


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

    card = share.hub_card(ctx)
    page_meta = {
        "title": seo.title(text["title"], season=ctx.season),
        "description": seo.description(text["description"], season=ctx.season),
        "canonical": url,
        "og_title": seo.title(text["title"], season=ctx.season),
        "og_description": seo.description(text["description"], season=ctx.season),
        "jsonld": seo.jsonld(blocks),
        **share.meta(card),
    }

    html = env.get_template("hub.html").render(
        page=page_meta,
        copy=ctx.copy,
        labels=ctx.labels(),
        text=text,
        teams=ctx.teams,
        national_partners=national_partners(ctx),
        ota_teams=free_ota_teams(ctx),
        showcase=showcase_rows(ctx),
        team_cards=team_cards(ctx),
        country_cards=country_cards(ctx),
        national_footnote=national_footnote(ctx),
        tonight_text=ctx.copy.get("tonight", {}),
        game_text=ctx.copy.get("game", {}),
        faq=faq,
        tonight_path=config.site_path("tonight"),
        countries=ctx.countries.countries,
        trail=crumb_trail(ctx),
    )
    return [Page(out_path="index.html", url=url, html=html, lastmod=ctx.today, meta={"share": card})]
