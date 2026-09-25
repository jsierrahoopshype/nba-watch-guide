"""Who carries which game, and the cheapest set of services that covers them.

Everything here is driven by data/services.json and data/local_tv.json. No
channel, price or blackout rule is written into this file.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from itertools import combinations

from .model import Game, LocalTV, Service, ServiceData

OUT_OF_MARKET = "out_of_market"
IN_MARKET = "in_market"
STATES = (OUT_OF_MARKET, IN_MARKET)


def _norm(code: str) -> str:
    """Loose match so 'NBA TV' and 'NBATV' line up."""
    return "".join(ch for ch in (code or "").lower() if ch.isalnum())


# --------------------------------------------------------------------------
# Which services carry one game
# --------------------------------------------------------------------------

def league_pass_blocked(game: Game, state: str, service_data: ServiceData) -> list[str]:
    """Labels of the blackout rules that stop League Pass showing this game."""
    hits = []
    for rule in service_data.active_blackouts("national_broadcast"):
        if game.is_national:
            hits.append(rule.label)
    for rule in service_data.active_blackouts("in_market_local"):
        if state == IN_MARKET:
            hits.append(rule.label)
    return hits


def carriers_for_game(
    game: Game,
    tricode: str,
    service_data: ServiceData,
    local: LocalTV | None,
    state: str,
) -> set[str]:
    """Service ids that let a viewer in `state` watch this game."""
    carriers: set[str] = set()
    national = {_norm(c) for c in game.national_codes}

    lp = service_data.league_pass_service_id
    # Channels bundled into League Pass (NBA TV) come through the League Pass
    # subscription, so they share its in-market blackout.
    lp_blacked_out_here = state == IN_MARKET and bool(service_data.active_blackouts("in_market_local"))

    # National broadcasts reach everyone who has a service carrying that channel.
    if national:
        for svc in service_data.services:
            if svc.id == lp and lp_blacked_out_here:
                continue
            if any(_norm(c) in national for c in svc.carries):
                carriers.add(svc.id)

    # Local options only reach a reader inside the market, and only for the
    # team's games with no national broadcaster. They are in service_data only
    # when with_local_options() put them there for this team.
    if state == IN_MARKET and local and local.counts and not game.is_national:
        for svc in service_data.services:
            if svc.local_option:
                carriers.add(svc.id)

    # League Pass, unless a blackout rule from the data file applies.
    if lp and service_data.by_id(lp) and not league_pass_blocked(game, state, service_data):
        carriers.add(lp)

    # An add-on that needs another service also gives you that service's games.
    for svc in service_data.services:
        if svc.requires and all(r.id in carriers for r in svc.requires):
            carriers.add(svc.id)

    # A service whose carries list is not checked yet counts for nothing, so it
    # stays out of the per-service counts and the cheapest-combination maths.
    return {sid for sid in carriers
            if (svc := service_data.by_id(sid)) is None or svc.carries_verified}


def channels_for_game(game: Game, tricode: str, local: LocalTV | None,
                      tba_label: str = "TBA") -> list[dict[str, str]]:
    """Channels to print next to a game, as {name, kind}. Never guesses.

    kind is national, local or tba, so the page can mark them differently and
    a reader can tell a league-wide broadcast from a regional one.
    """
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(name: str, kind: str) -> None:
        if name and name not in seen:
            seen.add(name)
            out.append({"name": name, "kind": kind})

    for code in game.national_codes:
        add(code, "national")
    local_codes = game.local_codes_for(tricode)
    if local_codes:
        for code in local_codes:
            add(code, "local")
    elif not out and local and local.counts:
        for name in local.names:
            add(name, "local")
    if not out:
        add(tba_label, "tba")
    return out


def channel_names(channels: list[dict[str, str]]) -> list[str]:
    return [c["name"] for c in channels]


# --------------------------------------------------------------------------
# Coverage over a set of games
# --------------------------------------------------------------------------

@dataclass
class ServiceCoverage:
    service: Service
    covered: int
    total: int
    mask: int = 0

    @property
    def percent(self) -> float:
        return 0.0 if not self.total else 100.0 * self.covered / self.total


@dataclass
class Combination:
    services: list[Service]
    total_price: float
    covered: int
    total: int
    missed: list[Game] = field(default_factory=list)

    @property
    def percent(self) -> float:
        return 0.0 if not self.total else 100.0 * self.covered / self.total

    @property
    def parts(self) -> list[Service]:
        """Services to list under the combination, with any service an add-on
        needs spelled out after it. The prices add up to total_price."""
        out: list[Service] = []
        for svc in self.services:
            for part in (svc, *svc.requires):
                if all(part is not seen for seen in out):
                    out.append(part)
        return out


@dataclass
class StateCoverage:
    state: str
    games: list[Game]
    per_service: list[ServiceCoverage]
    cheapest_full: Combination | None
    cheapest_ninety: Combination | None
    uncovered: list[Game]            # games no listed service carries
    priced_services: int             # how many services had a confirmed price
    service_data: ServiceData | None = None   # what the maths ran on, local options included

    @property
    def total(self) -> int:
        return len(self.games)


def build_state_coverage(
    games: list[Game],
    tricode: str,
    service_data: ServiceData,
    local: LocalTV | None,
    state: str,
) -> StateCoverage:
    service_data = with_local_options(service_data, local, state)
    total = len(games)

    # Bitmask per service: bit i set means it carries games[i].
    masks: dict[str, int] = {s.id: 0 for s in service_data.services}
    any_mask = 0
    for i, game in enumerate(games):
        bit = 1 << i
        for sid in carriers_for_game(game, tricode, service_data, local, state):
            if sid in masks:
                masks[sid] |= bit
                any_mask |= bit

    per_service = [
        ServiceCoverage(service=s, covered=bin(masks[s.id]).count("1"), total=total, mask=masks[s.id])
        for s in service_data.services
    ]
    per_service.sort(key=lambda c: (-c.covered, c.service.name))

    uncovered = [g for i, g in enumerate(games) if not (any_mask >> i) & 1]

    priced = [s for s in service_data.services if s.has_price and masks[s.id]]
    full = _cheapest(games, priced, masks, total, total)
    ninety_target = math.ceil(total * 0.9) if total else 0
    ninety = _cheapest(games, priced, masks, total, ninety_target)

    # Do not repeat the full answer under the 90% heading.
    if full and ninety and ninety.total_price >= full.total_price:
        ninety = None

    return StateCoverage(
        state=state,
        games=games,
        per_service=per_service,
        cheapest_full=full,
        cheapest_ninety=ninety,
        uncovered=uncovered,
        priced_services=len(priced),
        service_data=service_data,
    )


# --------------------------------------------------------------------------
# In-market local options from data/local_tv.json
# --------------------------------------------------------------------------

def local_services(local: LocalTV | None, service_data: ServiceData) -> list[Service]:
    """The team's local options as services the maths can use.

    Empty unless the team's confidence lets local options count (high or
    moderate, and not excluded from US maths). Over the air only counts at
    status 'all'. A streaming option with a null price is still returned, so
    it is listed and counted, but has no price and cannot enter a combination.
    """
    if not local or not local.counts:
        return []
    confidence = local.confidence if local.confidence == MODERATE else ""
    source = local.sources[0] if local.sources else ""

    def make(sid: str, name: str, price, note: str, requires=()) -> Service:
        return Service(
            id=sid, name=name, kind="local", monthly_price_usd=price, billing_note=note,
            carries=[], carries_note="", signup_url="", affiliate_url="",
            source_url=source, last_verified=local.last_checked, verified=True,
            carries_verified=True, carries_verified_confidence=confidence,
            local_option=True, requires=list(requires),
        )

    out: list[Service] = []
    if local.ota.counts:
        out.append(make(f"local-{local.slug}-ota", "Local TV over the air", 0, local.ota.note))
    for i, opt in enumerate(local.streaming):
        price = opt.monthly_price_usd
        requires = []
        if opt.requires_service:
            required = service_data.by_id(opt.requires_service)
            if required is None or not required.has_price:
                price = None             # real cost unknown, so no combination
            else:
                requires = [required]
        svc = make(f"local-{local.slug}-{i}", opt.name, price, opt.note, requires)
        if requires and price is not None:
            svc.own_price_usd = price
            svc.monthly_price_usd = round(price + sum(r.price for r in requires), 2)
        out.append(svc)
    return out


def with_local_options(service_data: ServiceData, local: LocalTV | None, state: str) -> ServiceData:
    """service_data plus the team's local options, in-market only."""
    if state != IN_MARKET:
        return service_data
    extra = local_services(local, service_data)
    if not extra:
        return service_data
    return replace(service_data, services=list(service_data.services) + extra)


