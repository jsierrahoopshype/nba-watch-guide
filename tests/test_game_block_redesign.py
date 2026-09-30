"""The phone-first game block and pair page redesign: the collapsed answer
for everyone, the cable and live TV line, the conditional "Why ...?",
players to watch kept out of who's out, the meetings cards, short channel
names, team color accents, and the SEO fields that must not move."""

from __future__ import annotations

import functools
import html as htmllib
import http.server
import json
import re
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from conftest import TODAY, _build, _copy_data
from watchguide import colors, config
from watchguide.context import load_context
from watchguide.model import load_local_tv, load_team_colors, load_teams
from watchguide.pages.common import chips, countdown, watch_view
from watchguide.pairs import game_pair_slug

ROOT = Path(__file__).resolve().parent.parent
TEAMS = load_teams()
BY_TRICODE = {t.tricode: t for t in TEAMS}
TAGS = re.compile(r"<[^>]+>")


def text(markup: str) -> str:
    return " ".join(htmllib.unescape(TAGS.sub(" ", markup)).split())


def read(site, rel: str) -> str:
    return (site / rel / "index.html").read_text(encoding="utf-8")


def blocks(page: str) -> list[str]:
    return [b.split("</article>")[0] for b in page.split("data-game-block>")[1:]]


def block_for(page: str, game_id: str) -> str | None:
    """The game block with this id on the page, or None."""
    ids = [m.group(1) for m in re.finditer(r'id="game-(\d+)" data-game-block', page)]
    return blocks(page)[ids.index(game_id)] if game_id in ids else None


def part(block: str, name: str) -> str:
    """One data-part of a game block, up to the next part."""
    start = block.index(f'data-part="{name}"')
    nxt = re.search(r'data-part="\w+"', block[start + 10:])
    return block[start:start + 10 + nxt.start()] if nxt else block[start:]


def ctx_for(games, data_dir=None, **kw):
    return load_context(games, today=TODAY, data_dir=data_dir, **kw)


def a_game(fixture_games, home, away, national=(), day=TODAY, **kw):
    base = next(g for g in fixture_games if g.date_et == day)
    return replace(base, home_tricode=home, away_tricode=away, national=list(national),
                   national_ott=[], home_tv=[], away_tv=[], **kw)


def slug(game) -> str:
    return game_pair_slug(game, BY_TRICODE)


# -- 1. identical answers collapse to one line --------------------------------------------

def test_everyone_line_only_when_all_four_answers_match(fixture_games):
    ctx = ctx_for(fixture_games)
    seen = {True: 0, False: 0}
    for game in fixture_games:
        watch = watch_view(ctx, game)
        answers = [st["answer"] for fan in watch["fans"] for st in fan["states"]]
        assert len(answers) == 4
        same = len(set(answers)) == 1
        assert (watch["everyone"] == answers[0]) if same else watch["everyone"] == ""
        seen[same] += 1
    assert seen[True] and seen[False]


def test_collapsed_and_stacked_answers_on_the_page(built_site, fixture_games):
    ctx = ctx_for(fixture_games)
    checked = {True: 0, False: 0}
    for game in [g for g in fixture_games if g.date_et >= TODAY][:24]:
        block = block_for(read(built_site, slug(game)), game.game_id)
        if block is None:
            continue                                   # not this pair's next meeting
        watch = part(block, "watch")
        collapsed = bool(watch_view(ctx, game)["everyone"])
        if collapsed:
            assert "Everyone in the US:" in text(watch) and 'class="gb-fans"' not in watch
        else:
            assert "Everyone in the US" not in watch and watch.count('class="gb-fan"') == 2
            for team in (BY_TRICODE[game.away_tricode], BY_TRICODE[game.home_tricode]):
                assert f"<h5>{team.short_name} fans</h5>" in watch
                assert f"Outside the {team.short_name} market:" in watch
                assert f"In the {team.short_name} market:" in watch
        checked[collapsed] += 1
    assert checked[True] and checked[False]


# -- 2. live TV in the answers: standalone first, grouped by service -----------------------

