"""The page script's "Who's out" rebuild, in a real browser at 375px.

Between full builds the pages read availability from the how-to-watch-live
Worker (/how-to-watch/live/<file>) and rebuild the Who's out lists from it
(assets/watch-guide.js renderOut, renderHubOut). Each case loads a page
built from one injury report, feeds it another, and checks the result is
exactly what a build from that second report renders: same elements,
classes, players, badges and wording. Fed the data it was built from, a page
must not change at all (no mutation, no layout shift). With the Worker
answering 404, the page falls back to the published /data/ file.
"""

from __future__ import annotations

import pytest

from conftest import TODAY, _build
from test_my_team import CLS, _serve
from test_pairs import canonical_slug

PARTS = "[data-live-out], [data-hub-out]"

SHAPE = """sel => Array.from(document.querySelectorAll(sel)).map(box => {
  function shape(node) {
    if (node.nodeType === 3) return node.nodeValue.replace(/\\s+/g, ' ').trim();
    if (node.nodeType !== 1) return '';
    const keep = ['class', 'data-player', 'data-status-slot', 'data-out-message', 'hidden'];
    const attrs = keep.filter(a => node.hasAttribute(a)).map(a => a + '=' + node.getAttribute(a)).join(',');
    return '<' + node.tagName + ' ' + attrs + '>' + Array.from(node.childNodes).map(shape).filter(Boolean).join('') + '</>';
  }
  return shape(box);
})"""

# Installed before any page script: counts every change inside the Who's out
# parts. The page script runs deferred, before DOMContentLoaded, and its
# fetch lands after it, so nothing it does is missed.
COUNT_CHANGES = """window.__outChanges = 0;
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('%s').forEach(box => new MutationObserver(list => {
    window.__outChanges += list.length; }).observe(box, {subtree: true, childList: true, characterData: true, attributes: true}));
});""" % PARTS


def _report(fixture_games, variant: str) -> dict:
    today = sorted((g for g in fixture_games if g.date_et == TODAY), key=lambda g: g.game_id)
    a, b = today[0], today[1]
    rows = {
        "before": [("Home Starter", "Out", a.home_tricode), ("Home Maybe", "Questionable", a.home_tricode),
                   ("Bench Guy", "Doubtful", b.away_tricode)],
        # One cleared, one changed status, one new player out after the build.
        "after": [("Home Starter", "Available", a.home_tricode), ("Home Maybe", "Out", a.home_tricode),
                  ("Late Scratch", "Out", a.away_tricode), ("Bench Guy", "Probable", b.away_tricode)],
        "none": [],
    }[variant]
    return {"updated_at": f"{TODAY}T12:00:00-05:00", "as_of": TODAY, "players": [
        {"player": n, "status": s, "injury": "", "date": TODAY, "team": t} for n, s, t in rows]}


@pytest.fixture(scope="module")
def sites(tmp_path_factory, fixture_games):
    return {v: _build(tmp_path_factory, fixture_games, f"live-out-{v}", injuries=_report(fixture_games, v))
            for v in ("before", "after", "none")}


def _pages(fixture_games):
    first = sorted((g for g in fixture_games if g.date_et == TODAY), key=lambda g: g.game_id)[0]
    return ["", "tonight", canonical_slug(first), "boston-celtics"]


class Served:
    """Each built site on its own local server at /how-to-watch/."""

    def __init__(self, sites, tmp_path):
        self.servers = {}
        for name, site in sites.items():
            root = tmp_path / f"srv-{name}"
            root.mkdir()
            (root / "how-to-watch").symlink_to(site)
            self.servers[name] = _serve(root)

    def url(self, name, rel):
        return f"http://127.0.0.1:{self.servers[name].server_port}/how-to-watch/{rel}"

    def close(self):
        for s in self.servers.values():
            s.shutdown()


@pytest.fixture
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception:
            b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        yield b
        b.close()


