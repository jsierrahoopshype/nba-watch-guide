"""In-market local options from data/local_tv.json: scope, confidence, over
the air, streaming prices, add-ons, the Raptors exclusion, the 'Watching in'
section and the hub's free-over-the-air line."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

import pytest

from watchguide.coverage import (IN_MARKET, OUT_OF_MARKET, build_state_coverage,
                                 local_services, moderate_carries_in)
from watchguide.model import Game, load_local_tv, load_services

MODERATE_NOTE = ("Local TV details for this team come from news reports, not an official "
                 "team page yet; check before you buy.")
LOW_LINE = "Local details for 2026-27 not confirmed yet."


def game(idx: int, national=None, team="BOS") -> Game:
    day = (date(2027, 1, 15) + timedelta(days=idx)).isoformat()
    return Game(game_id=f"00226{idx:05d}", game_code="x", date_et=day,
                tipoff_et=f"{day}T19:00:00-05:00", tipoff_utc=f"{day}T00:00:00+00:00",
                status_text="7:00 pm ET", home_tricode=team, away_tricode="NYK",
                national=list(national or []))


@pytest.fixture(scope="module")
def services():
    return load_services()


@pytest.fixture(scope="module")
def local():
    return load_local_tv()


def counts(cov):
    return {c.service.id: c.covered for c in cov.per_service}


def local_counts(cov):
    return {c.service.name: c.covered for c in cov.per_service if c.service.local_option}


def panel(site, slug, state):
    html = (site / slug / "index.html").read_text(encoding="utf-8")
    start = html.index(f'data-state-panel="{state}"')
    return html[start:html.index("</section>", start)]


def page(site, slug):
    return (site / slug / "index.html").read_text(encoding="utf-8")


# -- 1. scope -----------------------------------------------------------------

def test_local_options_cover_only_non_national_games_in_market(services, local):
    games = [game(0, national=["ESPN"]), game(1), game(2)]
    heat = local["miami-heat"]
    inside = build_state_coverage(games, "MIA", services, heat, IN_MARKET)
    assert local_counts(inside) == {"Local TV over the air": 2, "Local 10+ Platinum": 2}
    outside = build_state_coverage(games, "MIA", services, heat, OUT_OF_MARKET)
    assert local_counts(outside) == {}


# -- 2. confidence --------------------------------------------------------------

def test_high_confidence_counts(services, local):
    cov = build_state_coverage([game(0)], "MIA", services, local["miami-heat"], IN_MARKET)
    assert cov.cheapest_full is not None and cov.cheapest_full.total_price == 0


def test_moderate_confidence_counts_and_flags_the_combination(services, local):
    jazz = local["utah-jazz"]
    assert jazz.confidence == "moderate"
    games = [game(0), game(1)]
    cov = build_state_coverage(games, "UTA", services, jazz, IN_MARKET)
    assert [s.name for s in cov.cheapest_full.services] == ["Local TV over the air"]
    hits = moderate_carries_in(cov.cheapest_full, games, "UTA", cov.service_data, jazz, IN_MARKET)
    assert [h["service"].name for h in hits] == ["Local TV over the air"]


@pytest.mark.parametrize("slug", ["golden-state-warriors", "dallas-mavericks", "la-clippers"])
def test_low_and_unknown_confidence_never_count(services, local, slug):
    assert local[slug].confidence in ("low", "unknown")
    assert local_services(local[slug], services) == []
    cov = build_state_coverage([game(0)], "GSW", services, local[slug], IN_MARKET)
    assert local_counts(cov) == {}
    assert cov.cheapest_full is None


def test_low_confidence_page_shows_broadcasters_and_the_line(built_site):
    inside = panel(built_site, "golden-state-warriors", "in_market")
    assert LOW_LINE in inside
    watching = page(built_site, "golden-state-warriors")
    watching = watching[watching.index("data-watching"):]
    assert "NBC Sports Bay Area" in watching
    assert LOW_LINE in watching


def test_unknown_confidence_page_shows_the_notes(built_site):
    notes = "The Clippers have not announced where local games will air in 2026-27."
    assert notes in panel(built_site, "la-clippers", "in_market")
    assert notes in page(built_site, "la-clippers")[page(built_site, "la-clippers").index("data-watching"):]


def test_moderate_note_renders_under_an_in_market_combination(built_site_priced, local):
    # The priced build gives NBA TV a price, so in-market combinations exist.
    # The note shows for moderate-confidence teams whose combination uses a
    # local option, never out-of-market and never for any other confidence.
    shown = []
    for slug, info in local.items():
        inside = panel(built_site_priced, slug, "in_market")
        outside = panel(built_site_priced, slug, "out_of_market")
        assert MODERATE_NOTE not in outside
        if MODERATE_NOTE in inside:
            assert info.confidence == "moderate"
            shown.append(slug)
    assert shown


# -- 3. over the air ------------------------------------------------------------

def test_ota_all_is_free_coverage(services, local):
    ota = [s for s in local_services(local["charlotte-hornets"], services) if s.id.endswith("-ota")]
    assert len(ota) == 1 and ota[0].has_price and ota[0].is_free


@pytest.mark.parametrize("slug,status", [("cleveland-cavaliers", "partial"),
                                         ("portland-trail-blazers", "most"),
                                         ("boston-celtics", "none"),
                                         ("denver-nuggets", "unknown")])
def test_other_ota_statuses_are_not_coverage(services, local, slug, status):
    assert local[slug].ota.status == status
    assert not any(s.id.endswith("-ota") for s in local_services(local[slug], services))


def test_partial_ota_renders_as_a_text_line(built_site):
    html = page(built_site, "cleveland-cavaliers")
    assert re.search(r"data-ota-note>15 games are also free over the air on Gray stations and RESN\.<", html)
    html = page(built_site, "portland-trail-blazers")
    assert "data-ota-note>Most local games are free over the air.<" in html


# -- 4. streaming ---------------------------------------------------------------

def test_shared_dazn_price(services, local):
    dazn = [s for s in local_services(local["charlotte-hornets"], services) if s.name == "DAZN"]
    assert dazn[0].monthly_price_usd == 19.99 and dazn[0].has_price


def test_null_price_is_listed_but_never_in_a_combination(services, local):
    nets = local["brooklyn-nets"]
    games = [game(0, team="BKN"), game(1, team="BKN")]
    cov = build_state_coverage(games, "BKN", services, nets, IN_MARKET)
    assert local_counts(cov) == {"YES on DAZN": 2}          # listed and counted
    assert cov.cheapest_full is None                         # but never priced


def test_zero_priced_streaming_is_free(services, local):
    app = [s for s in local_services(local["miami-heat"], services) if s.name == "Local 10+ Platinum"]
    assert app[0].is_free


def test_add_on_costs_its_price_plus_the_required_service(services, local):
    celtics = local["boston-celtics"]
    addon = local_services(celtics, services)[0]
    assert addon.name == "NBC Sports Boston on Peacock"
    assert addon.own_price_usd == 15.0
    assert addon.monthly_price_usd == round(15.0 + services.by_id("peacock_premium").price, 2)

    # One local game and one Peacock game: the add-on brings Peacock with it,
    # so it covers both, and the combination lists and charges Peacock once.
    games = [game(0), game(1, national=["Peacock"])]
    cov = build_state_coverage(games, "BOS", services, celtics, IN_MARKET)
    assert counts(cov)[addon.id] == 2
    combo = cov.cheapest_full
    assert [s.name for s in combo.services] == ["NBC Sports Boston on Peacock"]
    assert [s.id for s in combo.parts] == [addon.id, "peacock_premium"]
    assert combo.total_price == 27.99
    assert sum(s.list_price_usd for s in combo.parts) == pytest.approx(combo.total_price)

    # Local games only: Peacock is still paid for, because the add-on needs it.
    cov = build_state_coverage([game(0)], "BOS", services, celtics, IN_MARKET)
    assert cov.cheapest_full.total_price == 27.99


def test_add_on_renders_with_its_own_price_and_the_required_service(built_site_priced):
    inside = panel(built_site_priced, "boston-celtics", "in_market")
    cheapest = inside[inside.index("Cheapest way to watch"):inside.index("Services and prices")]
    assert '<span>NBC Sports Boston on Peacock</span><span class="price">$15</span>' in cheapest
    assert '<span>Peacock Premium</span><span class="price">$12.99</span>' in cheapest
    assert MODERATE_NOTE in cheapest


# -- 5. Raptors -----------------------------------------------------------------

def test_raptors_in_market_shows_notes_and_no_combination(built_site_priced, local):
    raptors = local["toronto-raptors"]
    assert raptors.exclude_from_us_maths
    assert local_services(raptors, load_services()) == []
    inside = panel(built_site_priced, "toronto-raptors", "in_market")
    assert f"data-no-maths>{raptors.notes}<" in inside
    assert "combo-total" not in inside
    assert "combo-total" in panel(built_site_priced, "toronto-raptors", "out_of_market")


# -- 6. 'Watching in' section -----------------------------------------------------

def test_watching_section_renders_from_the_file(built_site):
    html = page(built_site, "boston-celtics")
    section = html[html.index("data-watching"):]
    section = section[:section.index("</section>")]
    assert "Watching in the Celtics market" in section
    assert "NBC Sports Boston" in section
    assert "NBC Sports Boston on Peacock" in section and "$15" in section
    assert "$15 a month add-on on top of a Peacock plan" in section
    assert "DirecTV Stream, Hulu + Live TV" in section
    assert "Celtics local market" in section
    assert "data-local-checked>Checked September 2026<" in section
    assert re.search(r"<details class=\"sources small\">\s*<summary>Sources</summary>", section)
    assert "https://www.nbcsportsboston.com/news/sports/faq-nbc-sports-boston-on-peacock/696847/" in section


def test_watching_section_is_on_every_team_page(built_site, teams):
    for team in teams:
        assert "data-watching" in page(built_site, team.slug), team.slug


# -- 7. hub ---------------------------------------------------------------------

def test_hub_lists_every_team_with_ota_all(built_site, local, teams):
    html = (built_site / "index.html").read_text(encoding="utf-8")
    line = re.search(r"<p class=\"small\" data-ota-teams>(.*?)</p>", html, re.S).group(1)
    listed = re.findall(r">([^<]+)</a>", line)
    expected = [t.full_name for t in teams if local[t.slug].ota.status == "all"]
    assert listed == expected
    assert "Miami Heat" in listed and "Cleveland Cavaliers" not in listed
