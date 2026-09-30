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
    # Each side's record as the schedule feed lists it on this game, or None
    # when the feed has none. Used for stakes in tonight's ranking.
    home_wins: int | None = None
    home_losses: int | None = None
    away_wins: int | None = None
    away_losses: int | None = None
    # The feed's gameStatus (1 scheduled, 2 live, 3 final) and, only once a
    # game is final, each side's score. None until the feed has one.
    game_status: int = 0
    home_score: int | None = None
    away_score: int | None = None

    @property
    def is_final(self) -> bool:
        return self.game_status == 3 and self.home_score is not None and self.away_score is not None

    @property
    def winner(self) -> str:
        """Tricode of the winning side of a final game, or ""."""
        if not self.is_final or self.home_score == self.away_score:
            return ""
        return self.home_tricode if self.home_score > self.away_score else self.away_tricode

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

LINEUP_STATUSES = ("carried", "not_carried", "zip_dependent", "unchecked")
LINEUP_CONFIDENCE = ("high", "moderate")
LINEUP_YEAR = "2026"          # third-party sources must be published this year


def _norm_code(code: str) -> str:
    return "".join(ch for ch in (code or "").lower() if ch.isalnum())


@dataclass
class LineupSource:
    url: str
    published: str = ""       # YYYY, YYYY-MM or YYYY-MM-DD, or "official" for the service's own page


@dataclass
class LineupChannel:
    """One channel in one live TV package. status is carried, not_carried,
    zip_dependent (sources say it depends on the ZIP code or market) or
    unchecked; confidence is high or moderate once sourced."""
    channel: str
    status: str = "unchecked"
    confidence: str = ""
    sources: list[LineupSource] = field(default_factory=list)
    checked: str = ""
    note: str = ""


