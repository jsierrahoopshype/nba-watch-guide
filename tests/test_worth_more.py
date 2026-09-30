"""Three more "Also worth knowing" lines: tonight's referee crew, revenge
games and the two stars' career head-to-head. Each line's presence and
absence, the four-line cap and its priority order, the referee date match,
Out players left out of revenge lines, links only to pages that exist, which
lines are data-volatile, and the loaders' caching."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, replace
from datetime import date, timedelta

import pytest

from conftest import TODAY, _copy_data, fixture_schedule
from watchguide import lastmod, worth
from watchguide.build import full_build, star_pairs
from watchguide.context import load_context
from watchguide.model import load_teams
from watchguide.pairs import game_pair_slug
from watchguide.sources import careers, matchups, referees
from watchguide.sources.careers import match_key
from watchguide.sources.http import FetchError

BY_TRICODE = {t.tricode: t for t in load_teams()}
GAMES = fixture_schedule()
GAME = next(g for g in GAMES if g.date_et == TODAY)          # BOS at ATL today
AWAY, HOME = GAME.away_tricode, GAME.home_tricode
LATER = next(g for g in GAMES if g.date_et > TODAY and {g.away_tricode, g.home_tricode} == {AWAY, HOME})
# A pair whose next meeting is tomorrow: its pair page's block is not on game day.
TOMORROW = next(g for g in GAMES if g.date_et == (date.fromisoformat(TODAY) + timedelta(days=1)).isoformat()
                and not any(o.date_et == TODAY and {o.away_tricode, o.home_tricode} ==
                            {g.away_tricode, g.home_tricode} for o in GAMES))
REF_URL = "https://hoopsmatic.com/referees/referee/{}/index.html"
PAIR = "anna-alpha-vs-bea-beta"


def day(offset: int) -> str:
    return (date.fromisoformat(TODAY) + timedelta(days=offset)).isoformat()


def crews_for(game, date_et=None, crew=None):
    return {"date": date_et or game.date_et, "games": [{
        "away": game.away_tricode, "home": game.home_tricode, "game_id": game.game_id,
        "crew": crew if crew is not None else [
            {"name": "Ann Ref", "slug": "ann-ref"}, {"name": "Bo Ref", "slug": "bo-ref"},
            {"name": "Cy Ref", "slug": "cy-ref"}]}]}


def matchup_data(poss_a=400, poss_b=350):
    return {"playerA": {"name": "Anna Alpha"}, "playerB": {"name": "Bea Beta"}, "ytdLabel": "2025-26",
            "aGuardedByB": {"career": {"poss": poss_a}}, "bGuardedByA": {"career": {"poss": poss_b}}}


def found_matchups(pages=(PAIR,), data=None):
    return matchups.Matchups(set(pages), {match_key("Anna Alpha"): "anna-alpha", match_key("Bea Beta"): "bea-beta"},
                             {PAIR: data if data is not None else matchup_data()})


def ctx_for(games=None, rosters=None, injuries=None, stars=True, **kw):
    ctx = load_context(games or GAMES, today=TODAY, injuries=injuries, star_rosters=rosters or {
        AWAY: [{"player": "Anna Alpha", "all_star": 5}], HOME: [{"player": "Bea Beta", "all_star": 4}]})
    if stars:     # both named in "Players to watch"
        ctx.recent_awards = [{"player": n, "season": "2025-26", "award": "all_nba_first"}
                             for n in ("Anna Alpha", "Bea Beta")]
    for key, value in kw.items():
        setattr(ctx, key, value)
    return ctx


def kinds(lines):
    return [line.kind for line in lines]


def texts(lines):
    return [line.text for line in lines]


# -- referees ---------------------------------------------------------------------------------

def test_referee_line_names_the_crew_and_links_pages_that_exist():
    ctx = ctx_for(crews=crews_for(GAME), referee_slugs={"ann-ref", "cy-ref"}, stars=False)
    [line] = worth.referee_lines(ctx, GAME)
    assert line.text == "Referees: Ann Ref, Bo Ref and Cy Ref"
    assert [(t, h) for t, h in line.parts if h] == [("Ann Ref", REF_URL.format("ann-ref")),
                                                    ("Cy Ref", REF_URL.format("cy-ref"))]
    assert line.volatile and line.kind == "referees"


def test_a_referee_without_a_slug_is_plain_text():
    crew = [{"name": "Ann Ref", "slug": "ann-ref"}, {"name": "New Ref", "slug": None}]
    ctx = ctx_for(crews=crews_for(GAME, crew=crew), referee_slugs={"ann-ref"}, stars=False)
    [line] = worth.referee_lines(ctx, GAME)
    assert line.text == "Referees: Ann Ref and New Ref"
    assert [h for t, h in line.parts if t == "New Ref"] == [""]


@pytest.mark.parametrize("crews", [
    crews_for(GAME, date_et=day(-1)),                     # yesterday's file, not refreshed yet
    crews_for(GAME, date_et=day(1)),                      # tomorrow's
    {"date": TODAY, "games": []},                          # empty
    {"date": "", "games": []},                             # what load() returns with no file
    {},
    crews_for(GAME, crew=[]),                             # game listed, crew not assigned yet
])
def test_no_referee_line_unless_the_file_is_dated_the_game_day(crews):
    ctx = ctx_for(crews=crews, referee_slugs={"ann-ref"}, stars=False)
    assert worth.referee_lines(ctx, GAME) == []


def test_a_later_game_never_gets_tonights_crew():
    """Tonight's file names this pair, but the next meeting is another day."""
    crews = crews_for(GAME)
    crews["games"][0]["game_id"] = LATER.game_id
    ctx = ctx_for(crews=crews, referee_slugs={"ann-ref"}, stars=False)
    assert worth.referee_lines(ctx, LATER) == []