def _lineups(tmp_path_factory, marks, label="data-live-tv"):
    """A data copy where every lineup entry starts unchecked and `marks` maps
    (package label, channel) to the entry to put there."""
    data_dir = _copy_data(tmp_path_factory, label)
    raw = json.loads((data_dir / "services.json").read_text(encoding="utf-8"))
    for svc in raw["services"]:
        for pkg in (svc.get("lineup") or {}).get("packages", []):
            for ch in pkg["channels"]:
                ch.update({"status": "unchecked", "confidence": "", "sources": [], "checked": ""})
                ch.update(marks.get((pkg["label"], ch["channel"]), {}))
    (data_dir / "services.json").write_text(json.dumps(raw), encoding="utf-8")
    return data_dir


def _src(url, published="2026"):
    return {"url": url, "published": published}


def _moderate(*sources, status="carried", checked="2026-09-30"):
    return {"status": status, "confidence": "moderate", "sources": list(sources), "checked": checked}


def _high(url, checked="2026-09-30"):
    return {"status": "carried", "confidence": "high", "sources": [_src(url, "official")], "checked": checked}


TWO = (_src("https://thestreamable.com/x"), _src("https://www.antennaland.com/y"))
CHECK = "Based on 2026 channel guides. Check your plan's lineup before you buy."
ZIP = "Local ABC and NBC availability varies by ZIP code."


def _answer(ctx, game):
    watch = watch_view(ctx, game)
    return watch["everyone"] or watch["fans"][0]["states"][0]["answer"], watch["check"]


def test_answers_list_standalone_first_then_live_tv_by_service(fixture_games):
    ctx = ctx_for(fixture_games)
    answer, check = _answer(ctx, a_game(fixture_games, "MIA", "MIN", ["ESPN"]))
    assert answer == ("Watch it on ESPN Unlimited, or on live TV with YouTube TV, Hulu + Live TV, Sling, Fubo "
                      "or DirecTV.")
    assert check == CHECK
    # NBA TV: Fubo Pro does not count there, so the plan that does is named;
    # both YouTube TV plans carry it, so YouTube TV is named once.
    answer, _ = _answer(ctx, a_game(fixture_games, "LAC", "DAL", ["NBA TV"]))
    assert answer.endswith(", or on live TV with YouTube TV, Fubo Elite or DirecTV.")
    assert "Fubo Pro" not in answer and "YouTube TV Sports Plan" not in answer


def test_a_plan_is_named_only_when_the_plans_differ(fixture_games, tmp_path_factory):
    ctx = ctx_for(fixture_games, data_dir=_lineups(tmp_path_factory, {
        ("YouTube TV Sports Plan", "ESPN"): _moderate(*TWO),       # the Sports Plan only
        ("Fubo Pro", "ESPN"): _moderate(*TWO),
        ("Fubo Elite", "ESPN"): _moderate(*TWO),                   # both Fubo plans
    }))
    answer, _ = _answer(ctx, a_game(fixture_games, "MIA", "MIN", ["ESPN"]))
    assert answer == "Watch it on ESPN Unlimited, or on live TV with YouTube TV Sports Plan or Fubo."


def test_live_tv_only_answer_and_no_check_line_at_high_confidence(fixture_games, tmp_path_factory):
    """A game only live TV carries reads "Watch it on live TV with ..."; a
    high-confidence entry needs no check line."""
    ctx = ctx_for(fixture_games, data_dir=_lineups(tmp_path_factory, {
        ("YouTube TV", "ESPN2"): _high("https://tv.youtube.com/welcome/"),
    }, label="data-live-tv-high"))
    answer, check = _answer(ctx, a_game(fixture_games, "LAC", "DAL", ["ESPN2"]))
    assert answer == "Watch it on live TV with YouTube TV."
    assert check == ""


def test_unchecked_below_the_rule_and_not_carried_are_never_named(fixture_games, tmp_path_factory):
    ctx = ctx_for(fixture_games, data_dir=_lineups(tmp_path_factory, {
        ("Hulu + Live TV", "ESPN"): _moderate(*TWO),
        ("Sling Orange", "ESPN"): _moderate(TWO[0]),                                  # one source
        ("Sling Blue", "ESPN"): _moderate(_src("https://thestreamable.com/a"),
                                          _src("https://thestreamable.com/b")),       # same site twice
        ("Fubo Pro", "ESPN"): _moderate(_src("https://thestreamable.com/x", "2025"), TWO[1]),  # a 2025 source
        ("DirecTV", "ESPN"): _high("https://cordcuttersnews.com/review"),             # "official" off-domain
        ("YouTube TV Sports Plan", "ESPN"): _moderate(*TWO, checked=""),              # no check date
        ("YouTube TV", "ESPN"): _moderate(*TWO, status="not_carried"),
    }, label="data-live-tv-rules"))
    answer, _ = _answer(ctx, a_game(fixture_games, "MIA", "MIN", ["ESPN"]))
    assert answer == "Watch it on ESPN Unlimited, or on live TV with Hulu + Live TV."


