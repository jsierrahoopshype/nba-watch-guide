""""My team": a team the reader saves on this device (localStorage
hm-watch-team). The hub shows its next game first; team pages get a "Make
this my team" button. The HTML is the same for everyone, nothing is fetched
or sent, and nothing shifts when a team is saved."""

from __future__ import annotations

import functools
import http.server
import re
import threading

import pytest

from conftest import TODAY, fixture_schedule
from watchguide import config, lastmod
from watchguide.model import load_teams

TEAMS = load_teams()
KEY = "hm-watch-team"


def _hub(built_site) -> str:
    return (built_site / "index.html").read_text(encoding="utf-8")


def _template(html: str) -> str:
    return re.search(r'<template id="my-team-cards" data-volatile>(.*?)</template>', html, re.S).group(1)


def test_hub_has_the_picker_and_one_card_per_team(built_site):
    html = _hub(built_site)
    select = re.search(r'<select id="my-team-select" data-my-team-select>(.*?)</select>', html, re.S).group(1)
    values = re.findall(r'<option value="([^"]*)">', select)
    assert values[0] == "" and sorted(values[1:]) == sorted(t.slug for t in TEAMS)
    cards = re.findall(r'<article class="myt-card" data-team="([^"]+)"', _template(html))
    assert sorted(cards) == sorted(t.slug for t in TEAMS)
    assert 'data-my-team-clear' in html and 'data-my-team-slot' in html


def test_each_card_is_the_teams_next_game_watch_first(built_site):
    games = fixture_schedule()
    template = _template(_hub(built_site))
    for team in TEAMS:
        card = re.search(rf'<article class="myt-card" data-team="{team.slug}".*?</article>', template, re.S).group(0)
        nxt = next(g for g in games if g.involves(team.tricode) and g.date_et >= TODAY)
        assert f'data-utc="{nxt.tipoff_utc}"' in card, team.slug
        # Where to watch comes before the tip time (the game view order).
        assert card.index('data-part="watch"') < card.index('data-part="when"'), team.slug
        assert re.search(r'class="badge badge-', card), team.slug
        assert f'href="{team.path}"' in card, team.slug


def test_the_card_script_runs_in_place_after_the_slot_and_template(built_site):
    html = _hub(built_site)
    script = re.search(r'<script src="(/how-to-watch/assets/my-team\.[0-9a-f]{10}\.js)"></script>', html)
    assert script, "my-team.js must be a plain (not deferred) script"
    pos = script.start()
    assert html.index("data-my-team-slot") < pos and html.index('<template id="my-team-cards"') < pos
    assert html.index("data-my-team-slot") < html.index("data-hub-games")
    # No inline script: a strict Content-Security-Policy cannot break it.
    for tag in re.findall(r"<script(?![^>]*\bsrc=)(?![^>]*application/(?:ld\+)?json)[^>]*>", html):
        pytest.fail(f"inline script on the hub: {tag}")


def test_scripts_only_use_local_storage_and_send_nothing():
    for name in ("my-team.js", "watch-guide.js"):
        js = (config.ASSET_DIR / name).read_text(encoding="utf-8")
        assert "sendBeacon" not in js and "XMLHttpRequest" not in js and "document.cookie" not in js, name
    mine = (config.ASSET_DIR / "my-team.js").read_text(encoding="utf-8")
    assert "fetch(" not in mine and f"'{KEY}'" in mine
    assert f"'{KEY}'" in (config.ASSET_DIR / "watch-guide.js").read_text(encoding="utf-8")


def test_team_pages_have_the_button(built_site):
    for team in TEAMS:
        html = (built_site / team.slug / "index.html").read_text(encoding="utf-8")
        assert f'data-my-team-btn="{team.slug}" aria-pressed="false"' in html, team.slug
        assert 'class="myt-l-make"' in html and 'class="myt-l-mine"' in html


def test_the_hidden_cards_do_not_move_the_hubs_lastmod(built_site):
    html = _hub(built_site)
    changed = html.replace(_template(html), _template(html).replace("All ", "Every "))
    assert changed != html
    assert lastmod.content_hash(changed) == lastmod.content_hash(html)


def _serve(root):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


CLS = """() => new Promise(done => { let total = 0;
  new PerformanceObserver(list => { for (const e of list.getEntries()) if (!e.hadRecentInput) total += e.value; })
    .observe({type: 'layout-shift', buffered: true});
  setTimeout(() => done(total), 800); })"""


def test_saved_team_in_a_real_browser(built_site, tmp_path):
    """375px: the saved team's card is first on the hub with no layout
    shift, the picker changes and clears it, the team page button saves and
    keeps its size, and no request leaves the site."""
    sync_api = pytest.importorskip("playwright.sync_api")
    root = tmp_path / "srv"
    root.mkdir()
    (root / "how-to-watch").symlink_to(built_site)
    server = _serve(root)
    base = f"http://127.0.0.1:{server.server_port}/how-to-watch"
    team, other = TEAMS[0], TEAMS[1]
    try:
        with sync_api.sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception:
                browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
            page = browser.new_page(viewport={"width": 375, "height": 800})
            hosts = set()
            page.on("request", lambda r: hosts.add(r.url.split("/")[2]))

            page.goto(base + "/")
            assert page.evaluate(CLS) == 0
            assert page.eval_on_selector("[data-my-team-slot]", "e => e.children.length") == 0

            page.evaluate(f"localStorage.setItem('{KEY}', '{team.slug}')")
            page.goto(base + "/")
            assert page.evaluate(CLS) == 0
            assert page.eval_on_selector("[data-my-team-slot] .myt-card", "e => e.dataset.team") == team.slug
            assert page.eval_on_selector("[data-my-team-select]", "e => e.value") == team.slug
            card_top, games_top = page.evaluate("""() => [document.querySelector('[data-my-team-slot] .myt-card'),
                document.querySelector('[data-hub-games]')].map(n => n.getBoundingClientRect().top)""")
            assert card_top < games_top
            assert page.evaluate("document.documentElement.scrollWidth") <= 375

            page.select_option("[data-my-team-select]", other.slug)
            assert page.eval_on_selector("[data-my-team-slot] .myt-card", "e => e.dataset.team") == other.slug
            assert page.evaluate(f"localStorage.getItem('{KEY}')") == other.slug
            page.click("[data-my-team-clear]")
            assert page.eval_on_selector("[data-my-team-slot]", "e => e.children.length") == 0
            assert page.evaluate(f"localStorage.getItem('{KEY}')") is None

            page.goto(f"{base}/{team.slug}")
            assert page.evaluate(CLS) == 0
            button = "[data-my-team-btn]"
            width = page.eval_on_selector(button, "e => e.getBoundingClientRect().width")
            assert page.get_attribute(button, "aria-pressed") == "false"
            page.click(button)
            assert page.get_attribute(button, "aria-pressed") == "true"
            assert page.evaluate(f"localStorage.getItem('{KEY}')") == team.slug
            assert page.eval_on_selector(button, "e => e.getBoundingClientRect().width") == width
            page.goto(f"{base}/{team.slug}")
            assert page.get_attribute(button, "aria-pressed") == "true"
            page.click(button)
            assert page.evaluate(f"localStorage.getItem('{KEY}')") is None

            assert hosts == {f"127.0.0.1:{server.server_port}"}, hosts
            browser.close()
    finally:
        server.shutdown()