def test_crews_match_on_teams_when_the_id_differs():
    crews = crews_for(GAME)
    crews["games"][0]["game_id"] = "0000000000"
    other = next(g for g in GAMES if g.date_et == TODAY and g.game_id != GAME.game_id)
    ctx = ctx_for(crews=crews, referee_slugs=set(), stars=False)
    assert texts(worth.referee_lines(ctx, GAME)) == ["Referees: Ann Ref, Bo Ref and Cy Ref"]
    assert worth.referee_lines(ctx, other) == []


def test_referee_line_has_no_figures():
    ctx = ctx_for(crews=crews_for(GAME), referee_slugs={"ann-ref"}, stars=False)
    assert not any(ch.isdigit() for ch in worth.referee_lines(ctx, GAME)[0].text)


# -- revenge games ----------------------------------------------------------------------------

def rosters(home_players=(), away_players=()):
    return {HOME: list(home_players), AWAY: list(away_players)}


def former(name, team, end, seasons=1, all_star=0):
    return {"player": name, "all_star": all_star, "past": [{"team": team, "end": end, "seasons": seasons}]}


def awarded(ctx, *names, season="2025-26", award="all_star"):
    """Put these players in the recent-awards pool."""
    ctx.recent_awards = ctx.recent_awards + [{"player": n, "season": season, "award": award} for n in names]
    return ctx


def test_revenge_line_for_a_star_facing_his_old_team():
    ctx = awarded(ctx_for(rosters=rosters([former("Paul George", AWAY, 2019)]), stars=False), "Paul George")
    assert worth.revenge_lines(ctx, GAME) == ["Revenge game: Paul George faces the Celtics"]


def test_all_nba_counts_like_all_star():
    ctx = awarded(ctx_for(rosters=rosters([former("Paul George", AWAY, 2019)]), stars=False), "Paul George",
                  season="2023-24", award="all_nba_third")
    assert worth.revenge_lines(ctx, GAME) == ["Revenge game: Paul George faces the Celtics"]


def test_no_line_for_a_player_outside_the_pool_on_a_short_or_old_stint():
    players = [former("Role Player", AWAY, 2019, seasons=9),        # long stint, left years ago
               former("Short Stay", AWAY, 2026, seasons=4),         # left this offseason, four seasons
               former("Old Star", AWAY, 2026, seasons=2)]           # his All-Star season is too old
    ctx = awarded(ctx_for(rosters=rosters(players), stars=False), "Old Star", season="2021-22")
    assert worth.revenge_lines(ctx, GAME) == []


def test_line_for_a_long_stint_that_ended_this_offseason():
    ctx = ctx_for(rosters=rosters([former("Long Timer", AWAY, 2026, seasons=5)]), stars=False)
    assert worth.revenge_lines(ctx, GAME) == ["Revenge game: Long Timer faces the Celtics"]


