"""'What am I missing?' on the team pages.

Two halves:

- payload() turns the coverage engine's output (the per-service game masks from
  build_state_coverage) into the compact JSON embedded in each team page. Only
  names, prices and masks go in. No signup or affiliate link is included, so a
  commission can never change what the page recommends.
- answer() is the reference result for a set of services the reader already
  pays for. It reuses coverage._cheapest for the add-on search.
  assets/watch-guide.js ports this function line for line so the page can
  answer without a network request, and tests/test_missing.py runs both on the
  same inputs to keep them identical.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from .coverage import STATES, StateCoverage, _cheapest

ANTENNA = "antenna"          # one tick box for every free over-the-air service
PAYLOAD_VERSION = 1


def option_id(svc) -> str:
    return ANTENNA if svc.kind == "ota" else svc.id


def payload(games: list[dict[str, str]], coverages: dict[str, StateCoverage],
            antenna_name: str) -> dict[str, Any]:
    """The matrix for one team page.

    games: [{"d": date label, "o": opponent label}] in the same order the
    coverage engine saw them. coverages: build_state_coverage per state.

    Tick boxes: every service whose carries list is verified, the team's local
    options, and one 'Antenna' box standing for every over-the-air service
    (the national antennas and, in-market, the team's own stations).
    """
    options: dict[str, dict[str, Any]] = {}
    for state in STATES:
        cov = coverages[state]
        masks = {c.service.id: c.mask for c in cov.per_service}
        for svc in (cov.service_data.services if cov.service_data else []):
            if not svc.carries_verified:
                continue
            key = option_id(svc)
            opt = options.get(key)
            if opt is None:
                opt = options[key] = {
                    "id": key,
                    "name": antenna_name if key == ANTENNA else svc.name,
                    # Price of this option alone. An add-on that needs another
                    # service lists that service in req; the page adds its
                    # price only when the reader does not have it already.
                    "price": svc.list_price_usd if svc.has_price else None,
                    "req": [option_id(r) for r in svc.requires],
                    "m": {s: 0 for s in STATES},
                }
            elif key == ANTENNA and not svc.has_price:
                opt["price"] = None
            opt["m"][state] |= masks.get(svc.id, 0)
    for opt in options.values():
        opt["m"] = {s: format(m, "x") for s, m in opt["m"].items()}
    return {"v": PAYLOAD_VERSION, "games": games, "options": list(options.values())}


# --------------------------------------------------------------------------
# Reference answer
# --------------------------------------------------------------------------

def _pop(mask: int) -> int:
    return bin(mask).count("1")


def _effective_price(opt: dict, by_id: dict, owned: set[str]) -> float | None:
    """What adding this option costs someone who owns `owned`."""
    if opt["price"] is None:
        return None
    price = opt["price"]
    for rid in opt["req"]:
        if rid in owned:
            continue
        req = by_id.get(rid)
        if req is None or req["price"] is None:
            return None
        price += req["price"]
    return round(price, 2)


def answer(data: dict[str, Any], state: str, owned: set[str]) -> dict[str, Any]:
    """covered/total, the games missed, the best single add-on and the
    cheapest set of add-ons reaching every game (or as many as possible)."""
    total = len(data["games"])
    by_id = {o["id"]: o for o in data["options"]}
    mask_of = {o["id"]: int(o["m"][state], 16) for o in data["options"]}
    owned = {o for o in owned if o in by_id}

    have = 0
    for oid in owned:
        have |= mask_of[oid]
    covered = _pop(have)
    missing = [i for i in range(total) if not (have >> i) & 1]

    candidates = []
    for opt in data["options"]:
        if opt["id"] in owned:
            continue
        price = _effective_price(opt, by_id, owned)
        added = _pop(mask_of[opt["id"]] & ~have)
        if price is None or not added:
            continue
        candidates.append(SimpleNamespace(id=opt["id"], name=opt["name"], price=price, added=added))

    single = None
    if candidates:
        best = sorted(candidates, key=lambda c: (-c.added, c.price, c.name))[0]
        single = {"id": best.id, "added": best.added, "price": best.price}

    best_set = None
    if missing and candidates:
        reach = have
        for c in candidates:
            reach |= mask_of[c.id]
        target = _pop(reach)
        # Masks include what the reader already has, so _cheapest counts
        # every game they would end up able to watch.
        masks = {c.id: mask_of[c.id] | have for c in candidates}
        combo = _cheapest(list(range(total)), candidates, masks, total, target)
        if combo is not None:
            best_set = {"ids": [s.id for s in combo.services], "price": combo.total_price,
                        "covered": combo.covered, "complete": combo.covered == total}

    return {"covered": covered, "total": total, "missing": missing,
            "single": single, "set": best_set}