def test_zip_line_only_when_live_tv_is_named_through_local_abc_or_nbc(fixture_games):
    ctx = ctx_for(fixture_games)
    for codes in (["ABC"], ["NBC", "Peacock"]):
        answer, _ = _answer(ctx, a_game(fixture_games, "LAC", "DAL", codes))
        assert answer.endswith(" " + ZIP), codes
    for codes in (["ESPN"], ["ABC", "ESPN"], ["NBA TV"], ["Amazon"]):
        answer, _ = _answer(ctx, a_game(fixture_games, "LAC", "DAL", codes))
        assert ZIP not in answer, codes


def test_alternatives_join_with_or_never_and(fixture_games):
    ctx = ctx_for(fixture_games)
    answer, _ = _answer(ctx, a_game(fixture_games, "MIA", "NYK", ["ABC"]))
    assert answer.startswith("Watch it on ABC (over the air) or ESPN Unlimited, or on live TV with ")
    for game in fixture_games:
        for fan in watch_view(ctx, game)["fans"]:
            for st in fan["states"]:
                assert " and " not in st["answer"].split(". ")[0], st["answer"]


def test_league_pass_includes_nba_tv_and_nba_tv_is_a_channel(fixture_games):
    ctx = ctx_for(fixture_games)
    watch = watch_view(ctx, a_game(fixture_games, "PHI", "MIL", ["NBA TV"]))
    by_state = {st["state"]: st["answer"] for st in watch["fans"][0]["states"]}
    assert by_state["out_of_market"] == ("Watch it on NBA League Pass (includes NBA TV), or on live TV with "
                                         "YouTube TV, Fubo Elite or DirecTV.")
    # In-market League Pass is blacked out and NBA TV is the only standalone option.
    assert by_state["in_market"] == ("Watch it on NBA TV through cable or live TV, or on live TV with "
                                     "YouTube TV, Fubo Elite or DirecTV.")


def test_nba_tv_keeps_its_plain_name_beside_other_standalone_options(fixture_games):
    """The Heat's local stations simulcast NBA TV games that carry the Heat's
    own code, so in the Heat market NBA TV is one option among several."""
    ctx = ctx_for(fixture_games)
    game = replace(a_game(fixture_games, "MIA", "PHI", ["NBA TV"]), home_tv=["WPLG"])
    heat = next(f for f in watch_view(ctx, game)["fans"] if f["team"].tricode == "MIA")
    inside = next(st["answer"] for st in heat["states"] if st["state"] == "in_market")
    assert inside.startswith("Watch it on NBA TV, Local TV over the air or Local 10+ Platinum, or on live TV with ")
    assert "through cable" not in inside


def test_the_service_level_flag_alone_names_nobody(fixture_games, tmp_path_factory):
    """Live TV coverage comes from the lineup; a service-level flag put back
    into services.json is ignored."""
    data_dir = _lineups(tmp_path_factory, {}, label="data-service-flag")      # every lineup entry unchecked
    raw = json.loads((data_dir / "services.json").read_text(encoding="utf-8"))
    for svc in raw["services"]:
        if svc.get("kind") == "live_tv":
            svc["carries"], svc["carries_verified"] = ["ESPN"], True
    (data_dir / "services.json").write_text(json.dumps(raw), encoding="utf-8")
    answer, check = _answer(ctx_for(fixture_games, data_dir=data_dir), a_game(fixture_games, "MIA", "MIN", ["ESPN"]))
    assert answer == "Watch it on ESPN Unlimited." and check == ""


