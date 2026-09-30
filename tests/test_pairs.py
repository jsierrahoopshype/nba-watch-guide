"""Team-vs-team pages, the shared game block and its layout rule, the tonight
page as one ranked list of cards, the back-to-back and season-series lines,
and the injury safety net."""

from __future__ import annotations

import functools
import html as htmllib
import http.server
import itertools
import json
import re
import threading
from dataclasses import asdict, replace
from datetime import date, timedelta

import pytest

from conftest import TODAY, fixture_schedule
from watchguide import config, pairs, worth
from watchguide.build import full_build
from watchguide.context import load_context
from watchguide.manifest import expected_pages
from watchguide.model import load_copy, load_teams
from watchguide.pages.pair import pair_title
from watchguide.sources import schedule as schedule_source

TEAMS = load_teams()
BY_TRICODE = {t.tricode: t for t in TEAMS}
TAGS = re.compile(r"<[^>]+>")
PARTS = ("watch", "when", "players", "out", "worth")


def read(site, rel: str) -> str:
    return (site / rel / "index.html").read_text(encoding="utf-8")


def text(markup: str) -> str:
    return " ".join(htmllib.unescape(TAGS.sub(" ", markup)).split())


def canonical_slug(game) -> str:
    a, b = sorted([BY_TRICODE[game.away_tricode].slug, BY_TRICODE[game.home_tricode].slug])
    return f"{a}-vs-{b}"


def blocks(page: str) -> list[str]:
    return [b.split("</article>")[0] for b in page.split("data-game-block>")[1:]]


# -- slugs: one page per pair, canonical order only ---------------------------------------

def test_one_page_per_pair_in_canonical_order(built_site, fixture_games):
    expected = {canonical_slug(g) for g in fixture_games}
    built = {p.parent.name for p in built_site.glob("*-vs-*/index.html")}
    assert built == expected
    for slug in built:
        first, second = slug.split(pairs.SEPARATOR)
        assert first < second
        assert not (built_site / f"{second}-vs-{first}").exists()


def test_slug_order_ignores_which_side_is_home():
    a, b = BY_TRICODE["NYK"], BY_TRICODE["PHI"]
    assert pairs.pair_slug(a, b) == pairs.pair_slug(b, a) == "new-york-knicks-vs-philadelphia-76ers"
    assert [t.short_name for t in pairs.by_name(a, b)] == ["76ers", "Knicks"]


def test_no_page_links_the_reversed_order(built_site):
    canonical = {p.parent.name for p in built_site.glob("*-vs-*/index.html")}
    for page in built_site.rglob("index.html"):
        for slug in re.findall(r'/how-to-watch/([a-z0-9-]+-vs-[a-z0-9-]+)', page.read_text(encoding="utf-8")):
            assert slug in canonical, f"{page}: links {slug}"


def test_pair_pages_are_in_the_manifest_sitemap_and_self_canonical(built_site_indexed, fixture_games):
    site = built_site_indexed
    manifest = (site / "data" / "expected-pages.txt").read_text(encoding="utf-8").split()
    assert manifest == expected_pages(games=fixture_games)
    sitemap = (site / "sitemap.xml").read_text(encoding="utf-8")
    for slug in {canonical_slug(g) for g in fixture_games}:
        url = config.public_url(slug)
        assert f"{slug}/index.html" in manifest
        assert f"<loc>{url}</loc>" in sitemap
        assert f'<link rel="canonical" href="{url}">' in read(site, slug)


# -- titles and descriptions -------------------------------------------------------------

def test_every_possible_pair_title_fits_and_keeps_names_and_how_to_watch():
    text_block = load_copy()["pair"]
    for x, y in itertools.combinations(TEAMS, 2):
        a, b = pairs.by_name(x, y)
        title = pair_title(text_block, a.short_name, b.short_name)
        assert len(title) <= 60, title
        assert title.endswith(" | HoopsMatic"), title
        assert a.short_name in title and b.short_name in title and "How to Watch" in title, title


