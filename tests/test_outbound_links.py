"""Outbound "where to watch" links (watchguide/links.py).

The rule this file guards: links never change the answer. Every page built
with links is the page built without them (WATCH_GUIDE_NO_LINKS=1) plus the
anchors, byte for byte, and nothing on screen moves. Also: the precision
ladder, the labels and attributes, the dormant affiliate switch, the data
the links come from, and the sitemap hash ignoring them."""

from __future__ import annotations

import functools
import http.server
import json
import os
import re
import threading
from datetime import date

import pytest

from conftest import _build
from watchguide import config, lastmod, links
from watchguide.model import Game

ANCHOR = re.compile(r'<a ([^>]*\bdata-out(?=[\s>])[^>]*)>(.*?)</a>', re.S)
OUT_ATTR = re.compile(r'\sdata-out(?=[\s>])')
LEVELS = set(links.LEVELS)


@pytest.fixture(scope="module")
def built_without_links(tmp_path_factory, fixture_games):
    os.environ["WATCH_GUIDE_NO_LINKS"] = "1"
    try:
        return _build(tmp_path_factory, fixture_games, "site-no-links")
    finally:
        del os.environ["WATCH_GUIDE_NO_LINKS"]


def _pages(site):
    return sorted(p.relative_to(site) for p in site.rglob("index.html"))


def strip(html: str) -> str:
    return ANCHOR.sub(r"\2", html)


# -- links never change the answer -------------------------------------------------------------

def test_every_page_is_the_page_without_links_plus_the_anchors(built_site, built_without_links):
    pages = _pages(built_site)
    assert pages == _pages(built_without_links)
    anchors = 0
    for rel in pages:
        with_links = (built_site / rel).read_text(encoding="utf-8")
        without = (built_without_links / rel).read_text(encoding="utf-8")
        assert not OUT_ATTR.search(without), rel
        assert strip(with_links) == without, rel
        anchors += len(ANCHOR.findall(with_links))
    assert anchors > 100


def test_links_do_not_move_the_sitemap_or_the_data(built_site, built_without_links):
    for rel in ("sitemap.xml", "data/sitemap_lastmod.json", "data/tonight.json", "data/injuries.json"):
        assert (built_site / rel).read_text(encoding="utf-8") == \
            (built_without_links / rel).read_text(encoding="utf-8"), rel


def test_page_types_that_get_links(built_site):
    """Hub game cards, tonight, a pair page, a team page and a country page."""
    hub = (built_site / "index.html").read_text(encoding="utf-8")
    cards = re.search(r'<ol class="hg-list">(.*?)</ol>', hub, re.S).group(1)
    assert ANCHOR.search(cards)
    pair = next(p for p in _pages(built_site) if "-vs-" in str(p) and ANCHOR.search(
        (built_site / p).read_text(encoding="utf-8")))
    for rel in ("tonight/index.html", "boston-celtics/index.html", "miami-heat/index.html", pair,
                "uk/index.html"):
        assert ANCHOR.search((built_site / rel).read_text(encoding="utf-8")), rel


# -- labels and attributes -------------------------------------------------------------------

def test_every_anchor_is_plain_new_tab_and_labelled(built_site):
    for rel in _pages(built_site):
        for attrs, inner in ANCHOR.findall((built_site / rel).read_text(encoding="utf-8")):
            href = re.search(r'href="([^"]+)"', attrs).group(1)
            assert href.startswith("https://") and "{" not in href, (rel, href)
            assert 'target="_blank"' in attrs and 'rel="noopener"' in attrs, (rel, attrs)
            assert "nofollow" not in attrs and "sponsored" not in attrs, (rel, attrs)
            name = re.search(r'aria-label="([^"]+)"', attrs).group(1)
            assert re.match(r"(Watch on|Sign up for) \S", name), (rel, name)
            assert "<a" not in inner and inner.strip(), (rel, inner)
        assert "earn HoopsMatic a commission" not in (built_site / rel).read_text(encoding="utf-8")


def test_a_national_chip_links_to_the_game_on_nba_com(built_site):
    """NBA TV games: the game's own page built from its NBA game ID."""
    html = (built_site / "tonight/index.html").read_text(encoding="utf-8")
    hrefs = re.findall(r'href="(https://www\.nba\.com/game/[a-z]{3}-vs-[a-z]{3}-\d{10})"', html)
    data = json.loads((config.DATA_DIR / "services.json").read_text(encoding="utf-8"))
    game_level = next(s for s in data["services"] if s["id"] == "nba_tv")["links"].get("game", {})
    assert bool(hrefs) == bool(game_level.get("verified")), hrefs


