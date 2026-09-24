"""Plain data objects shared by every page type.

Everything a page renders comes from one of these. New page types (player
pages, calendar feeds) read the same objects rather than the raw feed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import config


# --------------------------------------------------------------------------
# Teams
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Team:
    team_id: int
    tricode: str
    city: str
    nickname: str
    full_name: str
    slug: str
    short_name: str
    conference: str
    division: str

    @property
    def url(self) -> str:
        return config.public_url(self.slug)

    @property
    def path(self) -> str:
        return config.site_path(self.slug)


def load_teams(data_dir: Path | None = None) -> list[Team]:
    data_dir = data_dir or config.DATA_DIR
    raw = json.loads((data_dir / "teams.json").read_text(encoding="utf-8"))
    teams = [Team(**t) for t in raw["teams"]]
    if len(teams) != 30:
        raise ValueError(f"data/teams.json must hold 30 teams, found {len(teams)}")
    slugs = {t.slug for t in teams}
    if len(slugs) != 30:
        raise ValueError("data/teams.json has duplicate slugs")
    return teams


# --------------------------------------------------------------------------
# Games
# --------------------------------------------------------------------------

@dataclass
class Game:
    game_id: str
    game_code: str
    date_et: str            # YYYY-MM-DD in Eastern Time
    tipoff_et: str          # ISO 8601 with the Eastern offset, or "" when unknown
    tipoff_utc: str         # ISO 8601 in UTC, or "" when unknown
    status_text: str
    home_tricode: str
    away_tricode: str
    national: list[str] = field(default_factory=list)      # national TV codes
    national_ott: list[str] = field(default_factory=list)  # national streaming codes
    home_tv: list[str] = field(default_factory=list)       # home local TV codes
    away_tv: list[str] = field(default_factory=list)       # away local TV codes
    arena: str = ""
    week: int = 0

    @property
    def national_codes(self) -> list[str]:
        """Every code that makes this a national broadcast."""
        seen: list[str] = []
        for code in list(self.national) + list(self.national_ott):
            if code and code not in seen:
                seen.append(code)
        return seen

    @property
    def is_national(self) -> bool:
        return bool(self.national_codes)

    def opponent_of(self, tricode: str) -> str:
        return self.away_tricode if tricode == self.home_tricode else self.home_tricode

    def is_home_for(self, tricode: str) -> bool:
        return tricode == self.home_tricode

    def local_codes_for(self, tricode: str) -> list[str]:
        """Local broadcaster codes for the side that team is on."""
        return list(self.home_tv if self.is_home_for(tricode) else self.away_tv)

    def involves(self, tricode: str) -> bool:
        return tricode in (self.home_tricode, self.away_tricode)

    @property
    def date_obj(self) -> date:
        return date.fromisoformat(self.date_et)

    @property
    def tipoff_dt(self) -> datetime | None:
        return datetime.fromisoformat(self.tipoff_et) if self.tipoff_et else None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Game":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# --------------------------------------------------------------------------
# Services
# --------------------------------------------------------------------------

@dataclass
class Service:
    id: str
    name: str
    kind: str
    monthly_price_usd: float | None
    billing_note: str
    carries: list[str]
    carries_note: str
    signup_url: str
    affiliate_url: str
    source_url: str
    last_verified: str
    verified: bool
    # False means the carries list has not been checked yet: the service is
    # still listed with its price, but it counts for no games.
    carries_verified: bool = True
    carries_check: str = ""

    @property
    def has_price(self) -> bool:
        """A price only counts when it is a number and the entry is verified."""
        return self.verified and isinstance(self.monthly_price_usd, (int, float))

    @property
    def price(self) -> float:
        return float(self.monthly_price_usd) if self.has_price else 0.0

    @property
    def is_free(self) -> bool:
        """A confirmed price of 0 is a real price: free, not missing."""
        return self.has_price and self.price == 0

    @property
    def link(self) -> str:
        return self.affiliate_url or self.signup_url

    @property
    def is_affiliate(self) -> bool:
        return bool(self.affiliate_url)


@dataclass
class BlackoutRule:
    id: str
    applies_to: str
    active: bool
    label: str
    source_url: str
    last_verified: str
    verified: bool


@dataclass
class ServiceData:
    services: list[Service]
    blackouts: list[BlackoutRule]
    league_pass_service_id: str
    prices_checked: str = ""     # _meta.all_prices_checked, YYYY-MM-DD

    def by_id(self, sid: str) -> Service | None:
        for s in self.services:
            if s.id == sid:
                return s
        return None

    def active_blackouts(self, applies_to: str) -> list[BlackoutRule]:
        return [b for b in self.blackouts if b.active and b.applies_to == applies_to]


def load_services(data_dir: Path | None = None) -> ServiceData:
    data_dir = data_dir or config.DATA_DIR
    raw = json.loads((data_dir / "services.json").read_text(encoding="utf-8"))
    services = []
    for s in raw["services"]:
        services.append(Service(
            id=s["id"],
            name=s["name"],
            kind=s.get("kind", "streaming"),
            monthly_price_usd=s.get("monthly_price_usd"),
            billing_note=s.get("billing_note", ""),
            carries=list(s.get("carries") or []),
            carries_note=s.get("carries_note", ""),
            signup_url=s.get("signup_url", ""),
            affiliate_url=s.get("affiliate_url", ""),
            source_url=s.get("source_url", ""),
            last_verified=s.get("last_verified", ""),
            verified=bool(s.get("verified")),
            carries_verified=bool(s.get("carries_verified", True)),
            carries_check=s.get("carries_check", ""),
        ))
    rules = raw.get("rules") or {}
    blackouts = [
        BlackoutRule(
            id=b["id"],
            applies_to=b["applies_to"],
            active=bool(b.get("active", True)),
            label=b.get("label", ""),
            source_url=b.get("source_url", ""),
            last_verified=b.get("last_verified", ""),
            verified=bool(b.get("verified")),
        )
        for b in (rules.get("blackouts") or [])
    ]
    blackouts += _league_pass_blackouts(rules.get("league_pass_blackouts"))

    lp_id = rules.get("league_pass_service_id") or config.LEAGUE_PASS_SERVICE_ID
    if not any(s.id == lp_id for s in services):
        # League Pass has an empty carries list on purpose, so without this
        # link to the rules block it would cover nothing and quietly vanish.
        raise ValueError(f"data/services.json has no League Pass service with id {lp_id!r}")

    meta = raw.get("_meta") or {}
    return ServiceData(
        services=services,
        blackouts=blackouts,
        league_pass_service_id=lp_id,
        prices_checked=meta.get("all_prices_checked", ""),
    )


# Keys of rules.league_pass_blackouts that are blackout rules, and what each
# one applies to in the coverage maths.
_LP_BLACKOUT_KEYS = {"national": "national_broadcast", "local": "in_market_local"}


def _league_pass_blackouts(block: dict[str, Any] | None) -> list[BlackoutRule]:
    """Read the flat rules.league_pass_blackouts block into BlackoutRule rows."""
    if not block:
        return []
    source_url = block.get("source_url", "")
    last_verified = block.get("last_verified", "")
    return [
        BlackoutRule(id=f"league-pass-{key}", applies_to=applies_to, active=True,
                     label=block[key], source_url=source_url, last_verified=last_verified,
                     verified=bool(source_url and last_verified))
        for key, applies_to in _LP_BLACKOUT_KEYS.items()
        if block.get(key)
    ]


# --------------------------------------------------------------------------
# Local TV
# --------------------------------------------------------------------------

@dataclass
class LocalApp:
    service_id: str
    name: str
    monthly_price_usd: float | None
    signup_url: str = ""
    affiliate_url: str = ""


@dataclass
class LocalTV:
    slug: str
    team: str
    local_broadcasters: list[dict[str, str]]
    streaming_apps: list[LocalApp]
    in_market_note: str
    source_url: str
    last_verified: str
    verified: bool

    @property
    def codes(self) -> list[str]:
        return [b.get("code", "") for b in self.local_broadcasters if b.get("code")]

    @property
    def names(self) -> list[str]:
        return [b.get("name") or b.get("code", "") for b in self.local_broadcasters]


def load_local_tv(data_dir: Path | None = None) -> dict[str, LocalTV]:
    data_dir = data_dir or config.DATA_DIR
    raw = json.loads((data_dir / "local_tv.json").read_text(encoding="utf-8"))
    out: dict[str, LocalTV] = {}
    for t in raw["teams"]:
        apps = [
            LocalApp(
                service_id=a.get("service_id", ""),
                name=a.get("name", ""),
                monthly_price_usd=a.get("monthly_price_usd"),
                signup_url=a.get("signup_url", ""),
                affiliate_url=a.get("affiliate_url", ""),
            )
            for a in (t.get("streaming_apps") or [])
        ]
        out[t["slug"]] = LocalTV(
            slug=t["slug"],
            team=t.get("team", ""),
            local_broadcasters=list(t.get("local_broadcasters") or []),
            streaming_apps=apps,
            in_market_note=t.get("in_market_note", ""),
            source_url=t.get("source_url", ""),
            last_verified=t.get("last_verified", ""),
            verified=bool(t.get("verified")),
        )
    return out


# --------------------------------------------------------------------------
# Copy
# --------------------------------------------------------------------------

def load_copy(data_dir: Path | None = None) -> dict[str, Any]:
    data_dir = data_dir or config.DATA_DIR
    return json.loads((data_dir / "copy.json").read_text(encoding="utf-8"))
