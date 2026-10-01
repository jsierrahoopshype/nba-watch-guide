"""One page per country at /how-to-watch/<country-slug>, from data/countries.json.

Every time on the page is worked out at build time in the country's zone, so
the page carries no data-utc hooks and the script leaves it alone. The daily
build writes these pages; the 30-minute refresh does not.
"""

from __future__ import annotations

from datetime import date

from .. import config, seo, share
from ..context import SiteContext
from ..countries import (Country, clock, country_players, local_tip, price_text,
                         watchable_games, when_label)
from ..render import Page, date_label, safe_format
from .common import crumb_trail

LOW = "low"
MODERATE = "moderate"


def _fields(ctx: SiteContext, country: Country) -> dict[str, str]:
    text = ctx.copy["country"]
    return {
        "place": text.get("places", {}).get(country.slug, country.name),
        "country": country.name,
        "partner": country.partner.get("name", ""),
        "season": ctx.season,
    }


def _price(value, currency: str, period: str, verified: bool, low: bool, text: dict,
           labels: dict) -> dict[str, str]:
    """{amount, check}: the price and, for an unverified one, the check line.
    A null price, or any price on a low-confidence page, reads as not confirmed."""
    amount = "" if low else price_text(value, currency, period)
    if not amount:
        return {"amount": "", "none": labels.get("price_unconfirmed", "Price not confirmed"), "check": ""}
    return {"amount": amount, "none": "", "check": "" if verified else text["check_price"]}


def _options(country: Country, text: dict, labels: dict, low: bool) -> list[dict]:
    rows = []
    for opt in country.partner.get("options") or []:
        rows.append({
            "name": opt.get("name", ""),
            "note": opt.get("note", ""),
            **_price(opt.get("price"), country.currency, opt.get("period", ""),
                     bool(opt.get("price_verified")), low, text, labels),
        })
    return rows


def _prime(ctx: SiteContext, country: Country, text: dict, labels: dict, low: bool) -> dict:
    pv = country.prime_video
    return {
        "name": ctx.countries.prime_video_europe.get("name", "Prime Video"),
        "summary": ctx.countries.prime_video_europe.get("summary", ""),
        "commentary": pv.get("commentary", ""),
        "membership": {
            "name": text["prime_membership"],
            "note": pv.get("note", ""),
            **_price(pv.get("membership_price"), country.currency, pv.get("membership_period", ""),
                     bool(pv.get("price_verified")), low, text, labels),
        },
    }


def league_pass(ctx: SiteContext, country: Country, text: dict, fields: dict) -> dict:
    """The League Pass block. Prices come straight from the country's
    league_pass fields, so filling one in the data file is all it takes."""
    lp = country.league_pass
    verified = bool(lp.get("price_verified"))
    prices = [p for p in (price_text(lp.get("monthly_price"), country.currency, "month"),
                          price_text(lp.get("season_price"), country.currency, "season")) if p]
    return {
        "line": safe_format(text["league_pass_line"], **fields),
        "prices": prices,
        "unpublished": "" if prices else safe_format(text["league_pass_unpublished"], **fields),
        "check": text["check_price"] if prices and not verified else "",
        "rules_url": ctx.countries.league_pass_source_url,
        "rules_label": text["league_pass_rules_link"],
    }


def players_block(ctx: SiteContext, country: Country, text: dict) -> list[dict]:
    """Each player with his team and next game, in the country's zone,
    soonest game first. Ties (teammates, or two sides of one game) go by
    name, and players with no game scheduled come last."""
    rows = []
    for p in country_players(country, ctx.star_rosters, ctx.nationalities):
        nxt = ctx.next_game(p["tricode"])
        # A game with no tip-off time yet sorts after the timed games of its day.
        sort_key = (1, "", p["player"]) if nxt is None else \
            (0, nxt.tipoff_utc or f"{nxt.date_et}T99", p["player"])
        if nxt is None:
            next_label = text["players_no_game"]
        else:
            local = local_tip(nxt, country.zone)
            opponent = ctx.team_name(nxt.opponent_of(p["tricode"]))
            where = "vs " if nxt.is_home_for(p["tricode"]) else "at "
            when = when_label(local) if local else f"{date_label(nxt.date_et)}, {text['tba']}"
            next_label = f"{when}, {where}{opponent}"
        rows.append({"player": p["player"], "team": ctx.team_name(p["tricode"]),
                     "next": next_label, "sort": sort_key})
    rows.sort(key=lambda r: r["sort"])
    return rows


