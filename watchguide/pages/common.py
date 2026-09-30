"""Bits shared by more than one page type."""

from __future__ import annotations

from datetime import date

from .. import config, worth
from ..context import SiteContext
from ..coverage import (IN_MARKET, OUT_OF_MARKET, carriers_for_game, channels_for_game, league_pass_blocked,
                        local_reaches, with_local_options)
from ..pairs import by_name, game_teams, pair_path
from ..render import usd
from ..sources.careers import match_key
from ..why import answer_parts, explain


def crumb_trail(ctx: SiteContext, leaf_name: str = "", leaf_url: str = "") -> list[tuple[str, str]]:
    labels = ctx.labels()
    trail = [(labels.get("breadcrumb_home", "How to watch"), config.public_url())]
    if leaf_name and leaf_url:
        trail.append((leaf_name, leaf_url))
    return trail


def updated_label(ctx: SiteContext) -> str:
    """Server-side fallback. JS replaces it with 'Updated N min ago'."""
    labels = ctx.labels()
    if not ctx.injuries_updated_at:
        return ""
    return f"{labels.get('updated_prefix', 'Updated')} {ctx.injuries_updated_at[:16].replace('T', ' ')} ET"


def has_affiliate_link(ctx: SiteContext) -> bool:
    return any(s.affiliate_url for s in ctx.services.services)


def empty_players_label(ctx: SiteContext) -> str:
    """Tell apart 'we have the report and this team has nobody on it' from
    'there is no report for this season yet'. Neither case is an error, and
    neither renders as a bare empty list."""
    labels = ctx.labels()
    if ctx.has_injury_data:
        return labels.get("no_players_listed", "Nobody listed.")
    return labels.get("no_injury_report", "No injury report yet.")


# --------------------------------------------------------------------------
# One game, laid out the same way everywhere
# --------------------------------------------------------------------------

def all_channels(ctx: SiteContext, game) -> list[dict[str, str]]:
    """Every channel for both fan bases: national first, then each side's
    local channels (home, then away). TBA only when there is nothing else.
    A local channel also carries the short name of the team it belongs to."""
    tba = ctx.labels().get("tba", "TBA")
    out: list[dict[str, str]] = []
    for tricode in (game.home_tricode, game.away_tricode):
        team = ctx.by_tricode.get(tricode)
        for channel in channels_for_game(game, tricode, ctx.local(team.slug) if team else None, tba):
            if channel["kind"] != "tba" and channel["name"] not in {c["name"] for c in out}:
                if channel["kind"] == "local" and team:
                    channel = {**channel, "team": team.short_name}
                out.append(channel)
    return out or [{"name": tba, "kind": "tba"}]


def _norm(code: str) -> str:
    return "".join(ch for ch in (code or "").lower() if ch.isalnum())


def price_text(ctx: SiteContext, service) -> str:
    """'$31.99/mo', or 'Free' for a confirmed price of 0."""
    labels = ctx.labels()
    if service.is_free:
        return labels.get("price_free", "Free")
    return f"{usd(service.price)}{labels.get('per_month', '/mo')}"


def cheapest_for(ctx: SiteContext, code: str):
    """The cheapest service with a confirmed price and a verified carries list
    that carries this national code; an antenna wins a tie at $0. None when
    no such service exists (NBCSN, Telemundo)."""
    candidates = [s for s in ctx.services.services
                  if s.carries_verified and s.has_price and _norm(code) in {_norm(c) for c in s.carries}]
    if not candidates:
        return None
    return min(candidates, key=lambda s: (s.price, s.kind != "ota", s.name))


def chips(ctx: SiteContext, channels: list[dict[str, str]], priced: bool = False) -> list[dict[str, str]]:
    """Channels as chips: `label` (the short name for a long local channel),
    `title` (the full name, only when it differs from the label) and, with
    priced=True, `how`: for a national channel the cheapest way to get it
    from data/services.json ("ESPN Unlimited · $31.99/mo", "NBC · free over
    the air"); for a local channel whose market it is."""
    text = ctx.copy.get("game", {})
    out = []
    for channel in channels:
        name = channel["name"]
        label = ctx.short_channel(name) if channel["kind"] == "local" else name
        how = ""
        if priced and channel["kind"] == "national":
            svc = cheapest_for(ctx, name)
            if svc is not None and svc.kind == "ota" and svc.is_free:
                how = text["chip_free_ota"]
            elif svc is not None and _norm(svc.name).startswith(_norm(name)):
                label, how = svc.name, price_text(ctx, svc)
            elif svc is not None:
                how = f"{svc.name} {price_text(ctx, svc)}"
        elif priced and channel["kind"] == "local" and channel.get("team"):
            how = text["chip_local"].format(team=channel["team"])
        # title carries a shortened local name in full; a national chip
        # relabelled with its service needs none.
        title = name if channel["kind"] == "local" and label != name else ""
        # An over-the-air station's confirmed antenna channel; never a cable
        # or satellite number, and none for streaming apps or regional networks.
        virtual = ctx.antenna_channel(name) if channel["kind"] == "local" else ""
        antenna = text["chip_antenna"].format(channel=virtual) if virtual else ""
        out.append({**channel, "label": label, "title": title, "how": how, "antenna": antenna})
    return out


