"""The hub page at /how-to-watch."""

from __future__ import annotations

from collections import Counter
from datetime import date

from .. import config, seo
from ..context import SiteContext
from ..coverage import channels_for_game
from ..render import Page, date_label, et_label, format_block, usd
from ..sources.careers import match_key
from .common import crumb_trail


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


def _plural(n: int, one: str, many: str) -> str:
    return (one if n == 1 else many).format(n=f"{n:,}")


def stat_cards(ctx: SiteContext) -> list[dict]:
    """The dashboard strip. Every number is worked out from the data files
    and the schedule on each build."""
    text = ctx.copy["hub"]["stats"]
    cards = []

    opener = min((g.date_et for g in ctx.games), default="")
    today_games = ctx.games_today()
    if today_games:
        first = min((g for g in today_games if g.tipoff_et), key=lambda g: g.tipoff_utc, default=None)
        cards.append({"label": text["tonight_label"],
                      "num": _plural(len(today_games), text["games_one"], text["games_many"]),
                      "sub": text["first_tip"].format(time=et_label(first)) if first else "",
                      "href": config.site_path("tonight"), "id": "tonight"})
    elif opener and ctx.today < opener:
        days = (date.fromisoformat(opener) - date.fromisoformat(ctx.today)).days
        cards.append({"label": text["opener_label"],
                      "num": _plural(days, text["days_one"], text["days_many"]),
                      "sub": date_label(opener), "href": "", "id": "opener"})
    elif (nxt := ctx.showcase_day()):
        count = sum(1 for g in ctx.games if g.date_et == nxt)
        cards.append({"label": text["next_label"], "num": date_label(nxt), "text": True,
                      "sub": _plural(count, text["games_one"], text["games_many"]),
                      "href": config.site_path("tonight"), "id": "next"})
    else:
        cards.append({"label": text["season_label"], "num": text["season_over"], "text": True,
                      "sub": "", "href": "", "id": "season"})

    national = sum(1 for g in ctx.games if g.national_codes)
    cards.append({"label": text["national_label"], "num": f"{national:,}",
                  "sub": text["national_sub"].format(total=f"{len(ctx.games):,}") if national
                  else text["national_none"], "href": "#national", "id": "national"})
    ota = len(free_ota_teams(ctx))
    cards.append({"label": text["ota_label"], "num": str(ota), "sub": text["ota_sub"],
                  "href": "#teams", "id": "ota"})
    countries = len(ctx.countries.countries)
    cards.append({"label": text["countries_label"], "num": str(countries), "sub": text["countries_sub"],
                  "href": "#countries", "id": "countries"})
    for card in cards:
        card.setdefault("text", False)       # True: the value is words, not a number
    return cards


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


def _face(ctx: SiteContext, name: str | None) -> dict | None:
    """The headshot (or silhouette) for a player the ranking line names."""
    if not name:
        return None
    rel = ctx.faces.get(match_key(name))
    return {"name": name, "src": rel or "assets/silhouette.svg", "is_face": bool(rel)}


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
    tba = ctx.labels().get("tba", "TBA")
    rows = []
    for r in show["rows"]:
        game = r["game"]
        home, away = ctx.by_tricode.get(game.home_tricode), ctx.by_tricode.get(game.away_tricode)
        out = []
        if show["is_today"]:
            out = [{"team": ctx.team_name(t), "players": ctx.out_players(t)}
                   for t in (game.away_tricode, game.home_tricode)]
            out = [side for side in out if side["players"]]
        rows.append({
            "game": game,
            "away": away, "home": home,
            "away_name": r["away_name"], "home_name": r["home_name"],
            "channels": channels_for_game(game, game.home_tricode,
                                          ctx.local(home.slug) if home else None, tba),
            "line": r["line_core"],
            "out": out,
            "out_count": sum(len(side["players"]) for side in out),
            "top_pick": r["rank"] <= TOP_PICKS,
            "faces": [_face(ctx, n) for n in r.get("stars", [None, None])],
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
        ota_teams=free_ota_teams(ctx),
        showcase=showcase_rows(ctx),
        stats=stat_cards(ctx),
        team_cards=team_cards(ctx),
        country_cards=country_cards(ctx),
        national_footnote=national_footnote(ctx),
        tonight_text=ctx.copy.get("tonight", {}),
        faq=faq,
        tonight_path=config.site_path("tonight"),
        countries=ctx.countries.countries,
        trail=crumb_trail(ctx),
    )
    return [Page(out_path="index.html", url=url, html=html, lastmod=ctx.today)]