def _game(**kw) -> Game:
    return Game(game_id="0022600001", game_code="20261020/BOSDET", date_et="2026-10-20",
                tipoff_et="", tipoff_utc="", status_text="", home_tricode="DET", away_tricode="BOS", **kw)


COPY = {"links": {"watch": "Watch on {service}", "signup": "Sign up for {service}"}}


def test_the_ladder_takes_the_most_specific_verified_level():
    levels = {
        "game": {"url": "https://g.test/{away}-vs-{home}-{game_id}", "verified": True},
        "date": {"url": "https://d.test/{yyyymmdd}/{yyyy-mm-dd}", "verified": True},
        "section": {"url": "https://s.test/nba", "verified": True},
        "signup": {"url": "https://s.test/join", "verified": True},
    }
    assert links.best(levels, _game()) == ("game", "https://g.test/bos-vs-det-0022600001")
    levels["game"]["verified"] = False                     # unverified is never used
    assert links.best(levels, _game()) == ("date", "https://d.test/20261020/2026-10-20")
    assert links.best(levels) == ("section", "https://s.test/nba")   # no game: section and below
    levels["section"]["verified"] = False
    assert links.best(levels) == ("signup", "https://s.test/join")
    assert links.best({"game": {"url": "https://g.test/{nope}", "verified": True}}, _game()) == ("", "")


def test_labels_watch_signup_and_never_sign_up_for_a_station():
    assert links.label("Peacock", "section", COPY) == "Watch on Peacock"
    assert links.label("Peacock", "game", COPY) == "Watch on Peacock"
    assert links.label("Peacock", "signup", COPY) == "Sign up for Peacock"
    assert links.label("WPLG Local 10", "signup", COPY, kind="station") == "Watch on WPLG Local 10"
    assert links.label("ABC", "signup", COPY, kind="ota") == "Watch on ABC"


def test_the_affiliate_switch_is_built_but_dormant():
    plain = links.make("Peacock", "section", "https://s.test/nba", COPY)
    assert (plain.rel, plain.sponsored, plain.label) == ("noopener", False, "Watch on Peacock")
    aff = "https://aff.test/?id={game_id}"
    # The label follows the affiliate_level stored with the URL, not the
    # fact that it is an affiliate link.
    watch = links.make("Peacock", "section", "https://s.test/nba", COPY, affiliate=aff, game=_game(),
                       affiliate_level="watch")
    assert watch.href == "https://aff.test/?id=0022600001"
    assert (watch.rel, watch.sponsored, watch.label) == ("sponsored nofollow noopener", True, "Watch on Peacock")
    signup = links.make("Peacock", "section", "https://s.test/nba", COPY, affiliate=aff, game=_game(),
                        affiliate_level="signup")
    assert (signup.sponsored, signup.label) == (True, "Sign up for Peacock")
    # A station never says sign up, even through an affiliate link.
    station = links.make("WPLG", "section", "https://w.test/", COPY, kind="station", affiliate=aff,
                         game=_game(), affiliate_level="signup")
    assert station.label == "Watch on WPLG"
    # Without a valid level the affiliate_url is not used at all.
    for level in ("", "nope"):
        unused = links.make("Peacock", "section", "https://s.test/nba", COPY, affiliate=aff, game=_game(),
                            affiliate_level=level)
        assert (unused.href, unused.sponsored) == ("https://s.test/nba", False)
    out = links.OutLinks()
    out.attrs(plain)
    assert not out.sponsored
    assert 'rel="sponsored nofollow noopener"' in out.attrs(signup) and out.sponsored
    assert out.reset() == "" and not out.sponsored


def test_an_affiliate_url_brings_the_disclosure(built_site_priced):
    """conftest's priced build sets League Pass's affiliate_url."""
    html = (built_site_priced / "boston-celtics/index.html").read_text(encoding="utf-8")
    assert 'rel="sponsored nofollow noopener"' in html and "earn HoopsMatic a commission" in html
    # Its affiliate_level is "signup", so the label says so.
    assert re.search(r'href="https://example\.test/league-pass\?ref=test"[^>]*aria-label="Sign up for NBA League Pass"',
                     html)
    hub = (built_site_priced / "uk/index.html").read_text(encoding="utf-8")
    assert "sponsored" not in hub and "earn HoopsMatic a commission" not in hub


def test_local_names_match_exactly_then_the_first_part_of_a_feed_code():
    entries = [{"names": ["Altitude", "ALT"], "url": "https://a.test/", "verified": True, "level": "section"}]
    assert links.local_entry(entries, "ALT/ALT+/KTVD") is entries[0]
    assert links.local_entry(entries, "Altitude") is entries[0]
    assert links.local_entry(entries, "ALT2/ALT+") is None
    entries[0]["verified"] = False
    assert links.local_entry(entries, "ALT") is None