def cable_note(ctx: SiteContext, *chip_lists: list[dict]) -> str:
    """The once-per-block line under chips that show an antenna channel:
    the same stations sit on other numbers on cable and satellite."""
    shown = any(c.get("antenna") for chips_ in chip_lists for c in chips_)
    return ctx.copy.get("game", {})["cable_numbers"] if shown else ""


def _names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def fan_answers(ctx: SiteContext, game) -> tuple[list[dict], list[str]]:
    """(fans, why): for the away and then the home fan base, the out-of-market
    and in-market answer, plus the reasons a fan base cannot watch it where
    it might expect to.

    Built from why.explain, the same sentences as the team pages' "Why can't
    I watch this game?". Its first line is the answer; any further line is a
    League Pass blackout, collected once into `why`. A regional line is added
    when a team's local TV does not reach a national game in its own market.
    `why` is empty when nothing blocks anyone."""
    fans, reasons = _fans_and_reasons(ctx, game)
    return fans, [r["line"] for r in reasons]


def _fans_and_reasons(ctx: SiteContext, game) -> tuple[list[dict], list[dict]]:
    text = ctx.copy.get("game", {})
    why_text = ctx.copy.get("why", {})
    fans: list[dict] = []
    reasons: list[dict] = []

    def add(kind: str, line: str, in_market: bool = False) -> None:
        if line and line not in {r["line"] for r in reasons}:
            reasons.append({"kind": kind, "line": line, "in_market": in_market})

    for tricode in (game.away_tricode, game.home_tricode):
        team = ctx.by_tricode.get(tricode)
        if team is None:
            continue
        local = ctx.local(team.slug)
        states = []
        for state, label in ((OUT_OF_MARKET, text["outside"]), (IN_MARKET, text["inside"])):
            sd = with_local_options(ctx.services, local, state)
            lines = explain(game, tricode, sd, local, state, why_text)
            states.append({"state": state, "label": label.format(team=team.short_name),
                           "answer": lines[0] if lines else "",
                           "moderate": answer_parts(game, tricode, sd, local, state)["moderate"]})
            # A League Pass reason is an in-market blackout when the rule it
            # gives (the first that applies, as in why.explain) is one.
            rules = league_pass_blocked(game, state, sd)
            in_market = bool(rules) and rules[0] in {r.label for r in sd.active_blackouts("in_market_local")}
            for line in lines[1:]:
                add("league_pass", line, in_market)
        # Regional: in its own market a fan base with counted local options
        # still cannot see a national game on them. Skipped when a local
        # option carries it anyway (an add-on bundled with the national
        # streamer), so the reason never contradicts the answer.
        if local and local.counts and game.is_national and not local_reaches(game, tricode):
            sd = with_local_options(ctx.services, local, IN_MARKET)
            carriers = carriers_for_game(game, tricode, sd, local, IN_MARKET)
            options = [s for s in sd.services if s.local_option]
            name = (local.local_broadcasters or local.primary_carriers or [""])[0]
            if options and name and not any(s.id in carriers for s in options):
                add("local", why_text["regional"].format(team=team.short_name,
                                                         channels=ctx.short_channel(name)))
        fans.append({"team": team, "label": text["fans"].format(team=team.short_name),
                     "states": states})
    return fans, reasons


def watch_view(ctx: SiteContext, game) -> dict:
    """Where to watch one game: the priced chips, the four fan-base answers
    (or one line for everyone when all four are the same) with standalone
    options first and live TV services grouped by service, one
    check-before-you-buy line when a live TV answer rests on a moderate
    lineup entry, and "Why ...?" only when some fan base is actually
    blocked."""
    fans, reasons = _fans_and_reasons(ctx, game)
    answers = {st["answer"] for fan in fans for st in fan["states"]}
    # One check-before-you-buy line under the answers when any of them names
    # a live TV service on a moderate-confidence lineup entry.
    check = ctx.copy.get("game", {})["live_tv_check"] if any(
        st["moderate"] for fan in fans for st in fan["states"]) else ""
    everyone = answers.pop() if len(answers) == 1 and fans else ""
    why = None
    if reasons:
        why_text = ctx.copy.get("why", {})
        kinds = {r["kind"] for r in reasons}
        if len(kinds) > 1:
            key = "summary_both"
        elif kinds == {"local"}:
            key = "summary_local"
        elif all(r["in_market"] for r in reasons):
            key = "summary_blackout"          # only the in-market League Pass blackout is in the way
        else:
            key = "summary_league_pass"
        why = {"summary": why_text[key], "lines": [r["line"] for r in reasons], "kinds": sorted(kinds)}
    game_chips = chips(ctx, all_channels(ctx, game), priced=True)
    return {
        "chips": game_chips,
        "cable_note": cable_note(ctx, game_chips),
        "fans": fans,
        "everyone": everyone,
        "check": check,
        "why": why,
    }


