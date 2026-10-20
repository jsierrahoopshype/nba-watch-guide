"""Everything a page builder needs, loaded once per run.

A new page type (players, calendar feeds) takes this same object and returns
Page records, so nothing else in the generator has to change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import colors, config
from .countries import CountryData, load_countries
from .ranking import STAKES, load_awards, load_weights, rank
from .ranking import mode as ranking_mode
from .model import (Game, LocalTV, ServiceData, Team, load_arenas, load_copy, load_local_tv,
                    load_services, load_team_colors, load_teams)

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
    team_colors: dict[str, str] = field(default_factory=dict)     # tricode to '#RRGGBB', data/team_colors.json
    arenas: dict[str, dict[str, str]] = field(default_factory=dict)  # feed arena name to address, data/arenas.json
    # "Also worth knowing" sources, set by the build (see build.load_worth):
    # tonight's referee crews, the referee slugs that have a page, and the
    # career matchup pages (sources/matchups.Matchups).
    crews: dict[str, Any] = field(default_factory=dict)
    referee_slugs: set[str] = field(default_factory=set)
    matchups: Any = None
    # Pair pages to render in full; None means all. The 30-minute refresh
    # sets it to today's pairs, and the rest come back as placeholders
    # (see pages/pair.py) so the manifest, sitemap and lastmod still see them.
    render_pairs: set[str] | None = None

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

    def ranking_line(self, game: Game) -> str:
        """The ranking line for one game, the same one tonight's list shows:
        named players, records once stakes are on. Availability only counts
        on game day, as everywhere else."""
        row = self.ranking_row(game)
        return row["line"] if row else ""

    def ranking_row(self, game: Game) -> dict[str, Any] | None:
        """rank() for one game: its line and the two players it names
        (row["stars"], away then home, None for a side with nobody)."""
        injuries = self.injuries if game.date_et == self.today else {}
        rows = rank([game], self.star_rosters, injuries, self.team_name,
                    self.copy.get("tonight", {}), self.star_weights, self.recent_awards,
                    all_games=self.games)
        return rows[0] if rows else None

    # -- display helpers ----------------------------------------------------

    def short_channel(self, name: str) -> str:
        """A channel chip's name: the short name data/local_tv.json gives
        any team for it, otherwise the name itself."""
        for local in self.local_tv.values():
            if name in local.short_names:
                return local.short_names[name]
        return name

    def channel_names(self, name: str, kind: str, slug: str = "", chip: bool = False,
                      short: bool = True) -> list[str]:
        """A channel as fans read it, never as a feed code. The schedule feed
        codes a local channel like "WSOC/DAZN-CHA": each part takes, in order,
        the first name of the team's data/local_tv.json link entry that lists
        it, its confirmed name in the team's code_names, or the plain fallback
        in copy.json channels (the team's streaming app for a code_names entry
        of kind stream or team_stream, otherwise the team's local broadcast). A part that is
        already one of the team's recorded names stays as it is. A national
        code takes its confirmed name in data/services.json code_names.
        chip=True gives the chip forms: names as recorded, owner note kept,
        shortened by data/local_tv.json short_names unless short=False, and
        the fallback without "the"."""
        text = self.copy.get("channels", {})
        prefix = "chip_" if chip else ""

        def plain(value: str) -> str:
            # A chip keeps its short name (or the full one, owner note and
            # all); a sentence drops the owner note ("WANF (Gray)").
            if chip:
                return self.short_channel(value) if short else value
            return re.sub(r"\s*\([^)]*\)", "", value)

        if kind == "national":
            entry = self.services.code_names.get(name)
            if entry is None:
                return [name]           # a network's own name: ESPN, NBC, Peacock
            if entry.get("status") == "confirmed" and entry.get("name"):
                return [entry["name"]]
            return [text[prefix + "fallback_national"]]
        if kind != "local":
            return [name]
        local = self.local(slug)
        team = next((t.short_name for t in self.teams if t.slug == slug), "")
        if local is None:
            return [plain(name)]
        known = set(local.local_broadcasters) | {o.name for o in local.streaming}
        out: list[str] = []
        # A recorded name may hold a "/" itself ("Arizona's Family (3TV/KTVK)").
        whole = name in known or any(name in (e.get("names") or []) for e in local.links)
        for part in [name] if whole else name.split("/"):
            entry = next((e for e in local.links if part in (e.get("names") or [])), None)
            code = local.code_names.get(part)
            if part in known:
                found = plain(part)
            elif entry is not None:
                found = plain(entry["names"][0])
            elif code and code.get("status") == "confirmed" and code.get("name"):
                found = plain(code["name"])
            else:
                which = "fallback_app" if (code or {}).get("kind") in ("stream", "team_stream") else "fallback_tv"
                found = text[prefix + which].format(team=team)
            if found and found not in out:
                out.append(found)
        return out

    def antenna_channel(self, name: str) -> str:
        """A local channel's confirmed antenna (virtual) channel, "32.1", from
        whichever team's data/local_tv.json entry names it; "" otherwise.
        Never a cable or satellite number."""
        for local in self.local_tv.values():
            found = local.antenna_channel(name)
            if found:
                return found
        return ""

    def team_accent(self, tricode: str) -> str:
        """The team's color as a ring or edge color, darkened if needed to
        keep 3:1 against the card (see watchguide/colors.py), or ""."""
        value = self.team_colors.get(tricode)
        return colors.accent(value) if value else ""

    def injury_report_missing(self) -> bool:
        """The safety net for a game day whose report has not arrived.

        True from INJURY_GUARD_START_HOUR ET to midnight on a day with games
        when none of the day's teams has a single listing and the feed's
        newest date is not today. Pages then say the report is not available
        yet instead of implying nobody is hurt, and the build summary warns."""
        today = self.games_today()
        if not today:
            return False
        try:
            hour = datetime.fromisoformat(self.generated_at).astimezone(ET).hour
        except ValueError:
            return False
        if hour < config.INJURY_GUARD_START_HOUR:
            return False
        playing = {g.home_tricode for g in today} | {g.away_tricode for g in today}
        if any(self.players_for(t) for t in playing):
            return False
        return (self.injuries_as_of or "")[:10] != self.today

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
    now: str | None = None,
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
        # `now` is for tests: an ISO timestamp standing in for the clock.
        generated_at=now or datetime.now(ET).isoformat(timespec="seconds"),
        star_rosters=star_rosters or {},
        star_weights=load_weights(data_dir),
        recent_awards=load_awards(data_dir),
        countries=load_countries(data_dir),
        nationalities=nationalities or {},
        team_colors=load_team_colors(data_dir),
        arenas=load_arenas(data_dir),
    )
