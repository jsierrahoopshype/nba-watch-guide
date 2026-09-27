"""Most star power tonight: the score, the lines, the fallback and the refresh."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from conftest import TODAY, _build
from watchguide import config
from watchguide.model import load_copy, load_teams
from watchguide.ranking import rank, team_stars
from watchguide.sources import careers
from watchguide.sources.careers import match_key, rosters_from

TEXT = load_copy()["tonight"]
FULL = {t.full_name: t.tricode for t in load_teams()}


def test_match_key_lines_up_names_across_sources():
    assert match_key("V. J. Edgecombe") == match_key("VJ Edgecombe") == "vj edgecombe"
    assert match_key("Nikola Jokić") == match_key("Nikola Jokic")
    assert match_key("Jaren Jackson Jr.") == match_key("Jaren Jackson")
    assert match_key("P.J. Washington") == match_key("PJ Washington")


def test_rosters_come_from_the_present_stint():
    records = [
        {"player": "A One", "status": "nba_active", "all_star_count": 3,
         "career_history": [{"years": "2015-2020", "team": "Boston Celtics"},
                            {"years": "2020–present", "team": "Miami Heat"}]},
        {"player": "B Two", "status": "nba_active", "all_star_count": None,
         "career_history": [{"years": "2024–present", "team": "Some Overseas Club"}]},
        {"player": "C Three", "status": "retired", "all_star_count": 9,
         "career_history": [{"years": "2000–present", "team": "Miami Heat"}]},
    ]
    built = rosters_from(records, FULL)
    assert built["teams"] == {"MIA": [{"player": "A One", "all_star": 3}]}
    assert (built["active"], built["placed"]) == (2, 1)


def test_out_and_doubtful_do_not_count_questionable_does():
    roster = [{"player": "Star A", "all_star": 5}, {"player": "Star B", "all_star": 3},
              {"player": "Star C", "all_star": 2}, {"player": "Bench D", "all_star": 0}]
    injuries = [{"player": "Star A", "status": "Out"}, {"player": "Star B", "status": "Doubtful"},
                {"player": "Star C", "status": "Questionable"}]
    assert team_stars(roster, injuries) == (2, ["Star A", "Star B"], 3)


def _games(fixture_games):
    today = [g for g in fixture_games if g.date_et == TODAY]
    national = next(g for g in today if g.is_national)
    local = next(g for g in today if not g.is_national)
    return national, local


def test_national_tv_adds_its_points_and_ties_go_to_the_earlier_tip(fixture_games):
    national, local = _games(fixture_games)
    rows = rank([local, national], {}, {}, lambda t: t, TEXT)
    assert rows[0]["game"] is national
    assert rows[0]["score"] == config.RANK_NATIONAL_POINTS and rows[1]["score"] == 0


def test_each_game_gets_one_plain_line(fixture_games):
    national, local = _games(fixture_games)
    rosters = {national.home_tricode: [{"player": "Star A", "all_star": 7}],
               local.home_tricode: [{"player": "Star B", "all_star": 4}, {"player": "Star C", "all_star": 1}]}
    injuries = {local.home_tricode: [{"player": "Star B", "status": "Out"}]}
    rows = {r["game"].game_id: r for r in rank([national, local], rosters, injuries, lambda t: t, TEXT)}
    codes = " and ".join(national.national_codes)
    assert rows[national.game_id]["line"] == (
        f"7 All-Star selections in uniform, no All-Star listed out or doubtful, national TV on {codes}.")
    assert rows[local.game_id]["line"] == "1 All-Star selections in uniform, Star B listed out or doubtful."


def test_no_betting_language_anywhere():
    words = json.dumps(TEXT).lower()
    for word in ("odds", "bet", "spread", "favorite", "predict", "pick"):
        assert word not in words


# -- career map fallback ----------------------------------------------------------

def test_a_failed_fetch_keeps_the_last_good_copy(tmp_path, monkeypatch):
    cache = tmp_path / careers.CACHE
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"fetched_at": "2026-09-26T12:00:00+00:00",
                                 "teams": {"MIA": [{"player": "A", "all_star": 1}]}}), encoding="utf-8")

    def boom(*a, **k):
        raise RuntimeError("raw.githubusercontent.com is down")

    monkeypatch.setattr(careers, "get", boom)
    teams, note = careers.load(tmp_path, FULL)
    assert teams == {"MIA": [{"player": "A", "all_star": 1}]}
    assert "kept the copy from 2026-09-26" in note


def test_an_implausible_file_keeps_the_last_good_copy(tmp_path, monkeypatch):
    cache = tmp_path / careers.CACHE
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"fetched_at": "x", "teams": {"BOS": []}}), encoding="utf-8")
    monkeypatch.setattr(careers, "get", lambda *a, **k: [])
    teams, note = careers.load(tmp_path, FULL)
    assert teams == {"BOS": []} and "placed only 0" in note
    assert json.loads(cache.read_text(encoding="utf-8"))["fetched_at"] == "x"      # not overwritten


def test_no_copy_at_all_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(careers, "get", lambda *a, **k: {"not": "a list"})
    teams, note = careers.load(tmp_path, FULL)
    assert teams == {} and "star power is left out" in note


# -- the pages ---------------------------------------------------------------------

def _roster_for(fixture_games):
    """Stars for two of today's games, big enough that national TV cannot flip them."""
    today = sorted((g for g in fixture_games if g.date_et == TODAY), key=lambda g: g.game_id)
    first, second = today[0], today[1]
    teams = {first.home_tricode: [{"player": "Star One", "all_star": 30}],
             second.home_tricode: [{"player": "Star Two", "all_star": 20}]}
    return first, second, teams


