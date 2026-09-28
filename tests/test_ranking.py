"""Tonight's ranking: star power from recent awards, stakes from records,
the heading switch, the fallback and the refresh."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from conftest import TODAY, _copy_data
from watchguide.model import load_copy, load_teams
from watchguide.ranking import (STAKES, STARS, load_weights, mode, player_star_power, rank,
                                stakes_score, team_records, team_star_power)
from watchguide.sources import careers
from watchguide.sources.careers import match_key, rosters_from

ROOT = Path(__file__).resolve().parent.parent
TEXT = load_copy()["tonight"]
FULL = {t.full_name: t.tricode for t in load_teams()}
NAMES = {t.tricode: t.full_name for t in load_teams()}
W = load_weights()


def award(player, season, kind):
    return {"player": player, "season": season, "award": kind}


# -- the weights file ----------------------------------------------------------------

def test_weights_file_holds_every_number():
    raw = json.loads((ROOT / "data" / "star_power_weights.json").read_text(encoding="utf-8"))
    assert raw["seasons"] == {"2025-26": 1.0, "2024-25": 0.5, "2023-24": 0.25}
    assert raw["points"] == {"all_nba_first": 5, "all_nba_second": 4, "all_nba_third": 3, "all_star": 2}
    assert raw["stakes"]["min_games"] == 5
    for key in ("win_pct_points", "close_bonus", "close_within"):
        assert isinstance(raw["stakes"][key], (int, float))


def test_editing_the_weights_file_changes_the_score(tmp_path):
    data = _write_data(tmp_path)
    raw = json.loads((data / "star_power_weights.json").read_text(encoding="utf-8"))
    raw["points"]["all_star"] = 10
    (data / "star_power_weights.json").write_text(json.dumps(raw), encoding="utf-8")
    power = player_star_power([award("A", "2025-26", "all_star")], load_weights(data))
    assert power[match_key("A")]["score"] == 10


def _write_data(tmp_path):
    for name in ("star_power_weights.json",):
        (tmp_path / name).write_text((ROOT / "data" / name).read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


# -- star power ----------------------------------------------------------------------

def test_awards_stack_within_a_season():
    power = player_star_power([award("A", "2025-26", "all_nba_first"),
                               award("A", "2025-26", "all_star")], W)
    assert power[match_key("A")]["score"] == 5 + 2


def test_season_weights_and_the_three_season_window():
    power = player_star_power([
        award("A", "2025-26", "all_nba_second"),     # 4 x 1.0
        award("A", "2024-25", "all_nba_third"),      # 3 x 0.5
        award("A", "2023-24", "all_star"),           # 2 x 0.25
        award("A", "2022-23", "all_nba_first"),      # outside the window
        award("B", "2019-20", "all_star"),           # nothing in the window
    ], W)
    assert power[match_key("A")]["score"] == pytest.approx(4 + 1.5 + 0.5)
    assert match_key("B") not in power


def test_out_and_doubtful_do_not_count_questionable_does():
    power = player_star_power([award("Star A", "2025-26", "all_nba_first"),
                               award("Star B", "2025-26", "all_star"),
                               award("Star C", "2025-26", "all_star")], W)
    roster = [{"player": p, "all_star": 0} for p in ("Star A", "Star B", "Star C", "Bench D")]
    injuries = [{"player": "Star A", "status": "Out"}, {"player": "Star B", "status": "Doubtful"},
                {"player": "Star C", "status": "Questionable"}]
    got = team_star_power(roster, injuries, power)
    assert got["score"] == 2
    assert got["best"] == "Star C"          # the best player in uniform
    assert got["out"] == ["Star A"]         # listed Out; Doubtful gets no note


def test_award_names_match_through_aliases():
    power = player_star_power([award("Herbert Jones", "2025-26", "all_star")], W)
    got = team_star_power([{"player": "Herb Jones", "all_star": 0}], [], power)
    assert got["score"] == 2


# -- records and stakes ----------------------------------------------------------------

def _game(fixture_games, idx=0):
    return sorted((g for g in fixture_games if g.date_et == TODAY), key=lambda g: g.game_id)[idx]


def test_current_record_is_the_most_games_played(fixture_games):
    g = _game(fixture_games)
    early = replace(g, game_id="a", home_wins=1, home_losses=0, away_wins=0, away_losses=1)
    later = replace(g, game_id="b", home_wins=6, home_losses=2, away_wins=3, away_losses=5)
    future = replace(g, game_id="c", home_wins=None, home_losses=None, away_wins=None, away_losses=None)
    records = team_records([early, later, future])
    assert records[g.home_tricode] == (6, 2) and records[g.away_tricode] == (3, 5)


def test_no_stakes_until_both_teams_have_played_five():
    assert stakes_score((4, 0), (3, 2), W) is None          # away has played 4
    assert stakes_score((5, 0), (3, 2), W) is not None
    assert stakes_score(None, (3, 2), W) is None


def test_stakes_formula_uses_the_weights_file():
    s = W["stakes"]
    far = stakes_score((9, 1), (2, 8), W)                   # .900 and .200
    assert far == pytest.approx(s["win_pct_points"] * 1.1)
    close = stakes_score((9, 2), (8, 3), W)                 # .818 and .727, within .1
    assert close == pytest.approx(s["win_pct_points"] * (9 / 11 + 8 / 11) + s["close_bonus"])


# -- the ranking -------------------------------------------------------------------------

def _two_games(fixture_games):
    national = next(g for g in fixture_games if g.date_et == TODAY and g.is_national)
    local = next(g for g in fixture_games if g.date_et == TODAY and not g.is_national)
    return national, local


def test_national_tv_is_a_badge_not_points(fixture_games):
    national, local = _two_games(fixture_games)
    rows = rank([national, local], {}, {}, lambda t: t, TEXT, W, [])
    assert all(r["score"] == 0 for r in rows)
    assert next(r for r in rows if r["game"] is national)["national"] == national.national_codes
    assert rows[0]["game"].tipoff_utc <= rows[1]["game"].tipoff_utc      # ties by tip-off


def test_before_the_threshold_the_ranking_is_star_power_only(fixture_games):
    national, local = _two_games(fixture_games)
    awards = [award("Star A", "2025-26", "all_nba_first")]
    rosters = {local.home_tricode: [{"player": "Star A", "all_star": 0}]}
    early = [replace(local, home_wins=3, home_losses=1, away_wins=4, away_losses=0), national]
    rows = rank(early, rosters, {}, lambda t: t, TEXT, W, awards)
    assert [r["stakes"] for r in rows] == [None, None]
    assert rows[0]["game"].game_id == local.game_id and rows[0]["score"] == 5
    assert rows[0]["line"] == "Star A"      # only one side has an award winner in uniform


def test_with_stakes_the_line_names_both_records(fixture_games):
    national, local = _two_games(fixture_games)
    awards = [award("Star A", "2025-26", "all_nba_first"), award("Star B", "2025-26", "all_nba_third")]
    rosters = {local.home_tricode: [{"player": "Star A", "all_star": 0}],
               local.away_tricode: [{"player": "Star B", "all_star": 0}]}
    game = replace(local, home_wins=8, home_losses=3, away_wins=9, away_losses=2)
    row = rank([game], rosters, {}, lambda t: t, TEXT, W, awards)[0]
    assert row["stakes"] is not None
    assert row["line"] == "9-2 vs. 8-3: Star B vs. Star A"      # away first
    assert row["score"] == pytest.approx(8 + row["stakes"], abs=0.01)


def test_heading_switches_when_most_games_have_stakes(fixture_games):
    national, local = _two_games(fixture_games)
    played = lambda g: replace(g, home_wins=5, home_losses=5, away_wins=6, away_losses=4)
    off = rank([national, local], {}, {}, lambda t: t, TEXT, W, [])
    half = rank([played(national), local], {}, {}, lambda t: t, TEXT, W, [])
    most = rank([played(national), played(local)], {}, {}, lambda t: t, TEXT, W, [])
    assert (mode(off, W), mode(half, W), mode(most, W)) == (STARS, STARS, STAKES)


def test_no_betting_language_anywhere():
    words = json.dumps(TEXT).lower()
    for word in ("odds", "bet ", "spread", "favorite", "predict", " pick"):
        assert word not in words


# -- rosters and matching --------------------------------------------------------------

def test_match_key_lines_up_names_across_sources():
    assert match_key("V. J. Edgecombe") == match_key("VJ Edgecombe") == "vj edgecombe"
    assert match_key("Nikola Jokić") == match_key("Nikola Jokic")
    assert match_key("Jaren Jackson Jr.") == match_key("Jaren Jackson")


def test_rosters_come_from_the_present_stint():
    records = [
        {"player": "A One", "status": "nba_active", "all_star_count": 3,
         "career_history": [{"years": "2015-2020", "team": "Boston Celtics"},
                            {"years": "2020–present", "team": "Miami Heat"}]},
        {"player": "B Two", "status": "nba_active", "career_history": [{"years": "2024–present", "team": "Overseas"}]},
        {"player": "C Three", "status": "retired", "career_history": [{"years": "2000–present", "team": "Miami Heat"}]},
    ]
    built = rosters_from(records, FULL)
    assert built["teams"] == {"MIA": [{"player": "A One", "all_star": 3}]}
    assert (built["active"], built["placed"]) == (2, 1)


def test_a_failed_fetch_keeps_the_last_good_copy(tmp_path, monkeypatch):
    cache = tmp_path / careers.CACHE
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"fetched_at": "2026-09-26T12:00:00+00:00",
                                 "teams": {"MIA": [{"player": "A", "all_star": 1}]}}), encoding="utf-8")

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(careers, "get", boom)
    teams, note = careers.load(tmp_path, FULL)
    assert teams == {"MIA": [{"player": "A", "all_star": 1}]} and "kept the copy" in note


def test_no_copy_at_all_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(careers, "get", lambda *a, **k: {"not": "a list"})
    teams, note = careers.load(tmp_path, FULL)
    assert teams == {} and "star power is left out" in note


# -- the pages -----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ranked_site(tmp_path_factory, fixture_games):
    """Two of today's games get a star each, big enough that nothing else flips them."""
    today = sorted((g for g in fixture_games if g.date_et == TODAY), key=lambda g: g.game_id)
    first, second = today[0], today[1]
    data_dir = _copy_data(tmp_path_factory, "data-ranked")
    for name in ("star_power_weights.json", "player_aliases.json"):
        (data_dir / name).write_text((ROOT / "data" / name).read_text(encoding="utf-8"), encoding="utf-8")
    awards = [award("Star One", s, k) for s in ("2025-26", "2024-25", "2023-24")
              for k in ("all_nba_first", "all_star")]
    awards += [award("Star Two", "2025-26", "all_nba_second"), award("Star Two", "2025-26", "all_star")]
    (data_dir / "recent_awards.json").write_text(json.dumps({"awards": awards}), encoding="utf-8")
    site = tmp_path_factory.mktemp("ranked-site")
    (site / "data").mkdir()
    (site / careers.CACHE).write_text(json.dumps({"fetched_at": "t", "teams": {
        first.home_tricode: [{"player": "Star One", "all_star": 0}],
        second.home_tricode: [{"player": "Star Two", "all_star": 0}]}}), encoding="utf-8")
    (site / "data" / "schedule.json").write_text(json.dumps({
        "season": "2026-27", "updated_at": TODAY, "count": len(fixture_games),
        "games": [asdict(g) for g in fixture_games]}), encoding="utf-8")
    from watchguide.build import full_build
    full_build(site, today=TODAY, offline=True, data_dir=data_dir)
    return site, first, second, data_dir