def test_built_titles_and_descriptions(built_site):
    descriptions = []
    for page in built_site.glob("*-vs-*/index.html"):
        html = page.read_text(encoding="utf-8")
        title = htmllib.unescape(re.search(r"<title>(.*?)</title>", html).group(1))
        assert len(title) <= 60 and title.endswith(" | HoopsMatic")
        desc = htmllib.unescape(re.search(r'<meta name="description" content="([^"]*)"', html).group(1))
        assert len(desc) <= 155 and " next on " in desc
        descriptions.append(desc)
    assert len(set(descriptions)) == len(descriptions)
    knicks = read(built_site, "new-york-knicks-vs-philadelphia-76ers") \
        if (built_site / "new-york-knicks-vs-philadelphia-76ers").exists() else None
    if knicks:
        assert "<title>76ers vs. Knicks: How to Watch, TV &amp; Streaming | HoopsMatic</title>" in knicks


# -- the page: next meeting in full, then every meeting ------------------------------------

def test_pair_page_has_next_meeting_then_every_meeting(built_site, fixture_games):
    slug = canonical_slug(next(g for g in fixture_games if g.date_et == TODAY))
    games = sorted((g for g in fixture_games if canonical_slug(g) == slug), key=lambda g: g.date_et)
    nxt = next(g for g in games if g.date_et >= TODAY)
    page = read(built_site, slug)
    assert page.index("data-game-block") < page.index('id="meetings"')
    assert len(blocks(page)) == 1 and f'id="game-{nxt.game_id}"' in page
    ids = re.findall(r'\bid="(game-[^"]+)"', page)
    assert sorted(ids) == sorted(f"game-{g.game_id}" for g in games)       # each game exactly once
    block = blocks(page)[0]
    collapsed = "data-everyone" in block
    for team in (BY_TRICODE[nxt.away_tricode], BY_TRICODE[nxt.home_tricode]):
        assert f'href="{team.path}"' in block
        # Four fan-base answers, or one line for everyone when they match.
        assert collapsed or (f"{team.short_name} fans" in block and f"Outside the {team.short_name} market:" in block
                             and f"In the {team.short_name} market:" in block)
    assert not collapsed or "Everyone in the US:" in block
    assert f'data-utc="{nxt.tipoff_utc}"' in block and " pm ET" in block and "Tip-off" in block


def test_game_block_parts_are_in_the_layout_order(built_site):
    """Pair pages, tonight's cards and the team pages' next game: where to watch, when, who's out, then
    Also worth knowing, and nothing between the head and where to watch."""
    pages = [read(built_site, "tonight")] + [read(built_site, t.slug) for t in TEAMS] + \
        [p.read_text(encoding="utf-8") for p in sorted(built_site.glob("*-vs-*/index.html"))[:20]]
    seen = 0
    for page in pages:
        for block in blocks(page):
            found = [p for p in re.findall(r'data-part="(\w+)"', block)]
            assert found == [p for p in PARTS if p in found] and found[:4] == list(PARTS[:4]), found
            head = block.index('class="gb-head"')
            between = block[block.index("</div>", head) + len("</div>"):block.index('<div class="gb-watch"')]
            assert between.strip() == "", between
            seen += 1
    assert seen > 20


def test_hub_cards_put_where_to_watch_before_time_and_worth_last(built_site):
    hub = (built_site / "index.html").read_text(encoding="utf-8")
    for row in hub.split('<li class="hg-row" ')[1:]:
        row = row.split("</li>\n  <li")[0]
        order = [row.index('class="hg-watch"'), row.index('class="hg-top"'), row.index('class="hg-line')]
        assert order == sorted(order)
        if "hg-worth" in row:
            assert row.index('class="hg-worth') > order[-1]