def test_the_line_never_says_first_time():
    ctx = ctx_for(games=[GAME], rosters=rosters([former("Long Timer", AWAY, 2026, seasons=7)]), stars=False)
    [line] = worth.revenge_lines(ctx, GAME)
    assert line == "Revenge game: Long Timer faces the Celtics" and "first time" not in line
    assert "revenge_first" not in ctx.copy["game"]


def test_no_revenge_line_without_a_stint_with_the_opponent():
    ctx = awarded(ctx_for(rosters=rosters([former("Paul George", "LAL", 2020), {"player": "No Past"}]),
                          stars=False), "Paul George", "No Past")
    assert worth.revenge_lines(ctx, GAME) == []


def test_at_most_two_most_recent_departure_first():
    players = [former("Old Star", AWAY, 2019, all_star=9), former("Long Timer", AWAY, 2026, seasons=8),
               former("Mid Star", AWAY, 2023)]
    ctx = awarded(ctx_for(rosters=rosters(players, [former("Away Star", HOME, 2021)]), stars=False),
                  "Old Star", "Mid Star", "Away Star")
    assert worth.revenge_lines(ctx, GAME) == ["Revenge game: Long Timer faces the Celtics",
                                              "Revenge game: Mid Star faces the Celtics"]


def test_players_listed_out_do_not_count():
    players = [former("Paul George", AWAY, 2026, seasons=6), former("Other Star", AWAY, 2020)]
    injuries = {HOME: [{"player": "Paul George", "status": "Out", "injury": "Knee", "date": TODAY}]}
    ctx = awarded(ctx_for(rosters=rosters(players), injuries=injuries, stars=False), "Other Star")
    assert worth.revenge_lines(ctx, GAME) == ["Revenge game: Other Star faces the Celtics"]
    injuries[HOME][0]["status"] = "Questionable"                         # only Out removes him
    ctx = awarded(ctx_for(rosters=rosters(players), injuries=injuries, stars=False), "Other Star")
    assert worth.revenge_lines(ctx, GAME)[0] == "Revenge game: Paul George faces the Celtics"


# -- career head-to-head -------------------------------------------------------------------

def test_head_to_head_line_links_the_matchup_page():
    ctx = ctx_for(matchups=found_matchups())
    assert ctx.ranking_row(GAME)["stars"] == ["Anna Alpha", "Bea Beta"]
    [line] = worth.head_to_head_lines(ctx, GAME)
    assert line.text == "Alpha vs. Beta: 750 possessions guarding each other through 2025-26"
    assert [(t, h) for t, h in line.parts if h] == [
        ("Alpha vs. Beta", "https://hoopsmatic.com/matchups/m/anna-alpha-vs-bea-beta.html")]
    assert line.kind == "head_to_head" and not line.volatile


def test_pair_slug_is_alphabetical_whatever_the_order():
    assert matchups.pair_slug("bea-beta", "anna-alpha") == PAIR
    assert found_matchups().pair_for("Bea Beta", "Anna Alpha") == PAIR


@pytest.mark.parametrize("found", [
    found_matchups(pages=()),                                         # no page for the pair
    found_matchups(data=matchup_data(150, matchups.MIN_POSSESSIONS - 151)),   # one short of the minimum
    matchups.Matchups({PAIR}, {match_key("Anna Alpha"): "anna-alpha"}, {PAIR: matchup_data()}),  # one not indexed
    matchups.Matchups({PAIR}, {match_key("Anna Alpha"): "anna-alpha", match_key("Bea Beta"): "bea-beta"}, {}),
    None,
])
def test_no_head_to_head_line_without_a_page_or_enough_volume(found):
    assert worth.head_to_head_lines(ctx_for(matchups=found), GAME) == []


def test_exactly_the_minimum_shows():
    ctx = ctx_for(matchups=found_matchups(data=matchup_data(150, matchups.MIN_POSSESSIONS - 150)))
    assert worth.head_to_head_lines(ctx, GAME)


def test_no_head_to_head_line_with_only_one_star():
    ctx = ctx_for(matchups=found_matchups(), stars=False)
    ctx.recent_awards = [{"player": "Anna Alpha", "season": "2025-26", "award": "all_nba_first"}]
    assert ctx.ranking_row(GAME)["stars"][1] is None
    assert worth.head_to_head_lines(ctx, GAME) == []


