"""The NBA's public league schedule.

Verified against the live feed on 2026-09-24:

  https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json
  leagueSchedule.seasonYear == "2026-27", 174 game dates,
  1206 games with a regular-season game id (prefix 002).

The host rejects non-browser TLS fingerprints, so the request goes through
watchguide.sources.http, which uses curl_cffi with a Chrome profile.

gameDateTimeEst carries a Z suffix but holds an Eastern wall clock, so the
Eastern tipoff is worked out from gameDateTimeUTC with zoneinfo instead. That
keeps daylight saving correct across the season.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .. import config
from ..model import Game
from .http import FetchError, get

SCHEDULE_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
ET = ZoneInfo(config.EASTERN)


def fetch_raw() -> dict:
    return get(SCHEDULE_URL, expect_json=True)


def _codes(entries: list | None) -> list[str]:
    """Broadcaster abbreviations, in feed order, without blanks or repeats."""
    out: list[str] = []
    for entry in entries or []:
        code = (entry.get("broadcasterAbbreviation") or entry.get("broadcasterDisplay") or "").strip()
        if code and code not in out:
            out.append(code)
    return out


def _et_times(game: dict) -> tuple[str, str, str]:
    """(date_et, tipoff_et_iso, tipoff_utc_iso). Empty strings when unknown."""
    raw = game.get("gameDateTimeUTC") or ""
    if raw:
        try:
            utc = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
            eastern = utc.astimezone(ET)
            return eastern.date().isoformat(), eastern.isoformat(), utc.isoformat()
        except ValueError:
            pass
    # Fall back to the date-only field so a game never disappears.
    raw_date = (game.get("gameDateEst") or "")[:10]
    return raw_date, "", ""


def normalize(raw: dict, season: str = config.SEASON) -> list[Game]:
    """Regular-season games only, sorted by Eastern tipoff.

    Raises FetchError when the feed is not the season this build expects, so a
    bad run stops instead of publishing last season's schedule.
    """
    league = (raw or {}).get("leagueSchedule") or {}
    found = league.get("seasonYear")
    if found != season:
        raise FetchError(
            f"schedule feed is season {found!r}, this build expects {season!r}. "
            "Set WATCH_GUIDE_SEASON if the season has rolled over."
        )

    games: list[Game] = []
    for game_date in league.get("gameDates") or []:
        for g in game_date.get("games") or []:
            game_id = g.get("gameId") or ""
            if not game_id.startswith(config.REGULAR_SEASON_PREFIX):
                continue
            if (g.get("postponedStatus") or "").upper() in {"P", "POSTPONED"}:
                continue
            b = g.get("broadcasters") or {}
            date_et, tip_et, tip_utc = _et_times(g)
            if not date_et:
                continue
            games.append(Game(
                game_id=game_id,
                game_code=g.get("gameCode") or "",
                date_et=date_et,
                tipoff_et=tip_et,
                tipoff_utc=tip_utc,
                status_text=(g.get("gameStatusText") or "").strip(),
                home_tricode=(g.get("homeTeam") or {}).get("teamTricode") or "",
                away_tricode=(g.get("awayTeam") or {}).get("teamTricode") or "",
                national=_codes(b.get("nationalTvBroadcasters")),
                national_ott=_codes(b.get("nationalOttBroadcasters")),
                home_tv=_codes(b.get("homeTvBroadcasters")),
                away_tv=_codes(b.get("awayTvBroadcasters")),
                arena=(g.get("arenaName") or "").strip(),
                week=int(g.get("weekNumber") or 0),
            ))

    if not games:
        raise FetchError(f"schedule feed held no regular-season games for {season}")

    games.sort(key=lambda g: (g.date_et, g.tipoff_utc or "", g.game_id))
    return games


def fetch() -> list[Game]:
    return normalize(fetch_raw())
