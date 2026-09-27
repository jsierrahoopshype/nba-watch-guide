"""'Why can't I watch this game?' for each schedule row.

Every sentence is built from the coverage engine (carriers_for_game and
league_pass_blocked), the League Pass blackout rules in data/services.json and
the templates in data/copy.json under "why". No rule is worded here.
"""

from __future__ import annotations

from .coverage import carriers_for_game, league_pass_blocked
from .model import Game, LocalTV, ServiceData


def _names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def explain(game: Game, tricode: str, service_data: ServiceData, local: LocalTV | None,
            state: str, text: dict[str, str]) -> list[str]:
    """Plain sentences for one game in one market state.

    Only services whose carries list is verified are named, the same set the
    coverage maths uses. service_data should be the one build_state_coverage
    ran on for this state, so in-market it includes the team's local options.
    """
    listed = [s for s in service_data.services if s.carries_verified]
    carriers = carriers_for_game(game, tricode, service_data, local, state)
    carrying = [s.name for s in listed if s.id in carriers]

    lines: list[str] = []
    if carrying:
        lines.append(text["carried"].format(services=_names(carrying)))
    else:
        lines.append(text["none"])

    lp_id = service_data.league_pass_service_id
    lp = service_data.by_id(lp_id) if lp_id else None
    blackout_names: list[str] = []
    if lp is not None and lp.carries_verified and lp.id not in carriers:
        # One reason per game: league_pass_blocked lists the national rule
        # first, so a national game is explained as national and only a
        # local game in the reader's market gets the local rule.
        rules = league_pass_blocked(game, state, service_data)
        if rules:
            lines.append(text["blackout"].format(service=lp.name, rule=rules[0]))
            blackout_names.append(lp.name)

    others = [s.name for s in listed
              if s.id not in carriers and s.name not in blackout_names]
    if others:
        lines.append(text["not_carried"].format(services=_names(others)))
    return lines
