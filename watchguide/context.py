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
    today: str
    generated_at: str

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


    def availability_is_stale(self) -> bool:
        """True when the feed's own newest entry is behind today and there are
        games on. The page then shows the notice without waiting for JS."""
        if not self.games_today():
            return False
        return not self.injuries_as_of or self.injuries_as_of < self.today


def load_context(
    games: list[Game],
    injuries: dict[str, list[dict[str, str]]] | None = None,
    injuries_updated_at: str = "",
    injuries_as_of: str = "",
    data_dir: Path | None = None,
    today: str | None = None,
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
        today=today or today_et(),
        generated_at=datetime.now(ET).isoformat(timespec="seconds"),
    )
