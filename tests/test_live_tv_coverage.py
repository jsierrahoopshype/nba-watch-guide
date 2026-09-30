"""Live TV packages in the coverage maths: a channel carried at high or
moderate confidence in a package's lineup counts, unchecked and not carried
never do, local ABC and NBC marked "depends on ZIP" count with a note, and
the "What am I missing?" matrix includes the packages."""

from __future__ import annotations

import json
import re
from datetime import date

import pytest

from conftest import TODAY, _build, _copy_data
from watchguide.context import load_context
from watchguide.coverage import (IN_MARKET, OUT_OF_MARKET, STATES, build_state_coverage, carriers_for_game,
                                 moderate_carries_in, relies_on_zip, via_zip)
from watchguide.missing import answer, payload
from watchguide.model import Game, load_local_tv, load_services
from watchguide.pages.team import _confidence_lines, _row_notes

TEAM = "LAC"                 # unknown local confidence: no local options muddy the counts
ZIP_NOTE = "Local ABC and NBC availability varies by ZIP code."


def game(i: int, national=()) -> Game:
    day = date(2027, 1, 15 + i).isoformat()
    return Game(game_id=f"00226{i:05d}", game_code="x", date_et=day, tipoff_et=f"{day}T19:00:00-05:00",
                tipoff_utc=f"{day}T00:00:00+00:00", status_text="", home_tricode=TEAM, away_tricode="DAL",
                national=list(national))


def data_with(tmp_path_factory, label, edit):
    """A copy of data/ whose services.json lineups pass through edit(pkg_label, channel_entry)."""
    data_dir = _copy_data(tmp_path_factory, label)
    raw = json.loads((data_dir / "services.json").read_text(encoding="utf-8"))
    for svc in raw["services"]:
        for pkg in (svc.get("lineup") or {}).get("packages", []):
            for ch in pkg["channels"]:
                edit(pkg["label"], ch)
    (data_dir / "services.json").write_text(json.dumps(raw), encoding="utf-8")
    return data_dir


@pytest.fixture(scope="module")
def shipped():
    return load_services()


# -- a carried channel counts --------------------------------------------------------------

def test_a_carried_channel_counts_for_its_games(shipped):
    games = [game(0, ["ESPN"]), game(1, ["NBA TV"]), game(2)]
    cov = build_state_coverage(games, TEAM, shipped, None, OUT_OF_MARKET)
    counts = {c.service.id: c.covered for c in cov.per_service}
    assert counts["youtube_tv"] == 2                   # ESPN and NBA TV, not the local game
    assert counts["hulu_live_tv"] == 1                 # ESPN only: its lineup has NBA TV not carried
    assert counts["fubo"] == 1                         # NBA TV on Fubo Pro is unchecked
    assert counts["fubo_elite"] == 2


def test_live_tv_makes_a_full_in_market_season_possible(shipped):
    """In-market, League Pass is blacked out and NBA TV alone has no price, so
    before the lineups counted an NBA TV game had no priced carrier."""
    games = [game(0, ["NBA TV"]), game(1, ["ESPN"])]
    cov = build_state_coverage(games, TEAM, shipped, None, IN_MARKET)
    assert cov.cheapest_full is not None
    assert [s.id for s in cov.cheapest_full.services] == ["youtube_tv_sports_plan"]


# -- unchecked and not carried never count --------------------------------------------------

def test_unchecked_and_not_carried_never_count(tmp_path_factory):
    def edit(label, ch):
        if ch["channel"] == "ESPN" and label == "YouTube TV":
            ch.update({"status": "unchecked", "confidence": "", "sources": [], "checked": ""})
        if ch["channel"] == "ESPN" and label == "DirecTV":
            ch["status"] = "not_carried"                  # sources and confidence kept: still no
        if ch["channel"] == "ESPN" and label == "Hulu + Live TV":
            ch["status"] = "zip_dependent"                 # the ZIP rule is for ABC and NBC only
        if ch["channel"] == "NBC Sports Boston":           # regional networks stay out
            ch.update({"status": "carried", "confidence": "moderate", "checked": "2026-09-30",
                       "sources": [{"url": "https://thestreamable.com/a", "published": "2026"},
                                   {"url": "https://www.antennaland.com/b", "published": "2026"}]})
    services = load_services(data_with(tmp_path_factory, "data-never-count", edit))
    carriers = carriers_for_game(game(0, ["ESPN"]), TEAM, services, None, OUT_OF_MARKET)
    assert not {"youtube_tv", "directv_stream", "hulu_live_tv"} & carriers
    assert "youtube_tv_sports_plan" in carriers        # untouched package still counts
    for svc in services.services:
        assert "NBC Sports Boston" not in svc.carries


def test_an_entry_below_its_confidence_rule_never_counts(tmp_path_factory):
    """Carried but with one source: the loader recomputes the confidence and drops it."""
    def edit(label, ch):
        if label == "Sling Orange" and ch["channel"] in ("ESPN", "ESPN2"):
            ch["sources"] = ch["sources"][:1]
    services = load_services(data_with(tmp_path_factory, "data-one-source", edit))
    assert "ESPN" not in services.by_id("sling_tv").carries


# -- local ABC and NBC depend on the ZIP code -------------------------------------------------

def test_zip_dependent_abc_and_nbc_count_for_national_abc_and_nbc_games(shipped):
    abc, nbc, espn = game(0, ["ABC"]), game(1, ["NBC", "Peacock"]), game(2, ["ESPN"])
    for g in (abc, nbc):
        assert "youtube_tv" in carriers_for_game(g, TEAM, shipped, None, OUT_OF_MARKET)
    yt = shipped.by_id("youtube_tv")
    assert via_zip(yt, abc) and via_zip(yt, nbc) and not via_zip(yt, espn)
    sling = shipped.by_id("sling_tv")                  # Blue's local NBC; Orange has no locals
    assert "sling_tv" in carriers_for_game(nbc, TEAM, shipped, None, OUT_OF_MARKET)
    assert "sling_tv" not in carriers_for_game(abc, TEAM, shipped, None, OUT_OF_MARKET)
    assert via_zip(sling, nbc)