@pytest.fixture(scope="module")
def ranked_site(tmp_path_factory, fixture_games):
    first, second, teams = _roster_for(fixture_games)
    site = tmp_path_factory.mktemp("ranked-site")
    (site / "data").mkdir()
    (site / careers.CACHE).write_text(json.dumps({"fetched_at": "t", "teams": teams}), encoding="utf-8")
    from watchguide.build import full_build
    from dataclasses import asdict
    (site / "data" / "schedule.json").write_text(json.dumps({
        "season": "2026-27", "updated_at": TODAY, "count": len(fixture_games),
        "games": [asdict(g) for g in fixture_games]}), encoding="utf-8")
    full_build(site, today=TODAY, offline=True)
    return site, first, second


def _order(site):
    html = (site / "tonight" / "index.html").read_text(encoding="utf-8")
    block = html[html.index("data-ranked"):html.index("</ol>")]
    return re.findall(r"<strong>([^<]+)</strong>", block), block


def test_tonight_page_ranks_every_game(ranked_site, fixture_games):
    site, first, second = ranked_site
    order, block = _order(site)
    assert len(order) == sum(1 for g in fixture_games if g.date_et == TODAY)
    names = {t.tricode: t.full_name for t in load_teams()}
    assert order[0] == f"{names[first.away_tricode]} at {names[first.home_tricode]}"
    assert order[1] == f"{names[second.away_tricode]} at {names[second.home_tricode]}"
    ranks = [int(r) for r in re.findall(r'data-rank="(\d+)"', block)]
    scores = [int(s) for s in re.findall(r'data-score="(\d+)"', block)]
    assert ranks == list(range(1, len(ranks) + 1)) and scores == sorted(scores, reverse=True)
    assert "30 All-Star selections in uniform" in block


def test_hub_teaser_shows_the_top_three(ranked_site):
    site, *_ = ranked_site
    hub = (site / "index.html").read_text(encoding="utf-8")
    teaser = hub[hub.index("data-top3"):hub.index("</section>", hub.index("data-top3"))]
    assert "Most star power tonight" in teaser
    assert "Ranked by career All-Star selections of the players in uniform tonight, plus national TV." in teaser
    assert teaser.count("<li>") == 3
    assert 'href="/how-to-watch/tonight"' in teaser
    tonight_order, _ = _order(site)
    assert re.findall(r'<a href="/how-to-watch/tonight">([^<]+)</a> <span', teaser) == tonight_order[:3]


def test_an_injury_on_the_refresh_moves_a_game_down(ranked_site, tmp_path, monkeypatch):
    site, first, second = ranked_site
    from watchguide.build import refresh_build
    from watchguide.sources import injuries as injuries_source
    order_before, _ = _order(site)
    rows = [{"player": "Star One", "status": "Out", "injury": "Ankle", "date": TODAY}]
    monkeypatch.setattr(injuries_source, "fetch_raw", lambda: rows)
    monkeypatch.setattr(injuries_source, "fetch_player_teams", lambda: {"star one": first.home_tricode})
    outcome = refresh_build(site, today=TODAY, repo_root=tmp_path)
    assert any("refreshed" in n for n in outcome.notes)
    order_after, block = _order(site)
    names = {t.tricode: t.full_name for t in load_teams()}
    first_name = f"{names[first.away_tricode]} at {names[first.home_tricode]}"
    second_name = f"{names[second.away_tricode]} at {names[second.home_tricode]}"
    assert order_before[:2] == [first_name, second_name]
    assert order_after[0] == second_name                          # Star One out: 30 points gone
    assert order_after.index(first_name) > 0
    assert "Star One listed out or doubtful" in block
    # The hub teaser is refreshed with it.
    hub = (site / "index.html").read_text(encoding="utf-8")
    teaser = hub[hub.index("data-top3"):]
    assert teaser.index(second_name) < teaser.index("</ol>")
    assert re.findall(r'<a href="/how-to-watch/tonight">([^<]+)</a> <span', teaser)[0] == second_name


def test_the_ranking_is_called_star_power_everywhere(ranked_site):
    site, *_ = ranked_site
    tonight = (site / "tonight" / "index.html").read_text(encoding="utf-8")
    hub = (site / "index.html").read_text(encoding="utf-8")
    assert "<h2>Most star power tonight</h2>" in tonight
    basis = "Ranked by career All-Star selections of the players in uniform tonight, plus national TV."
    # The line sits under the list, not above it.
    assert tonight.index("</ol>", tonight.index("data-ranked")) < tonight.index(basis)
    copy_text = (Path(__file__).resolve().parent.parent / "data" / "copy.json").read_text(encoding="utf-8")
    for text in (tonight, hub, copy_text):
        assert "best games" not in text.lower()