def test_star_pairs_are_what_the_build_fetches():
    assert ("Anna Alpha", "Bea Beta") in star_pairs(ctx_for())


# -- the block: cap, order, volatility --------------------------------------------------------

def full_house(n_revenge=2, back_to_back=True):
    """Today's game with every item true: a back-to-back for the away team,
    n_revenge revenge lines, a crew, a head-to-head and a season series."""
    earlier = replace(GAME, game_id="0022699001", date_et=day(-5), tipoff_utc=f"{day(-5)}T00:00:00+00:00",
                      game_status=3, away_score=100, home_score=90)
    games = [earlier, GAME]
    if back_to_back:
        games.append(replace(GAME, game_id="0022699002", home_tricode="MIA", date_et=day(-1),
                             tipoff_utc=f"{day(-1)}T00:00:00+00:00"))
    home = [{"player": "Bea Beta", "all_star": 4}] + [former(f"Mover {i}", AWAY, 2026, seasons=6)
                                                      for i in range(n_revenge)]
    return ctx_for(games=games, rosters={AWAY: [{"player": "Anna Alpha", "all_star": 5}], HOME: home},
                   crews=crews_for(GAME), referee_slugs={"ann-ref"}, matchups=found_matchups())


def test_every_item_can_show_and_the_order_is_fixed():
    ctx = full_house(n_revenge=0, back_to_back=False)
    assert kinds(worth.lines(ctx, GAME)) == ["referees", "head_to_head", "series"]
    ctx = full_house(n_revenge=1, back_to_back=False)
    assert kinds(worth.lines(ctx, GAME)) == ["revenge", "referees", "head_to_head", "series"]


def test_never_more_than_four_lines_first_ones_kept():
    ctx = full_house()
    assert kinds(worth.lines(ctx, GAME)) == ["rest", "revenge", "revenge", "referees"]
    ctx = full_house(back_to_back=False)
    assert kinds(worth.lines(ctx, GAME)) == ["revenge", "revenge", "referees", "head_to_head"]
    ctx.crews = {}
    assert kinds(worth.lines(ctx, GAME)) == ["revenge", "revenge", "head_to_head", "series"]


def test_every_line_is_short():
    for line in worth.lines(full_house(back_to_back=False), GAME):
        assert len(line.text) <= 80, line.text


def test_game_day_lines_are_volatile_and_later_ones_stable():
    ctx = full_house(n_revenge=1, back_to_back=False)
    assert all(line.volatile for line in worth.lines(ctx, GAME))
    later = replace(GAME, game_id="0022699003", date_et=day(3), tipoff_utc=f"{day(3)}T00:00:00+00:00")
    ctx.games = ctx.games + [later]
    later_lines = worth.lines(ctx, later)
    assert kinds(later_lines) == ["revenge", "head_to_head", "series"]       # no crew on another day
    assert not any(line.volatile for line in later_lines)


# -- rendered pages ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def worth_site(tmp_path_factory):
    """The fixture site built offline with cached crews, referee pages,
    matchup pages and rosters in the published tree, as a morning build
    leaves them for the refresh."""
    out = tmp_path_factory.mktemp("site-worth")
    data = out / "data"
    (data / "matchups" / "m").mkdir(parents=True)
    (data / "schedule.json").write_text(json.dumps({
        "season": "2026-27", "updated_at": TODAY, "count": len(GAMES),
        "games": [asdict(g) for g in GAMES]}), encoding="utf-8")
    (data / "tonights-crews.json").write_text(json.dumps(crews_for(GAME)), encoding="utf-8")
    (data / "referee-pages.json").write_text(json.dumps(["ann-ref", "bo-ref"]), encoding="utf-8")
    (data / "matchups" / "pages.json").write_text(json.dumps([PAIR]), encoding="utf-8")
    (data / "matchups" / "players.json").write_text(json.dumps(
        {match_key("Anna Alpha"): "anna-alpha", match_key("Bea Beta"): "bea-beta"}), encoding="utf-8")
    (data / "matchups" / "m" / f"{PAIR}.json").write_text(json.dumps(
        {"fetched_at": "2000-01-01T00:00:00+00:00", "data": matchup_data()}), encoding="utf-8")
    (data / "star-rosters.json").write_text(json.dumps({"teams": {
        AWAY: [{"player": "Anna Alpha", "all_star": 9}],
        HOME: [{"player": "Bea Beta", "all_star": 9}, former("Paul George", AWAY, 2019)],
        TOMORROW.away_tricode: [{"player": "Anna Alpha", "all_star": 9}],
        TOMORROW.home_tricode: [{"player": "Bea Beta", "all_star": 9}]}}), encoding="utf-8")
    awards_dir = _copy_data(tmp_path_factory, "data-worth-awards")
    (awards_dir / "recent_awards.json").write_text(json.dumps({"awards": [
        {"player": n, "season": "2025-26", "award": "all_nba_first"} for n in ("Anna Alpha", "Bea Beta")] +
        [{"player": "Paul George", "season": "2024-25", "award": "all_star"}]}),
        encoding="utf-8")
    full_build(out, today=TODAY, offline=True, data_dir=awards_dir, now=f"{TODAY}T12:00:00-05:00")
    return out