def test_no_cable_line_and_one_check_line_per_block(built_site, fixture_games):
    page = read(built_site, "tonight")
    espn = next(g for g in fixture_games if g.date_et == TODAY and "ESPN" in g.national_codes)
    watch = part(block_for(page, espn.game_id), "watch")
    assert "data-cable" not in page and "Also on cable" not in page
    assert htmllib.unescape(watch).count(CHECK) == 1 and watch.count("data-live-tv-check") == 1
    assert "or on live TV with" in watch
    hub = (built_site / "index.html").read_text(encoding="utf-8")
    assert "data-cable" not in hub


# -- 3. "Why ...?" only when someone is blocked, worded for the case -----------------------

def _no_blackouts(tmp_path_factory):
    data_dir = _copy_data(tmp_path_factory, "data-no-blackouts")
    raw = json.loads((data_dir / "services.json").read_text(encoding="utf-8"))
    raw["rules"]["league_pass_blackouts"] = {"source_url": "x", "last_verified": "2026-09-25"}
    (data_dir / "services.json").write_text(json.dumps(raw), encoding="utf-8")
    return data_dir


def test_why_is_worded_for_the_block(fixture_games):
    ctx = ctx_for(fixture_games)
    # National game, neither team's local TV counts (Clippers unknown,
    # Mavericks low): only League Pass is in the way.
    why = watch_view(ctx, a_game(fixture_games, "LAC", "DAL", ["ESPN"]))["why"]
    assert why["summary"] == "Why isn't this on League Pass?" and why["kinds"] == ["league_pass"]
    # National game for the Heat, whose games are all on local TV in market:
    # League Pass and local TV both miss it.
    why = watch_view(ctx, a_game(fixture_games, "MIA", "DAL", ["ESPN"]))["why"]
    assert why["summary"] == "Why isn't this on League Pass or local TV?"
    assert "Heat local TV (WPLG Local 10) does not show games on national TV." in why["lines"]
    # A local game: League Pass is blacked out in the home markets.
    why = watch_view(ctx, a_game(fixture_games, "MIA", "DAL", []))["why"]
    assert why["summary"] == "Why isn't this on League Pass?"


def test_no_why_when_nothing_blocks_anyone(fixture_games, tmp_path_factory):
    data_dir = _no_blackouts(tmp_path_factory)
    ctx = ctx_for(fixture_games, data_dir=data_dir)
    assert watch_view(ctx, a_game(fixture_games, "LAC", "DAL", []))["why"] is None
    assert watch_view(ctx, a_game(fixture_games, "LAC", "DAL", ["ESPN"]))["why"] is None
    # The regional reason alone still shows, worded for local TV.
    why = watch_view(ctx, a_game(fixture_games, "MIA", "DAL", ["ESPN"]))["why"]
    assert why["summary"] == "Why isn't this on local TV?" and why["kinds"] == ["local"]


def test_why_markup_is_conditional_and_tappable(built_site, fixture_games, tmp_path_factory):
    page = read(built_site, "tonight")
    for block in blocks(page):
        watch = part(block, "watch")
        if "<details" in watch:
            summary = re.search(r'<details class="why gb-why" data-why="[\w ]+"><summary>([^<]+)</summary>', watch)
            assert summary and htmllib.unescape(summary.group(1)) in {
                "Why isn't this on League Pass?", "Why isn't this on local TV?",
                "Why isn't this on League Pass or local TV?"}
    assert "Why can&#39;t I watch this game?" not in "".join(blocks(page))
    css = (config.ASSET_DIR / "watch-guide.css").read_text(encoding="utf-8")
    assert re.search(r"\.gb-why > summary::after[^{]*\{[^}]*border-right: 2px solid", css)      # the chevron
    assert re.search(r"\.gb-why > summary, [^{]*\{[^}]*min-height: var\(--tap\)", css)
    # Without blackout rules, the expandable is there exactly for the games
    # where a fan base is still blocked (the regional reason).
    data_dir = _no_blackouts(tmp_path_factory)
    site = _build(tmp_path_factory, fixture_games, "site-no-blackouts", data_dir=data_dir)
    ctx = ctx_for(fixture_games, data_dir=data_dir)
    today = [g for g in fixture_games if g.date_et == TODAY]
    unblocked = {g.game_id for g in today if watch_view(ctx, g)["why"] is None}
    assert unblocked and len(unblocked) < len(today)
    page = read(site, "tonight")
    for game in today:
        assert ("<details" in part(block_for(page, game.game_id), "watch")) == (game.game_id not in unblocked)


