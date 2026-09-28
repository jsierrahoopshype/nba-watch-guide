"""Everything a page builder needs, loaded once per run.

A new page type (players, calendar feeds) takes this same object and returns
Page records, so nothing else in the generator has to change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import config
from .countries import CountryData, load_countries
from .ranking import STAKES, load_awards, load_weights, rank
from .ranking import mode as ranking_mode
from .model import (Game, LocalTV, ServiceData, Team, load_copy, load_local_tv,
                    load_services, load_teams)

ET = ZoneInfo(config.EASTERN)


def long_date(value: str) -> str:
    """'2026-10-20' becomes 'Tuesday, October 20'."""
    parsed = date.fromisoformat(value)
    return f"{parsed:%A, %B} {parsed.day}"


def today_et() -> str:
    return datetime.now(ET).date().isoformat()


@dataclass
class SiteContext:
    teams: list[Team]
    games: list[Game]
    services: ServiceData
    local_tv: dict[str, LocalTV]
    copy: dict[str, Any]
    injuries: dict[str, list[dict[str, str]]]   # tricode to player rows
    injuries_updated_at: str                    # when this build fetched the feed
    injuries_as_of: str                         # newest date the feed itself carries
    availability_degraded: str                  # why the feed was not trusted, or ""
    today: str
    generated_at: str
    star_rosters: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    star_weights: dict[str, Any] = field(default_factory=dict)
    recent_awards: list[dict[str, str]] = field(default_factory=list)
    countries: CountryData = field(default_factory=CountryData)
    nationalities: dict[str, str] = field(default_factory=dict)   # player to career-map nationality
    faces: dict[str, str] = field(default_factory=dict)           # match_key to assets/faces/<file>.webp

    by_tricode: dict[str, Team] = field(init=False)
    by_slug: dict[str, Team] = field(init=False)

    def __post_init__(self) -> None:
        self.by_tricode = {t.tricode: t for t in self.teams}
        self.by_slug = {t.slug: t for t in self.teams}

    # -- schedule helpers ---------------------------------------------------

    def team_games(self, tricode: str) -> list[Game]:
        return [g for g in self.games if g.involves(tricode)]

    def remaining_games(self, tricode: str) -> list[Game]:
        return [g for g in self.team_games(tricode) if g.date_et >= self.today]

    def games_today(self) -> list[Game]:
        return [g for g in self.games if g.date_et == self.today]

    def next_game(self, tricode: str) -> Game | None:
        upcoming = self.remaining_games(tricode)
        return upcoming[0] if upcoming else None

    def local(self, slug: str) -> LocalTV | None:
        return self.local_tv.get(slug)

    def tonight_ranked(self) -> list[dict[str, Any]]:
        """Today's games, best first. See watchguide/ranking.py."""
        return rank(self.games_today(), self.star_rosters, self.injuries, self.team_name,
                    self.copy.get("tonight", {}), self.star_weights, self.recent_awards,
                    all_games=self.games)

    def tonight_heading(self, rows: list[dict[str, Any]]) -> dict[str, str]:
        """Heading and basis line: star power only, or stakes once most of
        the day's games have them."""
        text = self.copy.get("tonight", {})
        if ranking_mode(rows, self.star_weights) == STAKES:
            return {"heading": text["rank_heading_stakes"], "basis": text["rank_basis_stakes"]}
        return {"heading": text["rank_heading"], "basis": text["rank_basis"]}

    def showcase_day(self) -> str:
        """Today when there are games today, otherwise the next date that has
        games, or "" once the schedule has run out."""
        if self.games_today():
            return self.today
        return min((g.date_et for g in self.games if g.date_et > self.today), default="")

    def showcase(self) -> dict[str, Any]:
        """The games the hub and the tonight page lead with, ranked, plus the
        heading and basis line to put around them.

        On a game day that is today's ranking with its usual heading. On an
        off day it is the next day with games, headed "Next games: <day>".
        The availability report is written for today's games, so the next
        day is ranked without it and nobody is marked Out."""
        day = self.showcase_day()
        if not day:
            return {"day": "", "is_today": False, "rows": [], "heading": "", "basis": ""}
        if day == self.today:
            rows = self.tonight_ranked()
            return {"day": day, "is_today": True, "rows": rows, **self.tonight_heading(rows)}
        text = self.copy.get("tonight", {})
        games = [g for g in self.games if g.date_et == day]
        rows = rank(games, self.star_rosters, {}, self.team_name, text, self.star_weights,
                    self.recent_awards, all_games=self.games)
        stakes = ranking_mode(rows, self.star_weights) == STAKES
        heading = text["next_heading"].format(day=long_date(day))
        return {"day": day, "is_today": False, "rows": rows, "heading": heading,
                "basis": text["next_basis_stakes" if stakes else "next_basis"]}

    def out_players(self, tricode: str) -> list[str]:
        """Names listed Out for a team in today's report."""
        return [p["player"] for p in self.players_for(tricode) if p.get("status") == "Out"]

    def players_for(self, tricode: str) -> list[dict[str, str]]:
        return self.injuries.get(tricode, [])

    def team_name(self, tricode: str) -> str:
        team = self.by_tricode.get(tricode)
        return team.full_name if team else tricode

    def labels(self) -> dict[str, str]:
        return self.copy.get("labels", {})

    @property
    def season(self) -> str:
        return self.copy.get("season_label", config.SEASON)

    @property
    def noindex(self) -> bool:
        """data/copy.json noindex. True keeps the site out of search results."""
        return bool(self.copy.get("noindex", False))


    def availability_is_stale(self) -> bool:
        """True when the page should carry the out-of-date notice from the
        server, without waiting for JavaScript."""
        if self.availability_degraded:
            return True
        if not self.games_today():
            return False
        return not self.injuries_as_of or self.injuries_as_of < self.today

    @property
    def has_injury_data(self) -> bool:
        return bool(self.injuries)


def load_context(
    games: list[Game],
    injuries: dict[str, list[dict[str, str]]] | None = None,
    injuries_updated_at: str = "",
    injuries_as_of: str = "",
    availability_degraded: str = "",
    data_dir: Path | None = None,
    today: str | None = None,
    star_rosters: dict[str, list[dict[str, Any]]] | None = None,
    nationalities: dict[str, str] | None = None,
) -> SiteContext:
    return SiteContext(
        teams=load_teams(data_dir),
        games=games,
        services=load_services(data_dir),
        local_tv=load_local_tv(data_dir),
        copy=load_copy(data_dir),
        injuries=injuries or {},
        injuries_updated_at=injuries_updated_at,
        injuries_as_of=injuries_as_of,
        availability_degraded=availability_degraded,
        today=today or today_et(),
        generated_at=datetime.now(ET).isoformat(timespec="seconds"),
        star_rosters=star_rosters or {},
        star_weights=load_weights(data_dir),
        recent_awards=load_awards(data_dir),
        countries=load_countries(data_dir),
        nationalities=nationalities or {},
    )