def test_zip_note_only_when_a_figure_relies_on_it(shipped):
    games = [game(0, ["ABC"]), game(1, ["ESPN"])]
    yt, antenna = shipped.by_id("youtube_tv"), shipped.by_id("antenna_abc")
    assert relies_on_zip([yt], games, TEAM, shipped, None, OUT_OF_MARKET)
    # With the antenna in the same combination the ABC game does not rely on YouTube TV.
    assert not relies_on_zip([yt, antenna], games, TEAM, shipped, None, OUT_OF_MARKET)
    # A missed game does not count.
    assert not relies_on_zip([yt], games, TEAM, shipped, None, OUT_OF_MARKET, skip={games[0].game_id})


def test_zip_and_check_notes_on_rows_and_combinations(fixture_games, shipped):
    ctx = load_context(fixture_games, today=TODAY)
    games = [game(0, ["ABC"]), game(1, ["ESPN"]), game(2, ["NBA TV"])]
    cov = build_state_coverage(games, TEAM, shipped, None, OUT_OF_MARKET)
    rows = _row_notes(ctx, cov, games, TEAM, None, OUT_OF_MARKET, cov.service_data)
    assert rows["youtube_tv"] == ["Includes ABC, ESPN, NBA TV games through YouTube TV; check before you buy.",
                                  ZIP_NOTE]
    assert rows["hulu_live_tv"] == ["Includes ABC, ESPN games through Hulu + Live TV; check before you buy.",
                                    ZIP_NOTE]
    assert "espn_unlimited" not in rows                # not a moderate carrier
    lines = _confidence_lines(ctx, cov.cheapest_full, games, TEAM, None, OUT_OF_MARKET, cov.service_data)
    if any(s.kind == "live_tv" for s in cov.cheapest_full.services):
        assert any(line.startswith("Includes ") for line in lines)
    uses_zip = relies_on_zip(cov.cheapest_full.services, games, TEAM, cov.service_data, None, OUT_OF_MARKET)
    assert (ZIP_NOTE in lines) == uses_zip


def test_moderate_lines_name_only_the_moderate_channels_used(shipped):
    games = [game(0, ["ESPN"]), game(1)]
    cov = build_state_coverage(games, TEAM, shipped, None, OUT_OF_MARKET)
    only_yt = type(cov.cheapest_full)(services=[shipped.by_id("youtube_tv")], total_price=0, covered=1,
                                      total=2, missed=[games[1]])
    hits = moderate_carries_in(only_yt, games, TEAM, shipped, None, OUT_OF_MARKET)
    assert [(h["service"].id, h["channels"]) for h in hits] == [("youtube_tv", ["ESPN"])]


def test_team_pages_show_the_notes(built_site):
    page = (built_site / "boston-celtics" / "index.html").read_text(encoding="utf-8")
    coverage = page[page.index('id="panel-out_of_market"'):]
    coverage = coverage[:coverage.index("Cheapest way to watch")]
    row = coverage[coverage.index(">YouTube TV<"):]
    row = row[:row.index('<div class="row-side">')]
    assert "check before you buy." in row and ZIP_NOTE in row


# -- the widget matrix -------------------------------------------------------------------------

def test_widget_matrix_includes_live_tv_packages(fixture_games, shipped):
    local = load_local_tv()["miami-heat"]
    games = [g for g in fixture_games if g.involves("MIA")]
    covs = {s: build_state_coverage(games, "MIA", shipped, local, s) for s in STATES}
    data = payload([{"d": g.date_et, "o": g.game_id} for g in games], covs, "Antenna")
    options = {o["id"]: o for o in data["options"]}
    live = [s for s in shipped.services if s.kind == "live_tv"]
    for svc in live:
        assert svc.id in options, svc.id
        for state in STATES:
            mask = next(c.mask for c in covs[state].per_service if c.service.id == svc.id)
            assert int(options[svc.id]["m"][state], 16) == mask
    assert options["fubo_elite"]["price"] is None       # tickable, never recommended
    assert options["youtube_tv"]["price"] == 82.99
    # Owning YouTube TV answers every ESPN, ABC, NBC and NBA TV game on the list.
    national = [i for i, g in enumerate(games) if set(g.national_codes) & {"ESPN", "ABC", "NBC", "NBA TV"}]
    result = answer(data, OUT_OF_MARKET, {"youtube_tv"})
    assert national and not set(national) & set(result["missing"])


def test_team_page_embeds_live_tv_options(built_site):
    page = (built_site / "miami-heat" / "index.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r'<script type="application/json" id="missing-data">(.*?)</script>', page,
                                re.S).group(1))["data"]
    ids = {o["id"] for o in data["options"]}
    assert {"youtube_tv", "youtube_tv_sports_plan", "hulu_live_tv", "sling_tv", "fubo", "fubo_elite",
            "directv_stream"} <= ids


# -- over-the-air entries are named as free ----------------------------------------------------

def test_every_over_the_air_entry_says_free_over_the_air(shipped):
    from watchguide.coverage import local_services
    ota = [s for s in shipped.services if s.kind == "ota"]
    assert [s.name for s in ota] == ["ABC (free over the air)", "NBC (free over the air)"]
    heat = local_services(load_local_tv()["miami-heat"], shipped)
    assert [s.name for s in heat if s.kind == "ota"] == ["Local TV (free over the air)"]