# -- 4. players to watch: its own row, never inside who's out -------------------------------

def test_players_to_watch_never_sits_in_whos_out(built_site):
    pages = [read(built_site, "tonight")] + [read(built_site, t.slug) for t in TEAMS] + \
        [p.read_text(encoding="utf-8") for p in sorted(built_site.glob("*-vs-*/index.html"))]
    seen = 0
    for page in pages:
        for block in blocks(page):
            players, out = part(block, "players"), part(block, "out")
            assert block.index('data-part="players"') < block.index('data-part="out"')
            assert "Players to watch" in players and "Who&#39;s out" in out
            for marker in ("Players to watch", 'class="pw"', "pw-face", "data-rank-line"):
                assert marker not in out, marker
            assert "data-player=" not in players          # who's out chips stay in their own part
            seen += 1
    assert seen > 30


def test_players_row_shows_two_faces_with_name_and_team(tmp_path_factory, fixture_games):
    game = next(g for g in fixture_games if g.date_et == TODAY)
    data_dir = _copy_data(tmp_path_factory, "data-players")
    awards = [{"player": n, "season": "2025-26", "award": "all_nba_first"} for n in ("Away Star", "Home Star")]
    (data_dir / "recent_awards.json").write_text(json.dumps({"awards": awards}), encoding="utf-8")
    ctx = ctx_for(fixture_games, data_dir=data_dir, star_rosters={
        game.away_tricode: [{"player": "Away Star", "all_star": 0}],
        game.home_tricode: [{"player": "Home Star", "all_star": 0}]})
    from watchguide.pages.common import game_view
    view = game_view(ctx, game)
    assert [(p["name"], p["team"]) for p in view["players"]] == [
        ("Away Star", BY_TRICODE[game.away_tricode].short_name),
        ("Home Star", BY_TRICODE[game.home_tricode].short_name)]
    assert all(p["src"] == "assets/silhouette.svg" for p in view["players"])      # no face on disk


def test_whos_out_shows_chips_or_the_message(tmp_path_factory, fixture_games):
    game = next(g for g in fixture_games if g.date_et == TODAY)
    injuries = {"updated_at": f"{TODAY}T11:00:00-05:00", "as_of": TODAY, "players": [
        {"player": "Hurt Guy", "status": "Out", "injury": "Knee", "date": TODAY, "team": game.home_tricode}]}
    site = _build(tmp_path_factory, fixture_games, "site-out-chips", injuries=injuries)
    out = part(blocks(read(site, slug(game)))[0], "out")
    assert re.search(r'<li class="out-chip" data-player="Hurt Guy"><span>Hurt Guy</span> '
                     r'<span class="badge badge-out" data-status-slot>Out</span></li>', out)


# -- 5. every meeting: cards on phones, table from tablet width -----------------------------

@pytest.fixture(scope="module")
def played_site(tmp_path_factory, fixture_games):
    """The fixture schedule with every game before today final, home side winning."""
    games = [replace(g, game_status=3, home_score=110, away_score=101) if g.date_et < TODAY else g
             for g in fixture_games]
    return _build(tmp_path_factory, games, "site-played"), games


def test_meetings_highlight_the_next_and_score_the_played(played_site):
    site, games = played_site
    past = next(g for g in games if g.is_final and any(
        o.date_et >= TODAY and slug(o) == slug(g) for o in games))
    page = read(site, slug(past))
    table = page[page.index('<table class="sched meetings">'):page.index("</table>")]
    rows = re.findall(r"<tr class=\"mt[^\"]*\"[^>]*>.*?</tr>", table, re.S)
    group = [g for g in games if slug(g) == slug(past)]
    assert len(rows) == len(group)
    nxt = [r for r in rows if "is-next" in r]
    assert len(nxt) == 1 and "data-next" in nxt[0] and '<span class="badge badge-next">Next</span>' in nxt[0]
    played = next(r for r in rows if f'id="game-{past.game_id}"' in r)
    home, away = BY_TRICODE[past.home_tricode].short_name, BY_TRICODE[past.away_tricode].short_name
    assert "is-past" in played and "data-final" in played
    assert f"Final · {away} 101, {home} 110" in text(played) and f"<strong>{home} 110</strong>" in played
    assert "data-utc" not in played                     # a played game shows no tip time
    upcoming = [r for r in rows if "is-past" not in r]
    assert all("data-utc" in r and "data-final" not in r for r in upcoming)
    assert "<th scope=\"col\">Tip-off</th>" in table


