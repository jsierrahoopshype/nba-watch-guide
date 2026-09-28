"""Per-country viewing data for the European pages, from data/countries.json.

Everything a country page states comes from that file, the schedule and the
career-map rosters. Tip-off times are worked out here, at build time, in the
country's own zone, so the page needs no script to show them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import config
from .model import Game
from .render import date_label
from .sources.careers import match_key

CURRENCY_SYMBOLS = {"GBP": "£", "EUR": "€", "USD": "$"}
PERIODS = {"month": "a month", "day": "a day", "year": "a year", "season": "a season"}

# The watchable-hour window: this many days from the build date, tip-offs
# from WATCHABLE_FROM_HOUR:00 to 23:59 local time.
WATCHABLE_DAYS = 14
WATCHABLE_FROM_HOUR = 12


@dataclass
class Country:
    slug: str
    name: str
    timezone: str
    currency: str
    nationality_aliases: list[str]
    confidence: str
    partner: dict[str, Any]
    prime_video: dict[str, Any]
    free_to_air: str
    notes: str
    league_pass: dict[str, Any]
    player_overrides: list[str]

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def url(self) -> str:
        return config.public_url(self.slug)

    @property
    def path(self) -> str:
        return config.site_path(self.slug)


@dataclass
class CountryData:
    countries: list[Country] = field(default_factory=list)
    prime_video_europe: dict[str, Any] = field(default_factory=dict)
    europe_games: list[dict[str, Any]] = field(default_factory=list)
    europe_games_source_url: str = ""
    league_pass_source_url: str = ""
    last_checked: str = ""


def load_countries(data_dir: Path | None = None) -> CountryData:
    """An empty CountryData when the file is absent, so a trimmed test data
    directory still builds the US pages."""
    path = (data_dir or config.DATA_DIR) / "countries.json"
    if not path.exists():
        return CountryData()
    raw = json.loads(path.read_text(encoding="utf-8"))
    meta = raw.get("_meta") or {}
    countries = []
    for slug, c in (raw.get("countries") or {}).items():
        countries.append(Country(
            slug=c.get("slug") or slug,
            name=c["name"],
            timezone=c["timezone"],
            currency=c.get("currency", ""),
            nationality_aliases=list(c.get("nationality_aliases") or []),
            confidence=c.get("confidence", "unknown"),
            partner=c.get("partner") or {},
            prime_video=c.get("prime_video") or {},
            free_to_air=c.get("free_to_air", ""),
            notes=c.get("notes", ""),
            league_pass=c.get("league_pass") or {},
            player_overrides=list(c.get("player_overrides") or []),
        ))
    return CountryData(
        countries=countries,
        prime_video_europe=raw.get("prime_video_europe") or {},
        europe_games=list(raw.get("europe_games") or []),
        europe_games_source_url=raw.get("europe_games_source_url", ""),
        league_pass_source_url=meta.get("league_pass_source_url", ""),
        last_checked=meta.get("last_checked", ""),
    )


# --------------------------------------------------------------------------
# Prices
# --------------------------------------------------------------------------

def money(value: Any, currency: str) -> str:
    """'£34.99', '€15'. '' when the value is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    symbol = CURRENCY_SYMBOLS.get(currency, f"{currency} ")
    amount = f"{value:,.0f}" if float(value) == int(value) else f"{value:,.2f}"
    return f"{symbol}{amount}"


def price_text(value: Any, currency: str, period: str = "") -> str:
    """'£34.99 a month', or '' for a missing price."""
    amount = money(value, currency)
    if not amount:
        return ""
    per = PERIODS.get(period or "", "")
    return f"{amount} {per}" if per else amount


# --------------------------------------------------------------------------
# Players
# --------------------------------------------------------------------------

def nationality_matches(nationality: str, aliases: list[str]) -> bool:
    """True when any part of a nationality such as 'American / Italian'
    is one of the aliases, ignoring case."""
    wanted = {a.strip().casefold() for a in aliases if a.strip()}
    parts = re.split(r"[/,]", nationality or "")
    return any(p.strip().casefold() in wanted for p in parts)


def country_players(country: Country, rosters: dict[str, list[dict[str, Any]]],
                    nationalities: dict[str, str]) -> list[dict[str, Any]]:
    """[{player, tricode, all_star}] for the active players on an NBA roster
    whose nationality matches, plus the country's overrides, most All-Star
    selections first. An override names a player as the career map does and
    goes through the same name matching as the rest of the guide."""
    overrides = {match_key(n) for n in country.player_overrides if n}
    found: dict[str, dict[str, Any]] = {}
    for tricode, players in rosters.items():
        for p in players:
            name = p.get("player", "")
            key = match_key(name)
            if key in found:
                continue
            if key in overrides or nationality_matches(nationalities.get(name, ""),
                                                       country.nationality_aliases):
                found[key] = {"player": name, "tricode": tricode,
                              "all_star": int(p.get("all_star") or 0)}
    return sorted(found.values(), key=lambda p: (-p["all_star"], p["player"]))


# --------------------------------------------------------------------------
# Local times
# --------------------------------------------------------------------------

def local_tip(game: Game, zone: ZoneInfo) -> datetime | None:
    if not game.tipoff_utc:
        return None
    return datetime.fromisoformat(game.tipoff_utc.replace("Z", "+00:00")).astimezone(zone)


def clock(local: datetime) -> str:
    """'20:00 CET'. The zone name tells the reader which side of the clock
    change the game falls on."""
    return f"{local:%H:%M} {local.tzname()}"


def when_label(local: datetime) -> str:
    """'Sun Oct 25, 20:00 CET', dated in the local zone."""
    return f"{date_label(local.date().isoformat())}, {clock(local)}"


def watchable_games(games: list[Game], zone: ZoneInfo, start: str,
                    days: int = WATCHABLE_DAYS, from_hour: int = WATCHABLE_FROM_HOUR
                    ) -> list[tuple[Game, datetime]]:
    """Games whose local date falls in the `days` from `start` (inclusive)
    and that tip off from from_hour:00 to 23:59 local time, in tip-off order.
    Games with no tip-off time yet are left out."""
    first = date.fromisoformat(start)
    last = first + timedelta(days=days - 1)
    rows = []
    for game in games:
        local = local_tip(game, zone)
        if local is None:
            continue
        if first <= local.date() <= last and local.hour >= from_hour:
            rows.append((game, local))
    rows.sort(key=lambda r: (r[1], r[0].game_id))
    return rows