def _site(url: str) -> str:
    """The site a URL is on, without www., for telling sources apart."""
    from urllib.parse import urlparse
    host = (urlparse(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def official_url(url: str, domains: list[str]) -> bool:
    """Whether url is https on one of `domains` or a subdomain of one."""
    from urllib.parse import urlparse
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == d or host.endswith("." + d) for d in domains)


def sourced_confidence(entry: LineupChannel, domains: list[str]) -> str:
    """The confidence an entry has earned, or "" when it falls short:
    high needs a source on the service's own domains; moderate needs two or
    more sources on different sites, each either the service's own page or a
    third-party page published in LINEUP_YEAR. Both need a check date."""
    if entry.status == "unchecked" or entry.confidence not in LINEUP_CONFIDENCE or not entry.checked:
        return ""
    official = [s for s in entry.sources if official_url(s.url, domains) and s.published == "official"]
    dated = [s for s in entry.sources if s.url.startswith("https://") and not official_url(s.url, domains)
             and s.published.startswith(LINEUP_YEAR)]
    if entry.confidence == "high":
        return "high" if official else ""
    sites = {_site(s.url) for s in official + dated}
    return "moderate" if len(sites) >= 2 else ""


@dataclass
class LineupPackage:
    """A live TV package (YouTube TV Base Plan, Sling Orange...) and its
    per-channel carries list. label is the name the cable line uses."""
    name: str
    label: str
    channels: list[LineupChannel] = field(default_factory=list)
    official_domains: list[str] = field(default_factory=list)

    def entry(self, code: str) -> LineupChannel | None:
        return next((c for c in self.channels if _norm_code(c.channel) == _norm_code(code)), None)

    def carried_confidence(self, code: str) -> str:
        """high or moderate when this channel is carried and the entry's
        sources back that confidence (sourced_confidence), else ""."""
        entry = self.entry(code)
        if not entry or entry.status != "carried":
            return ""
        return sourced_confidence(entry, self.official_domains)


def load_lineup(raw: dict[str, Any] | None) -> list[LineupPackage]:
    """services.json lineup block to packages. Anything malformed reads as
    unchecked rather than failing the build."""
    if not isinstance(raw, dict):
        return []
    domains = [str(d).lower() for d in raw.get("official_domains") or []]
    packages = []
    for pkg in raw.get("packages") or []:
        channels = []
        for ch in pkg.get("channels") or []:
            status = ch.get("status", "unchecked")
            confidence = ch.get("confidence", "")
            channels.append(LineupChannel(
                channel=str(ch.get("channel", "")),
                status=status if status in LINEUP_STATUSES else "unchecked",
                confidence=confidence if confidence in LINEUP_CONFIDENCE else "",
                sources=[LineupSource(url=str(src.get("url") or ""), published=str(src.get("published") or ""))
                         for src in ch.get("sources") or [] if isinstance(src, dict)],
                checked=str(ch.get("checked") or ""),
                note=str(ch.get("note") or ""),
            ))
        packages.append(LineupPackage(name=str(pkg.get("name", "")), label=str(pkg.get("label") or pkg.get("name", "")),
                                      channels=channels, official_domains=domains))
    return packages


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
    # Live TV services only: each package's per-channel carries list (see
    # apply_lineup). It replaces carries and carries_verified above for the
    # coverage maths, and the game block's cable line reads it directly.
    lineup: list[LineupPackage] = field(default_factory=list)
    # Filled by apply_lineup: counted channels whose best entry is moderate
    # confidence, and local ABC/NBC counted only through "depends on ZIP".
    moderate_codes: list[str] = field(default_factory=list)
    zip_codes: list[str] = field(default_factory=list)

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


# National channels a live TV lineup can count toward the coverage maths, and
# the local broadcast networks whose "depends on ZIP" entries count as carried
# for their national games. Regional networks never count.
LINEUP_COUNTED = ("ESPN", "ESPN2", "ABC", "NBC", "NBA TV")
LINEUP_ZIP_COUNTED = ("ABC", "NBC")


def apply_lineup(svc: Service) -> None:
    """For a live TV service, set carries and carries_verified from its
    lineup instead of the service-level fields: a channel counts when a
    package has it carried at high or moderate confidence, or, for ABC and
    NBC, "depends on ZIP" at either confidence. unchecked and not_carried
    never count. The service covers the union of its packages (Sling Orange
    and Blue are one Orange + Blue service)."""
    best: dict[str, tuple[str, str]] = {}          # code -> (how, confidence)
    rank = {("carried", "high"): 4, ("carried", "moderate"): 3, ("zip", "high"): 2, ("zip", "moderate"): 1}
    for pkg in svc.lineup:
        for code in LINEUP_COUNTED:
            entry = pkg.entry(code)
            if entry is None:
                continue
            confidence = sourced_confidence(entry, pkg.official_domains)
            if not confidence:
                continue
            if entry.status == "carried":
                how = "carried"
            elif entry.status == "zip_dependent" and code in LINEUP_ZIP_COUNTED:
                how = "zip"
            else:
                continue
            if rank[(how, confidence)] > rank.get(best.get(code, ("", "")), 0):
                best[code] = (how, confidence)
    svc.carries = [c for c in LINEUP_COUNTED if c in best]
    svc.carries_verified = bool(svc.carries)
    svc.moderate_codes = [c for c in svc.carries if best[c][1] == "moderate"]
    svc.zip_codes = [c for c in svc.carries if best[c][0] == "zip"]
    svc.carries_verified_confidence = "moderate" if svc.moderate_codes else ""


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
            lineup=load_lineup(s.get("lineup")),
        ))
        if services[-1].kind == "live_tv":
            apply_lineup(services[-1])
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
    # {full name: short name} for channel chips; see short_name().
    short_names: dict[str, str] = field(default_factory=dict)

    def short_name(self, name: str) -> str:
        """The name a channel chip shows: the short one when the file has
        one, otherwise the full name."""
        return self.short_names.get(name, name)

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
            short_names={str(k): str(v) for k, v in (t.get("short_names") or {}).items() if k and v},
        )
    return out


# --------------------------------------------------------------------------
# Team colors
# --------------------------------------------------------------------------

def load_team_colors(data_dir: Path | None = None) -> dict[str, str]:
    """{tricode: '#RRGGBB'} from data/team_colors.json. A missing file or a
    malformed value just means no accent for that team."""
    data_dir = data_dir or config.DATA_DIR
    try:
        raw = json.loads((data_dir / "team_colors.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    for tricode, entry in (raw.get("teams") or {}).items():
        value = (entry or {}).get("primary", "") if isinstance(entry, dict) else ""
        if isinstance(value, str) and len(value) == 7 and value.startswith("#"):
            try:
                int(value[1:], 16)
            except ValueError:
                continue
            out[tricode] = value.upper()
    return out


# --------------------------------------------------------------------------
# Copy
# --------------------------------------------------------------------------

def load_copy(data_dir: Path | None = None) -> dict[str, Any]:
    data_dir = data_dir or config.DATA_DIR
    return json.loads((data_dir / "copy.json").read_text(encoding="utf-8"))