def test_meetings_css_is_cards_on_phones_and_a_fixed_table_from_700(built_site):
    css = (config.ASSET_DIR / "watch-guide.css").read_text(encoding="utf-8")
    phone = css[css.index("@media (max-width: 699px) {\n  .sched.meetings tr"):]
    assert re.search(r"\.sched\.meetings tr \{\s*display: grid;", phone)
    wide = css[css.index("@media (min-width: 700px) {\n  .meetings"):]
    assert ".meetings { table-layout: fixed; }" in wide[:200]


def _serve(root):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_meetings_are_cards_at_375_and_a_table_at_800(played_site, tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    site, games = played_site
    root = tmp_path / "srv"
    root.mkdir()
    (root / "how-to-watch").symlink_to(site)
    server = _serve(root)
    path = slug(next(g for g in games if g.date_et == TODAY))
    try:
        with sync_api.sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception:
                browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
            for width, display in ((375, "grid"), (800, "table-row")):
                page = browser.new_page(viewport={"width": width, "height": 900})
                page.goto(f"http://127.0.0.1:{server.server_port}/how-to-watch/{path}")
                shown = page.eval_on_selector_all(".meetings tr.mt", "rs => rs.map(r => getComputedStyle(r).display)")
                assert shown and set(shown) == {display}, (width, shown)
                assert page.evaluate("document.documentElement.scrollWidth") <= width
                page.close()
            browser.close()
    finally:
        server.shutdown()


# -- 6. short names for long local channels ------------------------------------------------

def test_short_names_are_shorter_and_belong_to_the_team():
    for slug_, local in load_local_tv().items():
        names = set(local.local_broadcasters) | {o.name for o in local.streaming}
        for full, short in local.short_names.items():
            assert full in names, (slug_, full)
            assert short and len(short) < len(full), (slug_, full, short)
    detroit = load_local_tv()["detroit-pistons"]
    assert detroit.short_name("WMYD The Spot Detroit 20 (Scripps)") == "Scripps Detroit 20"
    assert detroit.short_name("DAZN") == "DAZN"


def test_chips_show_the_short_name_with_the_full_one_in_title(fixture_games, built_site):
    ctx = ctx_for(fixture_games)
    chip = chips(ctx, [{"name": "WMYD The Spot Detroit 20 (Scripps)", "kind": "local", "team": "Pistons"}],
                 priced=True)[0]
    assert (chip["label"], chip["title"], chip["how"]) == \
        ("Scripps Detroit 20", "WMYD The Spot Detroit 20 (Scripps)", "Pistons market")
    page = read(built_site, "detroit-pistons")
    assert '<span class="badge badge-local" title="WMYD The Spot Detroit 20 (Scripps)">Scripps Detroit 20</span>' in page
    assert ">WMYD The Spot Detroit 20 (Scripps)</span>" not in page


def test_national_chips_carry_the_service_and_price(fixture_games):
    ctx = ctx_for(fixture_games)
    got = [(c["label"], c["how"]) for c in chips(ctx, [
        {"name": code, "kind": "national"} for code in ("ESPN", "NBC", "Peacock", "ABC", "Amazon", "NBA TV", "NBCSN")],
        priced=True)]
    assert got == [("ESPN Unlimited", "$31.99/mo"), ("NBC", "free over the air"), ("Peacock Premium", "$12.99/mo"),
                   ("ABC", "free over the air"), ("Amazon", "Prime Video $14.99/mo"),
                   ("NBA TV", "NBA League Pass $16.99/mo"), ("NBCSN", "")]


# -- matchup head: date chip, countdown, local time ----------------------------------------

def test_countdown_labels(fixture_games):
    ctx = ctx_for(fixture_games)
    base = next(g for g in fixture_games if g.date_et == TODAY)       # 7 pm ET in the fixture

    def on(day, hour=19):
        return replace(base, date_et=day, tipoff_et=f"{day}T{hour:02d}:00:00-05:00")
    assert countdown(ctx, on(TODAY))["label"] == "Tonight"
    assert countdown(ctx, on(TODAY, 13))["label"] == "Today"
    assert countdown(ctx, on("2027-01-16"))["label"] == "Tomorrow"
    assert countdown(ctx, on("2027-02-05"))["label"] == "In 21 days"
    assert countdown(ctx, on("2027-01-14"))["label"] == ""
    assert countdown(ctx, on(TODAY))["day_label"] == "Fri, Jan 15"


def test_head_has_logos_team_links_date_chip_and_big_time(built_site, fixture_games):
    game = next(g for g in fixture_games if g.date_et == TODAY)
    block = blocks(read(built_site, slug(game)))[0]
    head = block[:block.index('data-part="watch"')]
    for team in (BY_TRICODE[game.away_tricode], BY_TRICODE[game.home_tricode]):
        assert re.search(rf'<a class="gb-team" href="{team.path}"[^>]*><img class="logo gb-logo" '
                         rf'src="/how-to-watch/assets/logos/{team.tricode.lower()}\.[0-9a-f]{{10}}\.svg" '
                         r'width="64" height="64"', head)
    assert '<span class="gb-day">Fri, Jan 15</span>' in head
    assert re.search(r'<span class="gb-count" data-countdown data-date="2027-01-15" data-evening[^>]*data-volatile>'
                     r'Tonight</span>', head)
    when = part(block, "when")
    assert '<span class="gb-clock" data-local-clock>7:00 pm</span> <span class="gb-zone" data-local-zone>ET</span>' in when
    assert '<span class="gb-tip-et" data-et-extra>7:00 pm ET</span>' in when


def test_one_time_format_in_the_script():
    js = (config.ASSET_DIR / "watch-guide.js").read_text(encoding="utf-8")
    assert "toLocaleString" not in js                   # no locale-dependent "1:00 AM GMT+2"
    assert "part(parts, 'dayPeriod').toLowerCase()" in js


# -- 7. team colors ------------------------------------------------------------------------

def test_every_team_has_a_color_and_the_accent_clears_3_to_1():
    team_colors = load_team_colors()
    assert set(team_colors) == set(BY_TRICODE)
    for tricode, value in team_colors.items():
        assert colors.contrast(colors.accent(value), "#FFFFFF") >= 3.0, tricode
    assert colors.accent("#C4CED4") != "#C4CED4"          # the Spurs' silver is darkened
    assert colors.accent("#007A33") == "#007A33"


def test_team_colors_are_never_text(built_site, fixture_games):
    css = (config.ASSET_DIR / "watch-guide.css").read_text(encoding="utf-8")
    assert not re.search(r"(?<![-\w])color:\s*var\(--(tc|away|home)\b", css)
    game = next(g for g in fixture_games if g.date_et == TODAY)
    block_start = read(built_site, slug(game))
    ctx = ctx_for(fixture_games)
    assert (f'style="--away:{ctx.team_accent(game.away_tricode)};--home:{ctx.team_accent(game.home_tricode)}"'
            in block_start)


# -- the section is live: titles, descriptions, canonicals, og:url unchanged ----------------

def test_titles_descriptions_and_canonicals_match_the_last_release(built_site_indexed):
    """tests/data/seo_snapshot.json was written from main before the
    redesign, from this same fixture build."""
    snapshot = json.loads((ROOT / "tests" / "data" / "seo_snapshot.json").read_text(encoding="utf-8"))
    assert len(snapshot) >= 30
    for rel, want in snapshot.items():
        page = read(built_site_indexed, "" if rel == "(hub)" else rel)
        got = {
            "title": re.search(r"<title>(.*?)</title>", page).group(1),
            "description": re.search(r'<meta name="description" content="([^"]*)"', page).group(1),
            "canonical": re.search(r'<link rel="canonical" href="([^"]*)"', page).group(1),
            "og_url": re.search(r'<meta property="og:url" content="([^"]*)"', page).group(1),
            "og_title": re.search(r'<meta property="og:title" content="([^"]*)"', page).group(1),
            "og_description": re.search(r'<meta property="og:description" content="([^"]*)"', page).group(1),
        }
        assert got == want, rel