def test_no_css_reorders_game_parts():
    css = (config.ASSET_DIR / "watch-guide.css").read_text(encoding="utf-8")
    for rule in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        selector, body = rule
        if re.search(r"\.(gb|hg)-|\.game\b", selector):
            assert not re.search(r"\border\s*:|flex-direction\s*:\s*\w*-reverse|grid-area|"
                                 r"grid-template-areas|position\s*:\s*absolute", body), selector


def _serve(root):
    """The built tree under /how-to-watch on a local port."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_layout_order_on_a_phone_in_a_real_browser(built_site, tmp_path):
    """375px wide: every part of every game block sits below the one before it.
    Needs the playwright package (a Chromium is preinstalled in the cloud
    sandbox); skipped where it is not installed."""
    sync_api = pytest.importorskip("playwright.sync_api")
    root = tmp_path / "srv"
    root.mkdir()
    (root / "how-to-watch").symlink_to(built_site)
    server = _serve(root)
    slug = next(p.parent.name for p in sorted(built_site.glob("*-vs-*/index.html")))
    try:
        with sync_api.sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception:
                browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
            page = browser.new_page(viewport={"width": 375, "height": 800})
            for path in ("tonight", slug, TEAMS[0].slug):
                page.goto(f"http://127.0.0.1:{server.server_port}/how-to-watch/{path}")
                tops = page.eval_on_selector_all("[data-game-block]", """els => els.map(el =>
                    ['watch', 'when', 'players', 'out', 'worth'].map(k => {
                      const n = el.querySelector('[data-part="' + k + '"]');
                      if (!n) return null;
                      const r = n.getBoundingClientRect();
                      return [r.top, r.bottom];
                    }))""")
                assert tops
                for parts in tops:
                    present = [t for t in parts if t]
                    for before, after in zip(present, present[1:]):
                        assert before[1] <= after[0] + 0.5, (path, parts)
                assert page.evaluate("document.documentElement.scrollWidth") <= 375
            browser.close()
    finally:
        server.shutdown()


# -- tonight: one ranked list of cards, no score ------------------------------------------

def test_tonight_is_one_list_of_cards_with_pair_and_team_links(built_site, fixture_games):
    page = read(built_site, "tonight")
    today = [g for g in fixture_games if g.date_et == TODAY]
    assert page.count("<ol") == 1 and page.count("data-game-block") == len(today)
    assert "data-score" not in page and "Score " not in page
    assert "data-rank-heading" in page and "data-rank-basis" in page and "data-rank-line" in page
    for block in blocks(page):
        gid = re.search(r'id="game-(\d+)"', page[page.index(block) - 60:page.index(block)]).group(1)
        game = next(g for g in today if g.game_id == gid)
        slug = canonical_slug(game)
        assert f'href="/how-to-watch/{slug}#game-{gid}" data-pair-link' in block
        assert f'href="{BY_TRICODE[game.away_tricode].path}"' in block
        assert f'id="game-{gid}"' in read(built_site, slug)


def test_no_score_on_any_page(built_site):
    for page in built_site.rglob("index.html"):
        html = page.read_text(encoding="utf-8")
        assert "data-score" not in html and not re.search(r"\bScore \d", html), page


# -- team schedule rows link their pair page -----------------------------------------------

def test_team_schedule_rows_link_the_pair_page_at_the_game(built_site):
    for team in TEAMS:
        page = read(built_site, team.slug)
        table = page[page.index('<table class="sched">'):]
        links = re.findall(r'<td class="opp"[^>]*><a href="([^"]+)" data-pair-link>', table)
        assert links and len(links) == table.count('<td class="opp"')
        for href in links:
            path, _, anchor = href.partition("#")
            assert team.slug in path and anchor.startswith("game-")
            assert f'id="{anchor}"' in read(built_site, path[len("/how-to-watch/"):])


# -- Also worth knowing ------------------------------------------------------------------

def _ctx(games, **kw):
    return load_context(games, today=kw.pop("today", TODAY), **kw)


def test_back_to_back_only_when_true():
    games = fixture_schedule()
    game = next(g for g in games if g.date_et == TODAY)
    ctx = _ctx(games)
    lines = worth.rest_lines(ctx, game)
    assert f"{BY_TRICODE[game.away_tricode].short_name} on the second night of a back-to-back" in lines
    # Take out yesterday's games and nobody is on a back-to-back.
    yesterday = (date.fromisoformat(TODAY) - timedelta(days=1)).isoformat()
    rested = [g for g in games if g.date_et != yesterday]
    assert worth.rest_lines(_ctx(rested), game) == []
    assert not worth.back_to_back(rested, game, game.home_tricode)


def test_back_to_back_line_is_on_the_page(built_site, fixture_games):
    game = next(g for g in fixture_games if g.date_et == TODAY)
    block = blocks(read(built_site, canonical_slug(game)))[0]
    worth_part = block[block.index('data-part="worth"'):]
    assert "Also worth knowing" in worth_part
    assert f"{BY_TRICODE[game.home_tricode].short_name} on the second night of a back-to-back" in worth_part


def _meetings(games):
    """Four meetings of one pair: three before TODAY, one on TODAY."""
    base = next(g for g in games if g.date_et == TODAY)
    out = []
    for i, days in enumerate((-30, -20, -10)):
        d = (date.fromisoformat(TODAY) + timedelta(days=days)).isoformat()
        swap = i % 2 == 1
        out.append(replace(base, game_id=f"00299{i:05d}", date_et=d, tipoff_utc=f"{d}T00:00:00+00:00",
                           home_tricode=base.away_tricode if swap else base.home_tricode,
                           away_tricode=base.home_tricode if swap else base.away_tricode))
    return base, out


def test_no_series_line_until_the_feed_has_scores():
    games = fixture_schedule()
    base, earlier = _meetings(games)
    ctx = _ctx(games + earlier)
    assert worth.series_lines(ctx, base) == []


def test_series_line_once_scores_exist():
    games = fixture_schedule()
    base, earlier = _meetings(games)
    home, away = base.home_tricode, base.away_tricode
    scored = [replace(g, game_status=3, home_score=110, away_score=100) for g in earlier]
    # Home side wins every game it hosts: base.home hosts meetings 0 and 2, base.away hosts 1.
    ctx = _ctx(games + scored)
    assert worth.series_lines(ctx, base) == [f"{BY_TRICODE[home].short_name} lead the season series 2-1"]
    tied = scored[:2]
    assert worth.series_lines(_ctx(games + tied), base) == ["Season series tied 1-1"]
    # A final score on a scheduled-looking row does not count.
    assert worth.series_lines(_ctx(games + [replace(g, game_status=1) for g in scored]), base) == []
    assert away in {g.home_tricode for g in scored}


def test_schedule_reader_keeps_scores_only_for_final_games():
    def game(gid, status, hs, as_):
        return {"gameId": gid, "gameStatus": status, "gameDateTimeUTC": "2026-11-01T00:00:00Z",
                "homeTeam": {"teamTricode": "NYK", "score": hs}, "awayTeam": {"teamTricode": "PHI", "score": as_},
                "broadcasters": {}}
    raw = {"leagueSchedule": {"seasonYear": config.SEASON, "gameDates": [
        {"games": [game("0022600001", 3, 101, 99), game("0022600002", 1, 0, 0)]}]}}
    final, scheduled = schedule_source.normalize(raw)
    assert (final.is_final, final.home_score, final.away_score, final.winner) == (True, 101, 99, "NYK")
    assert (scheduled.is_final, scheduled.home_score) == (False, None)


# -- the injury safety net ---------------------------------------------------------------

def _guard_site(tmp_path_factory, fixture_games, label, now, injuries=None):
    out = tmp_path_factory.mktemp(label)
    (out / "data").mkdir()
    (out / "data" / "schedule.json").write_text(json.dumps({
        "season": "2026-27", "updated_at": TODAY, "count": len(fixture_games),
        "games": [asdict(g) for g in fixture_games]}), encoding="utf-8")
    if injuries is not None:
        (out / "data" / "injuries.json").write_text(json.dumps(injuries), encoding="utf-8")
    outcome = full_build(out, today=TODAY, offline=True, now=now)
    return out, outcome.notes


OLD_FEED = {"updated_at": f"{TODAY}T15:00:00-05:00", "as_of": "2027-01-14", "players": []}


def test_guard_after_3pm_with_no_listings_and_an_old_feed(tmp_path_factory, fixture_games):
    site, notes = _guard_site(tmp_path_factory, fixture_games, "guard-on", f"{TODAY}T16:30:00-05:00", OLD_FEED)
    game = next(g for g in fixture_games if g.date_et == TODAY)
    for page in (read(site, "tonight"), read(site, canonical_slug(game))):
        out_part = blocks(page)[0].split('data-part="out"')[1]
        assert "Injury report not available yet" in out_part
        assert "Player availability shows here on game day" not in out_part
    assert "Injury report not available yet" in (site / "index.html").read_text(encoding="utf-8")
    assert any(n.startswith("WARNING injury report not available yet") for n in notes)


@pytest.mark.parametrize("now, injuries", [
    (f"{TODAY}T14:59:00-05:00", OLD_FEED),                                    # before 3 pm
    (f"{TODAY}T20:00:00-05:00", {**OLD_FEED, "as_of": TODAY}),                # feed dated today
])
def test_guard_stays_off(tmp_path_factory, fixture_games, now, injuries):
    site, notes = _guard_site(tmp_path_factory, fixture_games, "guard-off", now, injuries)
    assert "Injury report not available yet" not in read(site, "tonight")
    assert not any("injury report not available" in n for n in notes)


def test_guard_stays_off_when_a_team_has_a_listing(fixture_games):
    game = next(g for g in fixture_games if g.date_et == TODAY)
    listed = {game.home_tricode: [{"player": "Some One", "status": "Questionable", "injury": "", "date": TODAY}]}
    ctx = _ctx(fixture_games, injuries=listed, injuries_as_of="2027-01-14", now=f"{TODAY}T18:00:00-05:00")
    assert not ctx.injury_report_missing()
    ctx = _ctx(fixture_games, injuries_as_of="2027-01-14", now=f"{TODAY}T18:00:00-05:00")
    assert ctx.injury_report_missing()


def test_not_game_day_keeps_the_game_day_line(built_site, fixture_games):
    later = next(g for g in fixture_games if g.date_et > TODAY)
    slug = canonical_slug(later)
    games = [g for g in fixture_games if canonical_slug(g) == slug and g.date_et >= TODAY]
    if games[0].date_et == TODAY:
        pytest.skip("this pair plays today")
    block = blocks(read(built_site, slug))[0]
    assert "Player availability shows here on game day." in block.split('data-part="out"')[1]


def test_refresh_renders_and_writes_only_todays_pair_pages_with_the_latest_report(
        built_site, tmp_path, fixture_games, monkeypatch):
    import shutil
    from watchguide import build as build_module, lastmod
    from watchguide.sources import injuries as injuries_source
    game = next(g for g in fixture_games if g.date_et == TODAY)
    monkeypatch.setattr(injuries_source, "fetch_raw", lambda: [
        {"player": "Fresh Injury", "status": "Out", "injury": "Knee", "date": TODAY}])
    monkeypatch.setattr(injuries_source, "fetch_player_teams", lambda: {"fresh injury": game.home_tricode})
    rendered = []
    real_render = build_module.render_pages

    def spy(ctx, env=None):
        pages = real_render(ctx, env)
        rendered.extend(p.meta["pair"] for p in pages if p.meta.get("pair") and not p.meta.get("placeholder"))
        return pages
    monkeypatch.setattr(build_module, "render_pages", spy)

    site = tmp_path / "site"
    shutil.copytree(built_site, site)
    before = lastmod.read_state(site)
    stamps = {p: p.stat().st_mtime_ns for p in site.glob("*-vs-*/index.html")}
    build_module.refresh_build(site, today=TODAY, repo_root=tmp_path)

    today_pairs = {canonical_slug(g) for g in fixture_games if g.date_et == TODAY}
    assert set(rendered) == today_pairs and len(rendered) == len(today_pairs)
    changed = {p.parent.name for p, t in stamps.items() if p.stat().st_mtime_ns != t}
    assert changed == today_pairs
    page = read(site, canonical_slug(game))
    out_part = blocks(page)[0].split('data-part="out"')[1]
    assert 'data-player="Fresh Injury"' in out_part and ">Out</span>" in out_part
    # Every pair page is still in the manifest and keeps its lastmod entry.
    after = lastmod.read_state(site)
    pair_urls = {u for u in before if "-vs-" in u}
    assert pair_urls and pair_urls <= set(after)
    assert (site / "data" / "expected-pages.txt").read_text(encoding="utf-8").split() == \
        expected_pages(games=fixture_games)


def test_injury_ranking_and_out_parts_do_not_move_lastmod(fixture_games):
    """The same pair page with a different report, a different ranking line and
    the safety net on hashes the same, so the sitemap date stays put."""
    from watchguide import lastmod
    from watchguide.pages import pair as pair_page
    from watchguide.render import build_env
    game = next(g for g in fixture_games if g.date_et == TODAY)
    slug = canonical_slug(game)
    env = build_env()
    env.globals["noindex"] = True

    def page(**kw):
        ctx = _ctx(fixture_games, **kw)
        ctx.render_pairs = {slug}
        return next(p.html for p in pair_page.build(ctx, env) if p.meta["pair"] == slug)

    quiet = page(now=f"{TODAY}T10:00:00-05:00")
    hurt = page(injuries={game.home_tricode: [{"player": "Star Guy", "status": "Out", "injury": "", "date": TODAY}]},
                injuries_as_of=TODAY, now=f"{TODAY}T10:00:00-05:00")
    missing = page(injuries_as_of="2027-01-14", now=f"{TODAY}T18:00:00-05:00")
    star = json.loads((config.DATA_DIR / "recent_awards.json").read_text(encoding="utf-8"))["awards"][0]["player"]
    ranked = page(now=f"{TODAY}T10:00:00-05:00", star_rosters={game.home_tricode: [{"player": star}]})
    assert len({quiet, hurt, missing, ranked}) == 4 and star in ranked
    assert "Injury report not available yet" in missing and "Star Guy" in hurt
    assert lastmod.content_hash(quiet) == lastmod.content_hash(hurt) == lastmod.content_hash(missing) \
        == lastmod.content_hash(ranked)
    stripped = lastmod.normalise(hurt)
    for marker in ('data-part="out"', "data-rank-line", "data-player", "data-updated", "data-stale-notice"):
        assert marker not in stripped, marker
    assert 'data-part="watch"' in stripped and 'data-part="when"' in stripped


def test_team_next_game_card_is_the_shared_game_block(built_site, fixture_games):
    for team in TEAMS:
        page = read(built_site, team.slug)
        nxt = min((g for g in fixture_games if g.involves(team.tricode) and g.date_et >= TODAY),
                  key=lambda g: (g.date_et, g.tipoff_utc))
        section = page[page.index("<h2>Next game</h2>"):page.index('id="market"')]
        assert section.count("data-game-block") == 1 and f'id="game-{nxt.game_id}"' in section
        head_to_watch = section[section.index("data-game-block"):section.index('data-part="watch"')]
        assert "data-updated" not in head_to_watch and "data-stale-notice" not in head_to_watch
        assert f'href="/how-to-watch/{canonical_slug(nxt)}#game-{nxt.game_id}" data-pair-link' in section
