"""The merge-build-verify loop: the daily build also runs on a push to main
(not for doc-only changes), every build writes its commit to data/build.json
(never into the pages, so unchanged pages stay byte-identical), and the live
check after publish waits for that file before checking the pages. Plus the
tip-off line's weekday spacing."""

from __future__ import annotations

import functools
import http.server
import importlib.util
import json
import re
import threading
from pathlib import Path

import pytest

from conftest import TODAY, _build
from watchguide import build, config

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

def test_build_json_names_this_build_and_no_page_does(built_site):
    data = json.loads((built_site / "data" / "build.json").read_text(encoding="utf-8"))
    assert data["build"] == config.build_id() and data["mode"] == "build"
    assert live_check.BUILD_FILE == build.BUILD_FILE == "data/build.json"
    pages = list(built_site.rglob("index.html"))
    assert pages and not any('name="build"' in p.read_text(encoding="utf-8") for p in pages)


def test_build_id_prefers_the_explicit_value(monkeypatch):
    monkeypatch.setenv("WATCH_GUIDE_BUILD", "abcdef0123456")
    assert config.build_id() == "abcdef0"
    monkeypatch.delenv("WATCH_GUIDE_BUILD")
    monkeypatch.setenv("GITHUB_SHA", "1234567890abcdef")
    assert config.build_id() == "1234567"


def test_pages_are_byte_identical_between_builds_of_different_commits(tmp_path_factory, fixture_games,
                                                                      monkeypatch):
    monkeypatch.setenv("WATCH_GUIDE_BUILD", "aaaaaaa")
    one = _build(tmp_path_factory, fixture_games, "site-build-a")
    monkeypatch.setenv("WATCH_GUIDE_BUILD", "bbbbbbb")
    two = _build(tmp_path_factory, fixture_games, "site-build-b")
    pages = sorted(p.relative_to(one) for p in one.rglob("index.html"))
    assert pages and pages == sorted(p.relative_to(two) for p in two.rglob("index.html"))
    assert all((one / p).read_bytes() == (two / p).read_bytes() for p in pages)
    assert json.loads((two / "data" / "build.json").read_text(encoding="utf-8"))["build"] == "bbbbbbb"


def test_the_refresh_writes_build_json_too(tmp_path_factory, fixture_games, monkeypatch):
    site = _build(tmp_path_factory, fixture_games, "site-build-refresh")
    monkeypatch.setenv("WATCH_GUIDE_BUILD", "ccccccc")
    build.refresh_build(site, today=TODAY, now=f"{TODAY}T12:00:00-05:00")
    data = json.loads((site / "data" / "build.json").read_text(encoding="utf-8"))
    assert (data["build"], data["mode"]) == ("ccccccc", "refresh")


# -- live check -------------------------------------------------------------------------------

SHA = "0123456789abcdef"
TITLES = {"": "How to watch the NBA", "miami-heat": "Heat: How to Watch", "tonight": "NBA tonight",
          "spain": "Spanish players"}


@pytest.fixture
def site(tmp_path):
    for page, title in TITLES.items():
        d = tmp_path / page if page else tmp_path
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(f"<html><head><title>{title}</title></head></html>", encoding="utf-8")
    return tmp_path


def served(builds, title_for=None, robots: str = "", status: int = 200, headers=None):
    """A fake fetch. build.json answers with builds[n] on its n-th request
    (the last one from then on); pages with their built title."""
    builds = [builds] if isinstance(builds, str) else list(builds)
    calls = []

    def get(url):
        calls.append(url)
        path = url.split("?")[0]
        if path.endswith("/data/build.json"):
            n = sum(1 for c in calls if c.split("?")[0] == path)
            b = builds[min(n, len(builds)) - 1]
            return (200, {}, json.dumps({"build": b, "mode": "build"})) if b is not None else (404, {}, "")
        page = path.replace(live_check.BASE, "").strip("/")
        title = (title_for or {}).get(page, TITLES[page])
        meta = f'<meta name="robots" content="{robots}">' if robots else ""
        return status, dict(headers or {}), f"<html><head><title>{title}</title>{meta}</head></html>"
    get.calls = calls
    return get


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += s


def check(site, get, **kw):
    clock = Clock()
    ok, report = live_check.run(site, SHA, get=get, sleep=clock.sleep, clock=clock, **kw)
    return ok, report, clock