def _order(site):
    html = (site / "tonight" / "index.html").read_text(encoding="utf-8")
    block = html[html.index("data-ranked"):html.index("</ol>", html.index("data-ranked"))]
    return re.findall(r"<strong>([^<]+)</strong>", block), html


def _name(g):
    return f"{NAMES[g.away_tricode]} at {NAMES[g.home_tricode]}"


def test_tonight_page_ranks_by_star_power(ranked_site, fixture_games):
    site, first, second, _ = ranked_site
    order, html = _order(site)
    assert order[:2] == [_name(first), _name(second)]
    assert len(order) == sum(1 for g in fixture_games if g.date_et == TODAY)
    assert "<h2 data-rank-heading>Most star power tonight</h2>" in html
    assert ("Ranked by All-NBA and All-Star selections over the last three seasons, recent seasons "
            "weighted more, counting only players in uniform tonight.") in html
    assert "badge badge-national" in html[html.index("data-ranked"):]


def _hub_order(site):
    hub = (site / "index.html").read_text(encoding="utf-8")
    block = hub[hub.index("data-hub-games"):hub.index("</section>", hub.index("data-hub-games"))]
    return [re.sub(r"<[^>]+>", "", t) for t in re.findall(r'<span class="hg-teams">(.*?)</span>', block)], block