def _cheapest(
    games: list[Game],
    priced: list[Service],
    masks: dict[str, int],
    total: int,
    target: int,
) -> Combination | None:
    """Cheapest subset of `priced` covering at least `target` of `total` games.

    The service list is short, so every subset is tried. Ties go to the smaller
    set, then to the one covering more games.
    """
    if not total or not target or not priced:
        return None

    # Drop a service whose games are a subset of a cheaper-or-equal service's.
    kept: list[Service] = []
    for svc in sorted(priced, key=lambda s: (s.price, -bin(masks[s.id]).count("1"))):
        m = masks[svc.id]
        if any((m | masks[k.id]) == masks[k.id] and k.price <= svc.price for k in kept):
            continue
        kept.append(svc)

    best: tuple[float, int, int] | None = None
    best_combo: list[Service] | None = None
    best_mask = 0
    for size in range(1, len(kept) + 1):
        if best is not None and size > len(best_combo or []):
            # A bigger set can still be cheaper (free channels), so keep going,
            # but stop once no remaining set can beat the price.
            cheapest_possible = sum(sorted(s.price for s in kept)[:size])
            if cheapest_possible > best[0]:
                break
        for combo in combinations(kept, size):
            mask = 0
            for s in combo:
                mask |= masks[s.id]
            covered = bin(mask).count("1")
            if covered < target:
                continue
            price = round(sum(s.price for s in combo), 2)
            key = (price, len(combo), -covered)
            if best is None or key < best:
                best, best_combo, best_mask = key, list(combo), mask

    if best_combo is None:
        return None

    missed = [g for i, g in enumerate(games) if not (best_mask >> i) & 1]
    return Combination(
        services=sorted(best_combo, key=lambda s: (-s.price, s.name)),
        total_price=round(sum(s.price for s in best_combo), 2),
        covered=bin(best_mask).count("1"),
        total=total,
        missed=missed,
    )


