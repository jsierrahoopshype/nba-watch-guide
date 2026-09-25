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
    # "moderate" means the carries list is trusted for the maths but the page
    # should tell the reader to check; carries_confidence_note is that line.
    carries_verified_confidence: str = ""
    carries_confidence_note: str = ""
    # In-market local options (built from data/local_tv.json, never listed in
    # services.json). They cover the team's games with no national broadcast.
    local_option: bool = False
    # An add-on that needs another service: monthly_price_usd is the real cost
    # (own price plus the required ones), own_price_usd is the add-on alone.
    requires: list["Service"] = field(default_factory=list)
    own_price_usd: float | None = None

    @property
    def has_price(self) -> bool:
        """A price only counts when it is a number and the entry is verified."""
        return self.verified and isinstance(self.monthly_price_usd, (int, float))

    @property
    def price(self) -> float:
        return float(self.monthly_price_usd) if self.has_price else 0.0

    @property
    def list_price_usd(self) -> float | None:
        """Price shown next to the name: the add-on's own price when it
        needs another service, otherwise the monthly price."""
        return self.own_price_usd if self.requires else self.monthly_price_usd

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
            carries_verified_confidence=s.get("carries_verified_confidence", ""),
            carries_confidence_note=s.get("carries_confidence_note", ""),
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

CONFIDENCE_COUNTS = ("high", "moderate")


@dataclass
class LocalOTA:
    status: str          # all, partial, most, none or unknown
    games: int | None
    note: str

    @property
    def counts(self) -> bool:
        """Only 'all' is coverage: with 'partial' or 'most' we do not know which games."""
        return self.status == "all"


@dataclass
class LocalOption:
    """One in-market streaming option."""
    name: str
    monthly_price_usd: float | None
    season_price_usd: float | None
    note: str
    price_verified: bool = False
    requires_service: str = ""
    shared_service: str = ""
    billing_note: str = ""       # from the shared service, when there is one


@dataclass
class LocalTV:
    slug: str
    confidence: str              # high, moderate, low or unknown
    local_broadcasters: list[str]
    ota: LocalOTA
    streaming: list[LocalOption]
    live_tv_carriers: list[str]
    territory: str
    notes: str
    sources: list[str]
    exclude_from_us_maths: bool = False
    last_checked: str = ""

    @property
    def counts(self) -> bool:
        """Whether this team's local options may enter the coverage maths."""
        return self.confidence in CONFIDENCE_COUNTS and not self.exclude_from_us_maths

    @property
    def names(self) -> list[str]:
        return list(self.local_broadcasters)

    @property
    def primary_carriers(self) -> list[str]:
        """Where a local game with no channel in the feed is most likely on:
        the stations when every local game is over the air, otherwise the
        first streaming option. Stations from a 'partial' or 'most' list only
        carry some games, so they are never offered here."""
        if self.ota.status == "all":
            return list(self.local_broadcasters)
        return [self.streaming[0].name] if self.streaming else []


def load_local_tv(data_dir: Path | None = None) -> dict[str, LocalTV]:
    data_dir = data_dir or config.DATA_DIR
    raw = json.loads((data_dir / "local_tv.json").read_text(encoding="utf-8"))
    last_checked = (raw.get("_meta") or {}).get("last_checked", "")
    shared = raw.get("shared_services") or {}
    out: dict[str, LocalTV] = {}
    for slug, t in (raw.get("teams") or {}).items():
        options = []
        for o in t.get("streaming") or []:
            base = shared.get(o.get("shared_service", ""), {})
            options.append(LocalOption(
                name=o.get("name") or base.get("name", ""),
                monthly_price_usd=o.get("monthly_price_usd", base.get("monthly_price_usd")),
                season_price_usd=o.get("season_price_usd", base.get("season_price_usd")),
                note=o.get("note", ""),
                price_verified=bool(o.get("price_verified", base.get("verified", False))),
                requires_service=o.get("requires_service", ""),
                shared_service=o.get("shared_service", ""),
                billing_note=base.get("billing_note", ""),
            ))
        ota = t.get("ota") or {}
        out[slug] = LocalTV(
            slug=slug,
            confidence=t.get("confidence", "unknown"),
            local_broadcasters=list(t.get("local_broadcasters") or []),
            ota=LocalOTA(status=ota.get("status", "unknown"), games=ota.get("games"),
                         note=ota.get("note", "")),
            streaming=options,
            live_tv_carriers=list(t.get("live_tv_carriers") or []),
            territory=t.get("territory", ""),
            notes=t.get("notes", ""),
            sources=list(t.get("sources") or []),
            exclude_from_us_maths=bool(t.get("exclude_from_us_maths")),
            last_checked=last_checked,
        )
    return out


# --------------------------------------------------------------------------
# Copy
# --------------------------------------------------------------------------

def load_copy(data_dir: Path | None = None) -> dict[str, Any]:
    data_dir = data_dir or config.DATA_DIR
    return json.loads((data_dir / "copy.json").read_text(encoding="utf-8"))
