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
from .ranking import STAKES, load_awards, load_weights, rank
from .ranking import mode as ranking_mode
from .model import (Game, LocalTV, ServiceData, Team, load_copy, load_local_tv,
                    load_services, load_teams)

ET = ZoneInfo(config.EASTERN)


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
    )
