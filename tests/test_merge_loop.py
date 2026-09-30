"""The merge-build-verify loop: the daily build also runs on a push to main
(not for doc-only changes), every page carries a build marker that the
sitemap lastmod ignores, and the live check after publish waits for this
run's pages. Plus the tip-off line's weekday spacing."""

from __future__ import annotations

import functools
import http.server
import importlib.util
import re
import threading
from pathlib import Path

import pytest

from conftest import TODAY
from watchguide import config, lastmod

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = (ROOT / ".github" / "workflows" / "build-watch-guide-daily.yml").read_text(encoding="utf-8")

spec = importlib.util.spec_from_file_location("live_check", ROOT / "scripts" / "live_check.py")
live_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live_check)


# -- workflow triggers ------------------------------------------------------------------------

def test_build_runs_on_push_to_main_but_not_for_doc_only_changes():
    on = WORKFLOW[WORKFLOW.index("\non:"):WORKFLOW.index("\npermissions:")]
    assert re.search(r"push:\n\s+branches: \[main\]\n\s+paths-ignore:\n\s+- README\.md\n\s+- CLAUDE\.md", on)
    assert "cron: '0 10 * * *'" in on and "workflow_dispatch:" in on      # the old triggers stay


def test_live_check_runs_after_publish_and_before_the_final_failure():
    steps = re.findall(r"- name: (.+)", WORKFLOW)
    assert steps.index("Live check") == steps.index("Publish to gh-pages") + 1
    assert steps[-1] == "Fail if the availability feed was not trusted"
    step = WORKFLOW[WORKFLOW.index("- name: Live check"):]
    assert "if: inputs.publish != false" in step[:400]
    assert 'python scripts/live_check.py --site site --sha "$GITHUB_SHA"' in step[:400]


# -- build marker ------------------------------------------------------------------------------

def test_every_page_carries_the_build_marker(built_site):
    marker = f'<meta name="build" content="{config.build_id()}">'
    pages = list(built_site.rglob("index.html"))
    assert pages and all(marker in p.read_text(encoding="utf-8") for p in pages)


def test_build_id_prefers_the_explicit_value(monkeypatch):
    monkeypatch.setenv("WATCH_GUIDE_BUILD", "abcdef0123456")
    assert config.build_id() == "abcdef0"
    monkeypatch.delenv("WATCH_GUIDE_BUILD")
    monkeypatch.setenv("GITHUB_SHA", "1234567890abcdef")
    assert config.build_id() == "1234567"


def test_build_marker_does_not_move_lastmod(built_site):
    page = (built_site / "miami-heat" / "index.html").read_text(encoding="utf-8")
    other = re.sub(r'<meta name="build" content="[^"]*">', '<meta name="build" content="fffffff">', page)
    assert other != page
    assert lastmod.content_hash(other) == lastmod.content_hash(page)
    assert 'name="build"' not in lastmod.normalise(page)


# -- live check -------------------------------------------------------------------------------

SHA = "0123456789abcdef"


@pytest.fixture
def site(tmp_path):
    for page, title in (("", "How to watch the NBA"), ("miami-heat", "Heat: How to Watch"),
                        ("tonight", "NBA tonight"), ("spain", "Spanish players")):
        d = tmp_path / page if page else tmp_path
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(f"<html><head><title>{title}</title></head></html>", encoding="utf-8")
    return tmp_path


def served(build: str, title_for=None, robots: str = "", status: int = 200, headers=None):
    """A fake fetch: every page answers with `build` and its built title."""
    titles = {"": "How to watch the NBA", "miami-heat": "Heat: How to Watch", "tonight": "NBA tonight",
              "spain": "Spanish players"}
    calls = []

    def get(url):
        calls.append(url)
        page = url.split("?")[0].replace(live_check.BASE, "").strip("/")
        title = (title_for or titles).get(page, titles[page])
        meta = f'<meta name="robots" content="{robots}">' if robots else ""
        return status, dict(headers or {}), (f"<html><head><title>{title}</title>{meta}"
                                            f'<meta name="build" content="{build}"></head></html>')
    get.calls = calls
    return get


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += s