def test_hub_list_follows_the_ranking(ranked_site):
    site, first, second, _ = ranked_site
    order, block = _hub_order(site)
    tonight, _ = _order(site)
    assert order == tonight
    assert order[:2] == [_name(first), _name(second)]
    assert "<h2 data-rank-heading>Most star power tonight</h2>" in block


def test_an_injury_on_the_refresh_moves_a_game_down(ranked_site, tmp_path, monkeypatch):
    site, first, second, data_dir = ranked_site
    from watchguide.build import refresh_build
    from watchguide.sources import injuries as injuries_source
    rows = [{"player": "Star One", "status": "Out", "injury": "Ankle", "date": TODAY}]
    monkeypatch.setattr(injuries_source, "fetch_raw", lambda: rows)
    monkeypatch.setattr(injuries_source, "fetch_player_teams", lambda: {"star one": first.home_tricode})
    refresh_build(site, today=TODAY, repo_root=tmp_path, data_dir=data_dir)
    order, html = _order(site)
    assert order[0] == _name(second)
    assert order.index(_name(first)) > 0
    assert "No recent All-NBA or All-Star players in uniform (Star One out)" in html
    # The hub is rewritten by the same refresh: new order, the line without
    # the out note, and Star One in the game's collapsed Out detail.
    hub_order, block = _hub_order(site)
    assert hub_order == order
    row = next(r for r in block.split('<li class="hg-row" ')[1:] if r.startswith(f'data-game="{first.game_id}"'))
    assert '<div class="hg-line small">No recent All-NBA or All-Star players in uniform</div>' in row
    assert "<summary>Out (1)</summary>" in row and "Star One" in row