def out_block(ctx: SiteContext, game) -> dict:
    """Who's out, in the order the game block shows it.

    On game day: each side's listings, unless the safety net says the report
    has not arrived. Any other day: the game-day line."""
    labels = ctx.labels()
    text = ctx.copy.get("game", {})
    today = game.date_et == ctx.today
    message, sides = "", []
    if not today:
        message = labels.get("availability_on_game_day", "")
    elif ctx.injury_report_missing():
        message = text["injury_report_missing"]
    else:
        empty = empty_players_label(ctx)
        sides = [{"name": ctx.team_name(t), "players": ctx.players_for(t), "empty": empty}
                 for t in (game.away_tricode, game.home_tricode)]
    return {"is_today": today, "message": message, "sides": sides}


def face(ctx: SiteContext, name: str | None) -> dict | None:
    """The headshot (or silhouette) for a player the ranking line names."""
    if not name:
        return None
    rel = ctx.faces.get(match_key(name))
    return {"name": name, "src": rel or "assets/silhouette.svg", "is_face": bool(rel)}


def players_to_watch(ctx: SiteContext, game, stars: list | None) -> list[dict]:
    """The two players the ranking line names, away then home, each with a
    headshot and team. A side with nobody in uniform is left out."""
    out = []
    for tricode, name in zip((game.away_tricode, game.home_tricode), stars or [None, None]):
        pic = face(ctx, name)
        team = ctx.by_tricode.get(tricode)
        if pic:
            out.append({**pic, "team": team.short_name if team else tricode})
    return out


def countdown(ctx: SiteContext, game) -> dict:
    """The date chip: 'Tue, Oct 20' plus 'Tonight', 'Tomorrow' or 'In 21
    days' counted in Eastern dates from ctx.today. The page script redoes
    the count from the reader's clock, so a cached page never says Tonight
    a day late. Labels ride along as data attributes for it."""
    text = ctx.copy.get("game", {})
    evening = bool(game.tipoff_dt and game.tipoff_dt.hour >= 17)
    days = (date.fromisoformat(game.date_et) - date.fromisoformat(ctx.today)).days
    if days < 0:
        label = ""
    elif days == 0:
        label = text["countdown_tonight" if evening else "countdown_today"]
    elif days == 1:
        label = text["countdown_tomorrow"]
    else:
        label = text["countdown_days"].format(n=days)
    parsed = date.fromisoformat(game.date_et)
    return {
        "date": game.date_et,
        "day_label": f"{parsed:%a, %b} {parsed.day}",
        "label": label,
        "evening": evening,
        "labels": {"today": text["countdown_today"], "tonight": text["countdown_tonight"],
                   "tomorrow": text["countdown_tomorrow"], "days": text["countdown_days"]},
    }


def accent_style(ctx: SiteContext, game) -> str:
    """'--away:#..;--home:#..' for the card edge, or "" without colors."""
    away, home = ctx.team_accent(game.away_tricode), ctx.team_accent(game.home_tricode)
    return f"--away:{away};--home:{home}" if away and home else ""


def game_view(ctx: SiteContext, game, line: str | None = None) -> dict:
    """Everything the game block partial prints, in its fixed order:
    where to watch, then tip time, then players to watch with the ranking
    line, then who's out, then "Also worth knowing"."""
    teams = game_teams(game, ctx.by_tricode)
    away, home = (teams if teams else (ctx.by_tricode.get(game.away_tricode),
                                       ctx.by_tricode.get(game.home_tricode)))
    watch = watch_view(ctx, game)
    text = ctx.copy.get("game", {})
    pair_label = ""
    if teams:
        a, b = by_name(*teams)
        pair_label = text["pair_link"].format(a=a.short_name, b=b.short_name)
    row = ctx.ranking_row(game)
    return {
        "game": game,
        "away": away, "home": home,
        "away_name": ctx.team_name(game.away_tricode),
        "home_name": ctx.team_name(game.home_tricode),
        "away_accent": ctx.team_accent(game.away_tricode),
        "home_accent": ctx.team_accent(game.home_tricode),
        "accent_style": accent_style(ctx, game),
        "pair_path": pair_path(game, ctx.by_tricode),
        "pair_label": pair_label,
        "channels": all_channels(ctx, game),
        "watch": watch,
        "fans": watch["fans"],
        "why": watch["why"]["lines"] if watch["why"] else [],
        "countdown": countdown(ctx, game),
        "players": players_to_watch(ctx, game, row["stars"] if row else None),
        "out": out_block(ctx, game),
        "line": (row["line"] if row else "") if line is None else line,
        "worth": worth.lines(ctx, game),
    }