# --------------------------------------------------------------------------
# Lower-confidence carriage inside a combination
# --------------------------------------------------------------------------

MODERATE = "moderate"


def moderate_carries_in(
    combo: Combination | None,
    games: list[Game],
    tricode: str,
    service_data: ServiceData,
    local: LocalTV | None,
    state: str,
) -> list[dict]:
    """Services in `combo` whose moderate-confidence carries list actually
    reaches a game the combination covers, as {service, channels}.

    A service only counts through its carries list here, not through a rule
    (League Pass covering games with no national broadcast is not flagged).
    """
    if not combo:
        return []
    moderate = [s for s in combo.services if s.carries_verified_confidence == MODERATE]
    if not moderate:
        return []
    missed = {g.game_id for g in combo.missed}
    out = []
    for svc in moderate:
        carried = {_norm(c): c for c in svc.carries}
        channels: list[str] = []
        used = False
        for game in games:
            if game.game_id in missed:
                continue
            if svc.local_option:
                # A local option's coverage is the local games themselves.
                hits = [] if game.is_national else ["local"]
            else:
                hits = [code for code in game.national_codes if _norm(code) in carried]
            if hits and svc.id in carriers_for_game(game, tricode, service_data, local, state):
                used = True
                channels += [c for c in hits if c not in channels and c != "local"]
        if used:
            out.append({"service": svc, "channels": channels})
    return out