def test_the_page_switches_heading_once_stakes_are_on(tmp_path_factory, fixture_games, ranked_site):
    _, _, _, data_dir = ranked_site
    played = [replace(g, home_wins=6, home_losses=4, away_wins=7, away_losses=3) for g in fixture_games]
    site = tmp_path_factory.mktemp("stakes-site")
    (site / "data").mkdir()
    (site / "data" / "schedule.json").write_text(json.dumps({
        "season": "2026-27", "updated_at": TODAY, "count": len(played),
        "games": [asdict(g) for g in played]}), encoding="utf-8")
    from watchguide.build import full_build
    full_build(site, today=TODAY, offline=True, data_dir=data_dir)
    html = (site / "tonight" / "index.html").read_text(encoding="utf-8")
    assert "<h2 data-rank-heading>Tonight&#39;s best games</h2>" in html
    assert ("Ranked by team records and All-NBA and All-Star selections over the last three seasons, "
            "counting only players in uniform tonight.") in html
    assert "7-3 vs. 6-4: " in html
    hub = (site / "index.html").read_text(encoding="utf-8")
    assert "<h2 data-rank-heading>Tonight&#39;s best games</h2>" in hub



# -- the line ------------------------------------------------------------------------------

def _pair(fixture_games):
    return sorted((g for g in fixture_games if g.date_et == TODAY), key=lambda g: g.game_id)[0]