def test_passes_first_time_when_the_live_site_matches(site):
    get, clock = served(SHA[:7]), Clock()
    ok, report = live_check.run(site, SHA, get=get, sleep=clock.sleep, clock=clock)
    assert ok and report["attempts"] == 1
    assert len(get.calls) == 4 and all(re.search(r"\?v=0123456-1$", u) for u in get.calls)
    assert {u.split("?")[0] for u in get.calls} == {
        "https://hoopsmatic.com/how-to-watch", "https://hoopsmatic.com/how-to-watch/miami-heat",
        "https://hoopsmatic.com/how-to-watch/tonight", "https://hoopsmatic.com/how-to-watch/spain"}


def test_waits_until_the_new_build_is_served(site):
    old, new, clock = served("aaaaaaa"), served(SHA[:7]), Clock()
    rounds = []

    def get(url):
        rounds.append(url)
        return (old if len(rounds) <= 8 else new)(url)           # two stale rounds, then the new one
    ok, report = live_check.run(site, SHA, get=get, sleep=clock.sleep, clock=clock)
    assert ok and report["attempts"] == 3 and clock.now == 2 * live_check.INTERVAL


def test_fails_after_ten_minutes_when_it_never_matches(site):
    clock = Clock()
    ok, report = live_check.run(site, SHA, get=served("aaaaaaa"), sleep=clock.sleep, clock=clock)
    assert not ok and live_check.TIMEOUT - live_check.INTERVAL <= clock.now <= live_check.TIMEOUT
    assert all(not r["build_ok"] for r in report["pages"].values())


@pytest.mark.parametrize("fetch, field", [
    (served(SHA[:7], status=404), "status"),
    (served(SHA[:7], title_for={"spain": "Something else"}), "title_ok"),
    (served(SHA[:7], robots="noindex,follow"), "noindex"),
    (served(SHA[:7], headers={"x-robots-tag": "noindex"}), "noindex"),
    (served(""), "build_ok"),
])
def test_each_check_can_fail_on_its_own(site, fetch, field):
    clock = Clock()
    ok, report = live_check.run(site, SHA, get=fetch, sleep=clock.sleep, clock=clock, timeout=0)
    assert not ok
    bad = [r for r in report["pages"].values() if not r["ok"]]
    assert bad
    if field == "status":
        assert all(r["status"] == 404 for r in bad)
    elif field == "noindex":
        assert all(r["robots_noindex"] for r in bad)
    else:
        assert all(not r[field] for r in bad)


def test_summary_lists_every_page(site):
    clock = Clock()
    ok, report = live_check.run(site, SHA, get=served("aaaaaaa"), sleep=clock.sleep, clock=clock, timeout=0)
    text = live_check.summary(ok, report)
    assert text.startswith("### Live check: FAILED")
    assert text.count("| https://hoopsmatic.com/how-to-watch") == 4 and "aaaaaaa" in text


def test_main_writes_the_job_summary(site, monkeypatch, tmp_path):
    out = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(out))
    monkeypatch.setattr(live_check, "fetch", served(SHA[:7]))
    assert live_check.main(["--site", str(site), "--sha", SHA]) == 0
    assert out.read_text(encoding="utf-8").startswith("### Live check: passed")


# -- tip-off line -----------------------------------------------------------------------------

def test_weekday_and_clock_are_separated_by_a_space(built_site, fixture_games, tmp_path):
    """A reader in Madrid sees an evening ET game on the next day: the line
    reads "Sat 1:00 am CET", with a real space, not "Sat1:00 am"."""
    sync_api = pytest.importorskip("playwright.sync_api")
    root = tmp_path / "srv"
    root.mkdir()
    (root / "how-to-watch").symlink_to(built_site)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_api.sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception:
                browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
            page = browser.new_page(viewport={"width": 375, "height": 900}, timezone_id="Europe/Madrid")
            page.goto(f"http://127.0.0.1:{server.server_port}/how-to-watch/tonight")
            lines = page.eval_on_selector_all(".gb-tip-main", "ns => ns.map(n => n.textContent)")
            with_day = [t for t in lines if re.match(r"[A-Z][a-z]{2}", t)]
            assert with_day, lines
            for text in with_day:
                assert re.match(r"[A-Z][a-z]{2} \d{1,2}:\d{2} [ap]m ", text), text
            browser.close()
    finally:
        server.shutdown()