def _open(browser, url, live_site=None):
    """The page at 375px with /live/ answered from `live_site`'s data files,
    or 404 when None. Returns (page, urls asked)."""
    page = browser.new_page(viewport={"width": 375, "height": 800})
    page.add_init_script(COUNT_CHANGES)
    asked = []
    page.on("request", lambda r: asked.append(r.url.split("/how-to-watch")[-1].split("?")[0]))

    def live(route):
        if live_site is None:
            return route.fulfill(status=404, content_type="application/json", body="{}")
        name = route.request.url.split("/live/")[1].split("?")[0]
        route.fulfill(status=200, content_type="application/json",
                      body=(live_site / "data" / name).read_text(encoding="utf-8"))
    page.route("**/how-to-watch/live/**", live)
    page.goto(url)
    page.wait_for_function("() => document.readyState === 'complete'")
    page.wait_for_timeout(400)
    return page, asked


@pytest.mark.parametrize("later", ["after", "none"])
def test_live_data_rebuilds_whos_out_like_a_build(sites, fixture_games, tmp_path, browser, later):
    served = Served(sites, tmp_path)
    try:
        for rel in _pages(fixture_games):
            want, _ = _open(browser, served.url(later, rel))
            expected = want.evaluate(SHAPE, PARTS)
            want.close()

            page, asked = _open(browser, served.url("before", rel), live_site=sites[later])
            got = page.evaluate(SHAPE, PARTS)
            label = f"{rel or 'hub'} fed '{later}'"
            assert any(a.startswith("/live/") for a in asked), label
            assert expected, label
            assert got == expected, label
            assert page.evaluate("() => window.__outChanges") > 0, label    # it really was rebuilt
            if later == "after" and rel not in ("", "boston-celtics"):
                assert "Late Scratch" in "".join(got), label
            page.close()
    finally:
        served.close()


def test_its_own_data_changes_nothing(sites, fixture_games, tmp_path, browser):
    served = Served(sites, tmp_path)
    try:
        for rel in _pages(fixture_games):
            page, _ = _open(browser, served.url("before", rel), live_site=sites["before"])
            assert page.evaluate("() => window.__outChanges") == 0, rel or "hub"
            assert page.evaluate(CLS) == 0, rel or "hub"
            page.close()
    finally:
        served.close()


def test_a_404_from_the_worker_falls_back_to_the_published_file(sites, fixture_games, tmp_path, browser):
    served = Served(sites, tmp_path)
    try:
        for rel in _pages(fixture_games):
            page, asked = _open(browser, served.url("before", rel))
            live = [i for i, a in enumerate(asked) if a.startswith("/live/")]
            data = [i for i, a in enumerate(asked) if a.startswith("/data/") and a.endswith(".json")]
            assert live and data and live[0] < data[0], asked
            hosts = {u for u in asked if u.startswith("http")}
            assert not hosts, hosts                                      # nothing off the site
            page.close()
    finally:
        served.close()


def test_the_report_not_available_message_follows_the_same_rule(sites, fixture_games, tmp_path_factory,
                                                                tmp_path, browser):
    """After 3 pm ET, nobody listed on today's teams and a feed not yet on
    today: the build shows "Injury report not available yet", and so does a
    page that gets that report from the Worker."""
    from test_pairs import OLD_FEED, _guard_site
    guard_site, _ = _guard_site(tmp_path_factory, fixture_games, "live-out-guard",
                                f"{TODAY}T16:30:00-05:00", {**OLD_FEED, "updated_at": f"{TODAY}T16:30:00-05:00"})
    served = Served({**sites, "guard": guard_site}, tmp_path)
    try:
        for rel in _pages(fixture_games):
            want, _ = _open(browser, served.url("guard", rel))
            expected = want.evaluate(SHAPE, PARTS)
            want.close()
            page, _ = _open(browser, served.url("before", rel), live_site=guard_site)
            got = page.evaluate(SHAPE, PARTS)
            assert got == expected, rel or "hub"
            if rel != "boston-celtics":
                assert "Injury report not available yet" in "".join(got), rel or "hub"
            page.close()
    finally:
        served.close()
