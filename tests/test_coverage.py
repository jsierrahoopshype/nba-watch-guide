"""Cheapest-combination maths against a small made-up price list."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from watchguide.coverage import (IN_MARKET, OUT_OF_MARKET, build_state_coverage,
                                 carriers_for_game, channel_names, channels_for_game)
from watchguide.model import Game, LocalOption, LocalOTA, LocalTV

TEAM = "BOS"
OPP = "NYK"


def game(idx: int, national=None, home_tv=None) -> Game:
    day = (date(2027, 1, 15) + timedelta(days=idx)).isoformat()
    return Game(
        game_id=f"00226{idx:05d}", game_code="x", date_et=day,
        tipoff_et=f"{day}T19:00:00-05:00", tipoff_utc=f"{day}T00:00:00+00:00",
        status_text="7:00 pm ET", home_tricode=TEAM, away_tricode=OPP,
        national=list(national or []), home_tv=list(home_tv or []),
    )


def local_tv(confidence="high", ota="none", price=40.0):
    return LocalTV(slug="boston-celtics", confidence=confidence,
                   local_broadcasters=["Test Local 1"],
                   ota=LocalOTA(status=ota, games=None, note=""),
                   streaming=[LocalOption(name="Test Local App", monthly_price_usd=price,
                                          season_price_usd=None, note="")],
                   live_tv_carriers=[], territory="Test market", notes="", sources=["x"],
                   last_checked="2027-01-01")


LOCAL_APP = "local-boston-celtics-0"


@pytest.fixture
def local_verified():
    return local_tv()


# -- who carries what -------------------------------------------------------

def test_league_pass_carries_a_game_with_no_national_broadcast(priced_services):
    g = game(0, home_tv=["TESTLOCAL1"])
    assert "league-pass" in carriers_for_game(g, TEAM, priced_services, None, OUT_OF_MARKET)


def test_league_pass_is_blacked_out_on_a_national_game(priced_services):
    g = game(0, national=["ESPN"])
    assert "league-pass" not in carriers_for_game(g, TEAM, priced_services, None, OUT_OF_MARKET)


def test_league_pass_is_blacked_out_in_market(priced_services, local_verified):
    g = game(0, home_tv=["TESTLOCAL1"])
    assert "league-pass" not in carriers_for_game(g, TEAM, priced_services, local_verified, IN_MARKET)


def test_local_broadcast_does_not_reach_out_of_market(priced_services, local_verified):
    cov = build_state_coverage([game(0, home_tv=["TESTLOCAL1"])], TEAM, priced_services,
                               local_verified, OUT_OF_MARKET)
    assert all(not c.service.local_option for c in cov.per_service)


def test_local_broadcast_reaches_in_market_through_its_app(priced_services, local_verified):
    cov = build_state_coverage([game(0, home_tv=["TESTLOCAL1"])], TEAM, priced_services,
                               local_verified, IN_MARKET)
    assert {c.service.id: c.covered for c in cov.per_service}[LOCAL_APP] == 1


def test_unverified_local_data_carries_nothing_in_market(priced_services):
    cov = build_state_coverage([game(0, home_tv=["TESTLOCAL1"])], TEAM, priced_services,
                               local_tv(confidence="low"), IN_MARKET)
    assert all(not c.service.local_option for c in cov.per_service)
    assert len(cov.uncovered) == 1


def test_channel_names_fall_back_to_tba(priced_services):
    assert channels_for_game(game(0), TEAM, None) == [{"name": "TBA", "kind": "tba"}]
    assert channels_for_game(game(0, national=["ESPN"]), TEAM, None) == [
        {"name": "ESPN", "kind": "national"}]


def test_local_and_national_channels_are_marked_apart(priced_services):
    channels = channels_for_game(game(0, national=["ESPN"], home_tv=["TESTLOCAL1"]), TEAM, None)
    assert channels == [{"name": "ESPN", "kind": "national"},
                        {"name": "TESTLOCAL1", "kind": "local"}]


# -- cheapest combination ---------------------------------------------------

def test_free_over_the_air_wins_when_it_covers_everything(priced_services):
    games = [game(0, national=["ABC"]), game(1, national=["NBC"])]
    cov = build_state_coverage(games, TEAM, priced_services, None, OUT_OF_MARKET)
    assert cov.cheapest_full is not None
    assert [s.id for s in cov.cheapest_full.services] == ["free-air"]
    assert cov.cheapest_full.total_price == 0.0
    assert cov.cheapest_full.missed == []


def test_cheapest_full_picks_the_cheaper_of_two_valid_sets(priced_services):
    # ABC and NBC are free; ESPN needs either Sports Net (10) or Big Bundle (40).
    games = [game(0, national=["ABC"]), game(1, national=["ESPN"]), game(2, national=["NBC"])]
    cov = build_state_coverage(games, TEAM, priced_services, None, OUT_OF_MARKET)
    assert sorted(s.id for s in cov.cheapest_full.services) == ["free-air", "sportsnet"]
    assert cov.cheapest_full.total_price == 10.0


def test_ninety_percent_option_is_cheaper_and_names_what_it_misses(priced_services):
    # Nine free games plus one that only the 99 dollar service carries.
    games = [game(i, national=["ABC"]) for i in range(9)] + [game(9, national=["NBA TV"])]
    cov = build_state_coverage(games, TEAM, priced_services, None, OUT_OF_MARKET)
    assert cov.cheapest_full.total_price == 40.0          # Big Bundle covers all ten
    assert cov.cheapest_ninety is not None
    assert cov.cheapest_ninety.total_price == 0.0
    assert cov.cheapest_ninety.covered == 9
    assert [g.game_id for g in cov.cheapest_ninety.missed] == [games[9].game_id]


def test_no_combination_when_a_game_has_no_carrier(priced_services):
    # Drop League Pass, which would otherwise mop up anything not on national TV.
    priced_services.services = [s for s in priced_services.services if s.id != "league-pass"]
    priced_services.league_pass_service_id = ""
    games = [game(0, national=["SOME-CHANNEL-NOBODY-HAS"])]
    cov = build_state_coverage(games, TEAM, priced_services, None, OUT_OF_MARKET)
    assert cov.cheapest_full is None
    assert len(cov.uncovered) == 1


def test_per_service_counts_add_up(priced_services):
    games = [game(0, national=["ABC"]), game(1, national=["ESPN"]), game(2)]
    cov = build_state_coverage(games, TEAM, priced_services, None, OUT_OF_MARKET)
    counts = {c.service.id: c.covered for c in cov.per_service}
    assert counts["free-air"] == 1            # the ABC game
    assert counts["sportsnet"] == 1           # the ESPN game
    assert counts["bundle"] == 2              # ABC and ESPN
    assert counts["league-pass"] == 1         # the game with no national broadcast
    assert all(c.total == 3 for c in cov.per_service)


def test_unpriced_services_stay_out_of_the_maths(priced_services):
    for svc in priced_services.services:
        svc.verified = False
    cov = build_state_coverage([game(0, national=["ABC"])], TEAM, priced_services, None, OUT_OF_MARKET)
    assert cov.priced_services == 0
    assert cov.cheapest_full is None
