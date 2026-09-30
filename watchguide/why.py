"""'Why can't I watch this game?' for each schedule row.

Every sentence is built from the coverage engine (carriers_for_game and
league_pass_blocked), the League Pass blackout rules in data/services.json and
the templates in data/copy.json under "why". No rule is worded here.
"""

from __future__ import annotations

from .coverage import carriers_for_game, league_pass_blocked, via_zip
from .model import Game, LocalTV, Service, ServiceData


def _names(names: list[str], last: str = "and") -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + f" {last} " + names[-1]


def live_tv_names(carrying: list[Service], service_data: ServiceData) -> list[str]:
    """The live TV services carrying a game, one name per service family in
    file order: the family name ("Fubo") when every plan of it carries the
    game, otherwise the plans that do ("Fubo Elite")."""
    names: list[str] = []
    seen: set[str] = set()
    for svc in carrying:
        family = svc.family or svc.name
        if family in seen:
            continue
        seen.add(family)
        plans = [s for s in service_data.services if s.kind == "live_tv" and (s.family or s.name) == family]
        mine = [s for s in carrying if (s.family or s.name) == family]
        names += [family] if len(mine) == len(plans) else [s.name for s in mine]
    return names


def _is_nba_tv_channel(svc: Service, lp_id: str) -> bool:
    """The NBA TV channel entry itself (not League Pass, which bundles it)."""
    return svc.id != lp_id and [c.lower() for c in svc.carries] == ["nba tv"]


def _standalone_names(game: Game, services: list[Service], service_data: ServiceData,
                      text: dict[str, str]) -> list[str]:
    """Standalone options as the answer names them. On an NBA TV game League
    Pass reads "NBA League Pass (includes NBA TV)" and the NBA TV channel is
    not listed beside it; when the NBA TV channel is the only standalone
    option it reads "NBA TV through cable or live TV", since it is a cable
    channel rather than an app of its own."""
    lp_id = service_data.league_pass_service_id
    on_nba_tv = any(c.lower() == "nba tv" for c in game.national_codes)
    lp_covers = on_nba_tv and any(s.id == lp_id for s in services)
    names: list[str] = []
    for svc in services:
        if svc.id == lp_id and lp_covers:
            names.append(text["league_pass_nba_tv"].format(service=svc.name))
        elif _is_nba_tv_channel(svc, lp_id):
            if lp_covers:
                continue
            names.append(text["nba_tv_channel"] if len(services) == 1 else svc.name)
        else:
            names.append(svc.name)
    return names


def answer_parts(game: Game, tricode: str, service_data: ServiceData, local: LocalTV | None,
                 state: str) -> dict:
    """Who carries one game in one market state, split the way the answer
    reads: standalone options, live TV services, and whether any live TV
    service is named only through a ZIP-dependent local ABC or NBC, or on
    a moderate-confidence lineup entry."""
    listed = [s for s in service_data.services if s.carries_verified]
    carriers = carriers_for_game(game, tricode, service_data, local, state)
    carrying = [s for s in listed if s.id in carriers]
    live = [s for s in carrying if s.kind == "live_tv"]
    codes = {c.lower() for c in game.national_codes}
    return {
        "carriers": carriers,
        "standalone_services": [s for s in carrying if s.kind != "live_tv"],
        "standalone": [s.name for s in carrying if s.kind != "live_tv"],
        "live": live_tv_names(live, service_data),
        "zip": any(via_zip(s, game) for s in live),
        "moderate": any(codes & {c.lower() for c in s.moderate_codes} for s in live),
    }


def explain(game: Game, tricode: str, service_data: ServiceData, local: LocalTV | None,
            state: str, text: dict[str, str]) -> list[str]:
    """Plain sentences for one game in one market state: who carries it, and
    League Pass's blackout reason when it does not. At most two lines.

    Only services whose carries list is verified are named, the same set the
    coverage maths uses. service_data should be the one build_state_coverage
    ran on for this state, so in-market it includes the team's local options.
    """
    parts = answer_parts(game, tricode, service_data, local, state)
    carriers = parts["carriers"]
    standalone = _standalone_names(game, parts["standalone_services"], service_data, text)
    live = _names(parts["live"], "or")

    lines: list[str] = []
    # Standalone options first, then live TV grouped by service.
    # Every list is of alternatives, so it joins with "or".
    if standalone and live:
        answer = text["carried_live"].format(services=_names(standalone, "or"), live=live)
    elif live:
        answer = text["live_only"].format(live=live)
    elif standalone:
        answer = text["carried"].format(services=_names(standalone, "or"))
    else:
        answer = text["none"]
    if parts["zip"]:
        answer += " " + text["zip_locals"]
    lines.append(answer)

    lp_id = service_data.league_pass_service_id
    lp = service_data.by_id(lp_id) if lp_id else None
    if lp is not None and lp.carries_verified and lp.id not in carriers:
        # One reason per game: league_pass_blocked lists the national rule
        # first, so a national game is explained as national and only a
        # local game in the reader's market gets the local rule.
        rules = league_pass_blocked(game, state, service_data)
        if rules:
            lines.append(text["blackout"].format(service=lp.name, rule=rules[0]))
    return lines