def test_a_local_chip_links_only_to_its_own_teams_page(built_site):
    """"DAZN" is dazn.com/hornets for one team and dazn.com/grizzlies for
    another: a team's local chips never borrow another team's link."""
    local = json.loads((config.DATA_DIR / "local_tv.json").read_text(encoding="utf-8"))["teams"]
    checked = 0
    for slug, team in local.items():
        own = {e["url"] for e in team.get("links") or []}
        html = (built_site / slug / "index.html").read_text(encoding="utf-8")
        table = html[html.index('<table class="sched"'):html.index("</table>")] if "<table" in html else ""
        for chip in re.findall(r'<span class="badge badge-local"[^>]*>(.*?)</span>', table, re.S):
            for attrs, _ in ANCHOR.findall(chip):
                assert re.search(r'href="([^"]+)"', attrs).group(1) in own, (slug, attrs)
                checked += 1
    assert checked


# -- the data ---------------------------------------------------------------------------------

def _affiliate(where, record):
    """Every affiliate_url sits beside an affiliate_level; a filled-in URL
    needs a level ("watch" or "signup"), or the link's label would guess."""
    assert "affiliate_url" in record and "affiliate_level" in record, where
    if record["affiliate_url"]:
        assert record["affiliate_level"] in links.AFFILIATE_LEVELS, where
        assert record["affiliate_url"].startswith("https://"), where


def _entries():
    """(where, entry, placeholders allowed) for every link entry in the data."""
    services = json.loads((config.DATA_DIR / "services.json").read_text(encoding="utf-8"))
    for svc in services["services"]:
        _affiliate(svc["id"], svc)
        for level, entry in svc.get("links", {}).items():
            assert level in LEVELS, (svc["id"], level)
            yield f"{svc['id']}.{level}", entry, level in links.GAME_LEVELS
    local = json.loads((config.DATA_DIR / "local_tv.json").read_text(encoding="utf-8"))
    for slug, team in local["teams"].items():
        own = set(team.get("local_broadcasters") or []) | {o.get("name") for o in team.get("streaming") or []}
        for entry in team.get("links") or []:
            assert entry["names"][0] in own, (slug, entry["names"])    # a name the page shows
            assert entry["kind"] in ("station", "stream") and entry["level"] in LEVELS, (slug, entry)
            _affiliate(slug, entry)
            yield f"{slug} {entry['names'][0]}", entry, False
    countries = json.loads((config.DATA_DIR / "countries.json").read_text(encoding="utf-8"))
    for slug, country in countries["countries"].items():
        shown = {o["name"] for o in country["partner"]["options"]} | {"Prime Video", "NBA League Pass"}
        assert "NBA League Pass" in country.get("links", {}), slug
        for name, entry in country.get("links", {}).items():
            assert name in shown, (slug, name)
            assert entry["level"] in LEVELS, (slug, name)
            _affiliate(f"{slug} {name}", entry)
            yield f"{slug} {name}", entry, False


def test_every_link_entry_is_recorded_properly():
    seen = 0
    for where, entry, templated in _entries():
        seen += 1
        url = entry["url"]
        assert url.startswith("https://"), where
        assert isinstance(entry["verified"], bool) and entry.get("how"), where
        date.fromisoformat(entry["checked"])
        if entry["verified"]:
            assert entry["confidence"] in ("high", "moderate"), where
        if "{" in url:
            assert templated, f"{where}: placeholders only on the game and date levels"
            assert all(p in links.PLACEHOLDERS for p in re.findall(r"\{[^}]*\}", url)), where
            pattern = re.escape(url)
            for p in links.PLACEHOLDERS:
                pattern = pattern.replace(re.escape(p), r"[0-9a-z-]+")
            assert re.fullmatch(pattern, entry["sample"]), f"{where}: the sample is not this template"
    assert seen > 50