def test_passes_first_time_when_the_live_site_matches(site):
    get = served(SHA[:7])
    ok, report, _ = check(site, get)
    assert ok and (report["build_attempts"], report["page_attempts"]) == (1, 1)
    assert get.calls[0] == "https://hoopsmatic.com/how-to-watch/data/build.json?v=0123456-1"
    assert [u.split("?")[0] for u in get.calls[1:]] == [
        "https://hoopsmatic.com/how-to-watch", "https://hoopsmatic.com/how-to-watch/miami-heat",
        "https://hoopsmatic.com/how-to-watch/tonight", "https://hoopsmatic.com/how-to-watch/spain"]
    assert all("?v=0123456-" in u for u in get.calls)


def test_waits_for_build_json_before_checking_pages(site):
    get = served([None, "aaaaaaa", SHA[:7]])            # not there yet, the old build, then this one
    ok, report, clock = check(site, get)
    assert ok and report["build_attempts"] == 3 and clock.now == 2 * live_check.INTERVAL
    first_page = next(i for i, u in enumerate(get.calls) if "build.json" not in u)
    assert first_page == 3                               # no page fetched before the build matched


def test_fails_after_ten_minutes_when_the_build_is_never_served(site):
    get = served("aaaaaaa")
    ok, report, clock = check(site, get)
    assert not ok and live_check.TIMEOUT - live_check.INTERVAL <= clock.now <= live_check.TIMEOUT
    assert report["pages"] == {} and all("build.json" in u for u in get.calls)
    assert "Pages not checked" in live_check.summary(ok, report)


@pytest.mark.parametrize("get, field", [
    (served(SHA[:7], status=404), "status"),
    (served(SHA[:7], title_for={"spain": "Something else"}), "title_ok"),
    (served(SHA[:7], robots="noindex,follow"), "robots_noindex"),
    (served(SHA[:7], headers={"x-robots-tag": "noindex"}), "robots_noindex"),
])
def test_each_page_check_can_fail_on_its_own(site, get, field):
    ok, report, _ = check(site, get, timeout=0)
    bad = [r for r in report["pages"].values() if not r["ok"]]
    assert not ok and bad
    if field == "status":
        assert all(r["status"] == 404 for r in bad)
    elif field == "robots_noindex":
        assert all(r["robots_noindex"] for r in bad)
    else:
        assert all(not r[field] for r in bad)


def test_page_checks_retry_within_the_same_ten_minutes(site):
    good, bad = served(SHA[:7]), served(SHA[:7], status=503)
    n = []

    def get(url):
        n.append(url)
        return (bad if len(n) <= 5 else good)(url)       # build.json, then one failed round of pages
    ok, report, _ = check(site, get)
    assert ok and report["page_attempts"] == 2


def test_summary_lists_the_build_and_every_page(site):
    ok, report, _ = check(site, served(SHA[:7], title_for={"spain": "Old"}), timeout=0)
    text = live_check.summary(ok, report)
    assert text.startswith("### Live check: FAILED")
    assert "data/build.json`: serves this build" in text
    assert text.count("| https://hoopsmatic.com/how-to-watch") == 4 and "got “Old”" in text


def test_main_writes_the_job_summary(site, monkeypatch, tmp_path):
    out = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(out))
    monkeypatch.setattr(live_check, "fetch", served(SHA[:7]))
    assert live_check.main(["--site", str(site), "--sha", SHA]) == 0
    assert out.read_text(encoding="utf-8").startswith("### Live check: passed")


def test_requests_are_browser_like(monkeypatch):
    """The same curl_cffi impersonation profile the build uses for cdn.nba.com."""
    from watchguide.sources import http as http_source
    seen = {}

    class Resp:
        status_code, headers, text = 200, {"X-Robots-Tag": "all"}, "ok"

    def fake_get(url, **kw):
        seen.update(kw, url=url)
        return Resp()
    requests = pytest.importorskip("curl_cffi.requests")
    monkeypatch.setattr(requests, "get", fake_get)
    assert live_check.fetch("https://example.test/x") == (200, {"x-robots-tag": "all"}, "ok")
    assert seen["impersonate"] == http_source.IMPERSONATE and seen["url"] == "https://example.test/x"


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
