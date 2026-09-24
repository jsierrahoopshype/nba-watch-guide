"""The shipped data/services.json: carries_verified, zero prices, the
prices-checked line and League Pass, checked in the maths and on the page."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

import pytest

from watchguide.coverage import OUT_OF_MARKET, build_state_coverage, carriers_for_game
from watchguide.model import Game, load_services

TEAM = "BOS"
PAGE = "boston-celtics/index.html"


def game(idx: int, national=None) -> Game:
    day = (date(2027, 1, 15) + timedelta(days=idx)).isoformat()
    return Game(
        game_id=f"00226{idx:05d}", game_code="x", date_et=day,
        tipoff_et=f"{day}T19:00:00-05:00", tipoff_utc=f"{day}T00:00:00+00:00",
        status_text="7:00 pm ET", home_tricode=TEAM, away_tricode="NYK",
        national=list(national or []),
    )


@pytest.fixture
def shipped():
    return load_services()


def _html(site):
    return (site / PAGE).read_text(encoding="utf-8")


def _panel(html: str, state: str) -> str:
    start = html.index(f'data-state-panel="{state}"')
    end = html.find("</section>", start)
    return html[start:end]


def _coverage_block(panel: str) -> str:
    """The 'What each service covers' card, up to the cheapest block."""
    return panel[panel.index("What each service covers"):panel.index("Cheapest way to watch")]


# -- 1. carries_verified false ----------------------------------------------

def test_unverified_carries_count_for_nothing(priced_services):
    # Big Bundle is priced and claims ESPN, ABC, NBC and NBA TV, but its
    # carries list is not checked, so it must not show up anywhere in the maths.
    priced_services.by_id("bundle").carries_verified = False
    games = [game(0, national=["ABC"]), game(1, national=["ESPN"]), game(2, national=["NBA TV"])]
    cov = build_state_coverage(games, TEAM, priced_services, None, OUT_OF_MARKET)
    counts = {c.service.id: c.covered for c in cov.per_service}
    assert counts["bundle"] == 0
    assert "bundle" in counts                      # still listed
    assert sorted(s.id for s in cov.cheapest_full.services) == ["free-air", "pricey", "sportsnet"]
    assert cov.cheapest_full.total_price == 109.0


def test_shipped_live_tv_bundles_do_not_count_yet(shipped):
    # ESPN is claimed by five live TV services with carries_verified false.
    carriers = carriers_for_game(game(0, national=["ESPN"]), TEAM, shipped, None, OUT_OF_MARKET)
    assert carriers == {"espn_unlimited"}
    peacock = carriers_for_game(game(1, national=["Peacock"]), TEAM, shipped, None, OUT_OF_MARKET)
    assert peacock == set()


def test_unverified_services_listed_with_price_and_unconfirmed_line(built_site):
    html = _html(built_site)
    unverified = [s for s in load_services().services if not s.carries_verified]
    assert unverified
    for state in ("out_of_market", "in_market"):
        panel = _panel(html, state)
        assert panel.count("data-coverage-unconfirmed") == len(unverified)
        assert "Which games this covers is not confirmed yet" in panel
        for svc in unverified:
            assert svc.name in panel
            assert f"${svc.monthly_price_usd:,.2f}" in panel
            assert svc.name not in _coverage_block(panel)


# -- 2. 0 is a price, null is not -------------------------------------------

def test_zero_price_is_free_coverage_and_null_stays_out(shipped):
    abc, nbc, nba_tv = (shipped.by_id(i) for i in ("antenna_abc", "antenna_nbc", "nba_tv"))
    assert abc.has_price and abc.is_free and abc.price == 0
    assert nbc.has_price and nbc.is_free
    assert not nba_tv.has_price and not nba_tv.is_free

    # Nine free-to-air games and one on NBA TV, which only the unpriced NBA TV carries.
    games = [game(i, national=["ABC" if i % 2 else "NBC"]) for i in range(9)]
    games.append(game(9, national=["NBA TV"]))
    cov = build_state_coverage(games, TEAM, shipped, None, OUT_OF_MARKET)
    counts = {c.service.id: c.covered for c in cov.per_service}
    assert counts["nba_tv"] == 1                  # coverage still counted
    assert cov.cheapest_full is None              # but it has no price to add up
    assert cov.cheapest_ninety is not None
    assert sorted(s.id for s in cov.cheapest_ninety.services) == ["antenna_abc", "antenna_nbc"]
    assert cov.cheapest_ninety.total_price == 0.0
    assert [g.game_id for g in cov.cheapest_ninety.missed] == [games[9].game_id]


def test_zero_price_renders_as_free_not_unconfirmed(built_site):
    panel = _panel(_html(built_site), "out_of_market")
    services = panel[panel.index("Services and prices"):]
    for name in ("ABC (over the air)", "NBC (over the air)"):
        row = services[services.index(name):]
        row = row[:row.index('<div class="row">') if '<div class="row">' in row else len(row)]
        assert '<span class="price">Free</span>' in row
        assert "Price not confirmed" not in row
    nba_tv = services[services.index(">NBA TV<"):]
    assert "Price not confirmed" in nba_tv[:nba_tv.index('<div class="row">')]


# -- 3. prices checked -------------------------------------------------------

def test_prices_checked_line_comes_from_meta(built_site, shipped):
    assert shipped.prices_checked == "2026-09-25"
    html = _html(built_site)
    lines = re.findall(r'<p class="small muted" data-prices-checked>([^<]+)</p>', html)
    assert lines == ["Prices checked September 2026"] * 2      # one per market panel


# -- 4. League Pass ----------------------------------------------------------

def test_league_pass_is_wired_to_the_rules_block(shipped):
    assert shipped.league_pass_service_id == "nba_league_pass"
    assert shipped.by_id("nba_league_pass").carries == []
    assert {b.applies_to for b in shipped.blackouts} == {"national_broadcast", "in_market_local"}
    assert "nba_league_pass" in carriers_for_game(game(0), TEAM, shipped, None, OUT_OF_MARKET)
    assert "nba_league_pass" not in carriers_for_game(
        game(0, national=["ESPN"]), TEAM, shipped, None, OUT_OF_MARKET)


def test_league_pass_is_listed_in_both_market_panels(built_site):
    html = _html(built_site)
    for state in ("out_of_market", "in_market"):
        panel = _panel(html, state)
        assert "NBA League Pass" in _coverage_block(panel)
        assert "NBA League Pass" in panel[panel.index("Services and prices"):]


def test_missing_league_pass_service_fails_loudly(tmp_path):
    from pathlib import Path
    raw = json.loads((Path(__file__).resolve().parent.parent / "data" / "services.json")
                     .read_text(encoding="utf-8"))
    raw["services"] = [s for s in raw["services"] if s["id"] != "nba_league_pass"]
    (tmp_path / "services.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="League Pass"):
        load_services(tmp_path)