def test_the_link_check_requests_one_sample_per_template():
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_links", config.REPO_ROOT / "scripts" / "check_links.py")
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    items = check.targets()
    assert len(items) == sum(1 for _ in _entries()) and all("{" not in i["url"] for i in items)

    responses = {"https://ok.test/": (200, "https://ok.test/", "<title>NBA</title>", ""),
                 "https://gone.test/": (404, "https://gone.test/", "", ""),
                 "https://wall.test/": (403, "https://wall.test/", "<title>Access Denied</title>", ""),
                 "https://bot.test/": (200, "https://bot.test/", "<title>Just a moment...</title>", ""),
                 "https://nohost.test/": (0, "https://nohost.test/", "", "Could not resolve host: nohost.test"),
                 "https://espn.test/": (202, "https://espn.test/", "", ""),
                 "https://notitle.test/": (200, "https://notitle.test/", "<p>app</p>", "")}
    rows = check.run([{"where": u, "url": u, "verified": True} for u in responses],
                     get=lambda u: responses[u], pause=0)
    assert [r["verdict"] for r in rows] == ["ok", "broken", "unverifiable", "unverifiable", "broken",
                                            "unverifiable", "unverifiable"]
    assert check.summary(rows).startswith("### Outbound links: 2 broken, 4 unverifiable, 1 ok")


def test_the_link_check_is_its_own_weekly_job_that_never_fails():
    text = (config.REPO_ROOT / ".github/workflows/check-links.yml").read_text(encoding="utf-8")
    assert re.search(r"schedule:\n\s+- cron: '\d+ \d+ \* \* 1'", text)
    assert "continue-on-error: true" in text and "contents: read" in text
    assert "git push" not in text and "git commit" not in text
    build = (config.REPO_ROOT / ".github/workflows/build-watch-guide-daily.yml").read_text(encoding="utf-8")
    assert "check_links" not in build


# -- sitemap lastmod --------------------------------------------------------------------------

def test_the_sitemap_hash_ignores_outbound_anchors():
    page = ('<p>On <span class="chip-name"><a class="out" data-out href="https://a.test/x" target="_blank" '
            'rel="noopener" aria-label="Watch on A" title="Watch on A">A</a></span> tonight.</p>')
    moved = page.replace("https://a.test/x", "https://a.test/y").replace("Watch on", "Sign up for")
    bare = '<p>On <span class="chip-name">A</span> tonight.</p>'
    assert lastmod.content_hash(page) == lastmod.content_hash(moved) == lastmod.content_hash(bare)
    # The name inside is still content: renaming the service moves the date.
    assert lastmod.content_hash(page) != lastmod.content_hash(page.replace(">A</a>", ">B</a>"))
    # A plain (internal) link is untouched.
    assert lastmod.content_hash('<a href="/x">A</a>') != lastmod.content_hash('<a href="/y">A</a>')


# -- phone first: the same layout at 375px ----------------------------------------------------

BOXES = """() => [...document.querySelectorAll('.badge, .row-title, .combo-parts li, h2, h3')]
  .map(n => { const r = n.getBoundingClientRect(); return [n.className, Math.round(r.x), Math.round(r.y),
                                                            Math.round(r.width), Math.round(r.height)]; })"""


def _serve(root):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_links_move_nothing_on_a_phone(built_site, built_without_links, tmp_path):
    """At 375px every chip, service row and heading sits exactly where it
    does without links, the page does not scroll sideways, and a tap on a
    chip's price text still hits its link."""
    sync_api = pytest.importorskip("playwright.sync_api")
    servers, bases = [], []
    for i, site in enumerate((built_site, built_without_links)):
        root = tmp_path / f"srv{i}"
        root.mkdir()
        (root / "how-to-watch").symlink_to(site)
        servers.append(_serve(root))
        bases.append(f"http://127.0.0.1:{servers[-1].server_port}/how-to-watch")
    try:
        with sync_api.sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception:
                browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
            page = browser.new_page(viewport={"width": 375, "height": 800})
            for path in ("/", "/tonight", "/boston-celtics", "/miami-heat", "/uk"):
                layouts = []
                for base in bases:
                    page.goto(base + path)
                    layouts.append(page.evaluate(BOXES))
                    assert page.evaluate("document.documentElement.scrollWidth") <= 375, path
                assert layouts[0] == layouts[1], path
            def hit(selector):
                box = page.query_selector(selector).bounding_box()
                return page.evaluate(f"(() => {{ const a = document.elementFromPoint({box['x'] + box['width'] / 2}, "
                                     f"{box['y'] + box['height'] / 2})?.closest('a'); "
                                     f"return a ? (a.matches('[data-out]') ? 'out' : a.className) : null; }})()")

            # Tonight: the price text of a linked chip is part of its tap target.
            page.goto(bases[0] + "/tonight")
            assert hit(".badge.chip:has(a.out) .chip-how") == "out"
            # Hub cards: a linked chip sits above the card's stretched link,
            # and the rest of the card still opens the game.
            page.goto(bases[0] + "/")
            assert hit(".hg-channels .badge:has(a.out)") == "out"
            assert hit(".hg-row .hg-players") == "card-link"
            browser.close()
    finally:
        for s in servers:
            s.shutdown()