def worth_part(page: str, game_id: str) -> str:
    block = page[page.index(f'id="game-{game_id}"'):]
    block = block[:block.index("</article>")]
    return block[block.index('data-part="worth"'):]


def test_pair_page_block_renders_the_lines_with_links(worth_site):
    slug = game_pair_slug(GAME, BY_TRICODE)
    page = (worth_site / slug / "index.html").read_text(encoding="utf-8")
    block = worth_part(page, GAME.game_id)
    # Both teams are on a back-to-back in the fixture schedule, so the cap
    # keeps rest, rest, revenge and referees and drops the head-to-head.
    items = re.findall(r"<li data-volatile>(.*?)</li>", block)
    assert len(items) == 4 and re.search(r"<li(?! data-volatile)", block) is None
    assert [i.split(" ")[1] for i in items[:2]] == ["on", "on"]            # "Hawks on the second night ..."
    assert items[2] == "Revenge game: Paul George faces the Celtics"
    assert (f'<li data-volatile>Referees: <a href="{REF_URL.format("ann-ref")}">Ann Ref</a>, '
            f'<a href="{REF_URL.format("bo-ref")}">Bo Ref</a> and Cy Ref</li>') in block
    stripped = lastmod.normalise(page)
    assert "Ann Ref" not in stripped and "Paul George" not in stripped
    # A pair page whose next meeting is tomorrow: no crew, and stable content.
    page = (worth_site / game_pair_slug(TOMORROW, BY_TRICODE) / "index.html").read_text(encoding="utf-8")
    later = worth_part(page, TOMORROW.game_id)
    assert "Referees" not in later and "data-volatile" not in later
    assert ('<li><a href="https://hoopsmatic.com/matchups/m/'
            'anna-alpha-vs-bea-beta.html">Alpha vs. Beta</a>: 750 possessions guarding each other through '
            '2025-26</li>') in later
    assert "Alpha vs. Beta" in lastmod.normalise(page)


def test_block_order_holds_with_the_new_lines(worth_site):
    slug = game_pair_slug(GAME, BY_TRICODE)
    page = (worth_site / slug / "index.html").read_text(encoding="utf-8")
    block = page[page.index(f'id="game-{GAME.game_id}"'):]
    block = block[:block.index("</article>")]
    order = [block.index(f'data-part="{p}"') for p in ("watch", "when", "players", "out", "worth")]
    assert order == sorted(order)
    worth_ul = block[block.index('data-part="worth"'):]
    assert worth_ul.count("<li") <= worth.MAX_LINES


def test_hub_and_tonight_cards_carry_the_lines(worth_site):
    for rel in ("index.html", "tonight/index.html"):
        page = (worth_site / rel).read_text(encoding="utf-8")
        assert f'<a href="{REF_URL.format("ann-ref")}">Ann Ref</a>' in page, rel
        assert "Revenge game: Paul George faces the Celtics" in page, rel


def test_links_point_only_at_pages_that_exist(worth_site):
    for page in worth_site.rglob("*.html"):
        html = page.read_text(encoding="utf-8")
        for href in re.findall(r'href="(https://hoopsmatic\.com/(?:referees|matchups)/[^"]+)"', html):
            assert href in (REF_URL.format("ann-ref"), REF_URL.format("bo-ref"),
                            f"https://hoopsmatic.com/matchups/m/{PAIR}.html"), (page, href)


# -- loaders -------------------------------------------------------------------------------