def _line_for(fixture_games, away_players, home_players, awards, injuries=(), records=None):
    g = _pair(fixture_games)
    if records:
        g = replace(g, away_wins=records[0][0], away_losses=records[0][1],
                    home_wins=records[1][0], home_losses=records[1][1])
    rosters = {g.away_tricode: [{"player": p, "all_star": 0} for p in away_players],
               g.home_tricode: [{"player": p, "all_star": 0} for p in home_players]}
    inj = {}
    for name, status in injuries:
        side = g.away_tricode if name in away_players else g.home_tricode
        inj.setdefault(side, []).append({"player": name, "status": status})
    return rank([g], rosters, inj, lambda t: t, TEXT, W, awards)[0]["line"]


def test_names_the_best_player_in_uniform_on_each_side(fixture_games):
    awards = [award("Shai Gilgeous-Alexander", "2025-26", "all_nba_first"),
              award("Jalen Williams", "2025-26", "all_star"),
              award("Nikola Jokić", "2025-26", "all_nba_first")]
    line = _line_for(fixture_games, ["Jalen Williams", "Shai Gilgeous-Alexander"], ["Nikola Jokić"], awards)
    assert line == "Shai Gilgeous-Alexander vs. Nikola Jokić"


def test_records_lead_when_stakes_are_on(fixture_games):
    awards = [award("Shai Gilgeous-Alexander", "2025-26", "all_nba_first"),
              award("Nikola Jokić", "2025-26", "all_nba_first")]
    line = _line_for(fixture_games, ["Shai Gilgeous-Alexander"], ["Nikola Jokić"], awards,
                     records=[(9, 1), (8, 2)])
    assert line == "9-1 vs. 8-2: Shai Gilgeous-Alexander vs. Nikola Jokić"


def test_a_top_three_player_out_is_noted_a_fourth_is_not(fixture_games):
    stars = ["P One", "P Two", "P Three", "P Four"]
    awards = [award(p, "2025-26", "all_nba_first") for p in stars[:1]]
    awards += [award(p, "2025-26", "all_nba_second") for p in stars[1:2]]
    awards += [award(p, "2025-26", "all_nba_third") for p in stars[2:3]]
    awards += [award("P Four", "2025-26", "all_star")]
    line = _line_for(fixture_games, stars, [], awards, injuries=[("P One", "Out"), ("P Four", "Out")])
    assert line == "P Two (P One out)"
    doubtful = _line_for(fixture_games, stars, [], awards, injuries=[("P One", "Doubtful")])
    assert doubtful == "P Two"


def test_long_lines_fall_back_to_surnames_and_stay_under_80(fixture_games):
    away = ["Giannis Antetokounmpo", "Karl-Anthony Towns"]
    home = ["Shai Gilgeous-Alexander", "Alexander-Walker Nickeil-Longname"]
    awards = [award(p, "2025-26", "all_nba_first") for p in away + home]
    line = _line_for(fixture_games, away, home, awards,
                     injuries=[("Karl-Anthony Towns", "Out"), ("Alexander-Walker Nickeil-Longname", "Out")],
                     records=[(10, 2), (11, 1)])
    assert len(line) <= 80, line
    assert line.startswith("10-2 vs. 11-1: Antetokounmpo vs. Gilgeous-Alexander")


def test_nobody_in_uniform(fixture_games):
    line = _line_for(fixture_games, ["Star A"], [], [award("Star A", "2025-26", "all_star")],
                     injuries=[("Star A", "Out")])
    assert line == "No recent All-NBA or All-Star players in uniform (Star A out)"