def watchable_block(ctx: SiteContext, country: Country) -> list[dict]:
    return [{
        "date": date_label(local.date().isoformat()),
        "matchup": f"{ctx.team_name(g.away_tricode)} at {ctx.team_name(g.home_tricode)}",
        "time": clock(local),
    } for g, local in watchable_games(ctx.games, country.zone, ctx.today)]


def europe_block(ctx: SiteContext, text: dict) -> list[dict]:
    """The Paris and Manchester games, until they have been played."""
    rows = []
    for g in ctx.countries.europe_games:
        if (g.get("date") or "") < ctx.today:
            continue
        rows.append({
            "date": f"{date_label(g['date'])}, {date.fromisoformat(g['date']).year}",
            "matchup": g.get("matchup", ""),
            "place": ", ".join(x for x in (g.get("arena", ""), g.get("city", "")) if x),
            "on": safe_format(text["europe_on"], broadcaster=g["broadcaster"]) if g.get("broadcaster") else "",
            "tip_note": g.get("tip_note", ""),
        })
    return rows


def sources(ctx: SiteContext, country: Country) -> list[str]:
    urls = [country.partner.get("source_url", "")]
    urls += [o.get("source_url", "") for o in country.partner.get("options") or []]
    urls += [country.prime_video.get("source_url", ""),
             ctx.countries.prime_video_europe.get("source_url", ""),
             ctx.countries.league_pass_source_url,
             country.league_pass.get("source_url", ""),
             ctx.countries.europe_games_source_url]
    out: list[str] = []
    for url in urls:
        if url and url not in out:
            out.append(url)
    return out


def build(ctx: SiteContext, env) -> list[Page]:
    text = ctx.copy.get("country", {})
    labels = ctx.labels()
    countries = ctx.countries.countries
    pages: list[Page] = []

    for country in countries:
        fields = _fields(ctx, country)
        low = country.confidence == LOW
        url = country.url
        # A country with no title or description of its own in copy.json gets
        # the shared template, so adding one to countries.json is enough.
        title = seo.title(safe_format(text.get("titles", {}).get(country.slug) or text["title"], **fields))
        desc = seo.description(safe_format(text.get("descriptions", {}).get(country.slug)
                                           or text["description"], **fields))
        h1 = safe_format(text["h1"], **fields)
        trail = crumb_trail(ctx, country.name, url)

        card = share.country_card(ctx, country)
        page_meta = {
            "title": title,
            "description": desc,
            "canonical": url,
            "og_title": title,
            "og_description": desc,
            "jsonld": seo.jsonld([seo.breadcrumbs(trail)]),
            **share.meta(card),
        }
        note = ""
        if low:
            note = safe_format(text["low_note"], **fields)
        elif country.confidence == MODERATE:
            note = safe_format(text["moderate_note"], **fields)

        html = env.get_template("country.html").render(
            page=page_meta,
            copy=ctx.copy,
            labels=labels,
            text={k: safe_format(v, **fields) if isinstance(v, str) else v for k, v in text.items()},
            h1=h1,
            country=country,
            answer_line=safe_format(text["answer_line"], **fields),
            partner={
                "name": country.partner.get("name", ""),
                "carries": country.partner.get("carries", ""),
                "commentary": country.partner.get("commentary", ""),
                "options": _options(country, text, labels, low),
            },
            prime=_prime(ctx, country, text, labels, low),
            confidence_note=note,
            league_pass=league_pass(ctx, country, text, fields),
            players=players_block(ctx, country, text),
            watchable=watchable_block(ctx, country),
            europe=europe_block(ctx, text),
            checked=ctx.countries.last_checked,
            sources=sources(ctx, country),
            others=[c for c in countries if c.slug != country.slug],
            hub_path=config.site_path(),
            flag=(f"assets/flags/{country.flag}.svg"
                  if country.flag and (config.ASSET_DIR / "flags" / f"{country.flag}.svg").is_file() else ""),
            trail=trail,
        )
        pages.append(Page(out_path=f"{country.slug}/index.html", url=url, html=html,
                          lastmod=ctx.today, meta={"country": country.slug, "share": card}))
    return pages