def test_referees_load_caches_and_keeps_the_last_copy(tmp_path, monkeypatch):
    listed = [{"slug": f"ref-{i}", "name": f"Ref {i}"} for i in range(referees.MIN_PAGES)]
    files = {referees.CREWS_URL: crews_for(GAME), referees.REFEREES_URL: listed}
    monkeypatch.setattr(referees, "get", lambda url, expect_json=False: files[url])
    crews, slugs, _ = referees.load(tmp_path)
    assert crews["date"] == TODAY and "ref-0" in slugs

    def refuse(*a, **k):
        raise FetchError("down")
    monkeypatch.setattr(referees, "get", refuse)
    crews, slugs, note = referees.load(tmp_path)
    assert crews["date"] == TODAY and len(slugs) == referees.MIN_PAGES and "kept the last copy" in note


def test_referees_load_rejects_a_broken_file(tmp_path, monkeypatch):
    monkeypatch.setattr(referees, "get", lambda url, expect_json=False: {"oops": True})
    crews, slugs, _ = referees.load(tmp_path)
    assert crews == {"date": "", "games": []} and slugs == set()
    assert referees.load(tmp_path, allow_fetch=False)[0] == {"date": "", "games": []}


def test_matchups_load_fetches_only_wanted_pairs_with_a_page(tmp_path, monkeypatch):
    names = [("Anna Alpha", "anna-alpha"), ("Bea Beta", "bea-beta")] + \
            [(f"Player {chr(97 + i // 26)}{chr(97 + i % 26)}", f"p-{i}") for i in range(matchups.MIN_PAGES)]
    pages = [PAIR] + [f"p-{i}-vs-p-{i + 1}" for i in range(matchups.MIN_PAGES)]
    sitemap = "".join(f"<loc>https://hoopsmatic.com/matchups/m/{p}.html</loc>" for p in pages).encode()
    calls = []

    def fake(url, expect_json=False):
        calls.append(url)
        if url.endswith("/sitemap.xml"):
            return sitemap
        if url.endswith("/player_index.json"):
            return [{"name": n, "slug": s} for n, s in names]
        if url.endswith(f"/data/m/{PAIR}.json"):
            return matchup_data()
        raise FetchError("404")
    monkeypatch.setattr(matchups, "get", fake)
    found, _ = matchups.load(tmp_path, [("Bea Beta", "Anna Alpha"), ("Anna Alpha", "Nobody Here")])
    assert found.headline("Anna Alpha", "Bea Beta")["possessions"] == 750
    assert sum("/data/m/" in c for c in calls) == 1
    calls.clear()
    found, _ = matchups.load(tmp_path, [("Anna Alpha", "Bea Beta")])       # fresh copy on disk: no download
    assert not any("/data/m/" in c for c in calls) and found.headline("Anna Alpha", "Bea Beta")
    offline, _ = matchups.load(tmp_path, [("Anna Alpha", "Bea Beta")], allow_fetch=False)
    assert offline.headline("Anna Alpha", "Bea Beta")["url"].endswith(f"/m/{PAIR}.html")


# -- career map stints ---------------------------------------------------------------------

@pytest.mark.parametrize("years, end", [
    ("2010–2017", 2017), ("2016–17", 2017), ("1999–00", 2000), ("2025", 2025), ("2026–present", None),
    ("", None)])
def test_stint_end(years, end):
    assert careers.stint_end(years) == end


def test_past_teams_latest_stint_per_team_newest_first():
    full = {t.full_name: t.tricode for t in load_teams()}
    record = {"career_history": [
        {"years": "2012–2014", "team": "Boston Celtics"}, {"years": "2014–2019", "team": "Miami Heat"},
        {"years": "2019–2021", "team": "Boston Celtics"}, {"years": "2021–present", "team": "Atlanta Hawks"},
        {"years": "2011", "team": "Some G League Team"}]}
    assert careers.past_teams(record, full, "ATL") == [{"team": "BOS", "end": 2021, "seasons": 2},
                                                       {"team": "MIA", "end": 2019, "seasons": 5}]


@pytest.mark.parametrize("years, seasons", [
    ("2013–2026", 13), ("2019-2026", 7), ("2016–17", 1), ("2025–2026", 1), ("2025", 1), ("2026–present", 0),
    ("", 0)])
def test_stint_seasons(years, seasons):
    assert careers.stint_seasons(years) == seasons
