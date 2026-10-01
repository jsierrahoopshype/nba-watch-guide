"""'What am I missing?' on the team pages."""

from __future__ import annotations

import itertools
import json
import random
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import _build, _copy_data
from watchguide.coverage import IN_MARKET, OUT_OF_MARKET, STATES, build_state_coverage
from watchguide.missing import ANTENNA, answer, payload
from watchguide.model import load_local_tv, load_services

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "assets" / "watch-guide.js"
DATA_RE = re.compile(r'<script type="application/json" id="missing-data">(.*?)</script>', re.S)
ROOT_DIV = '<div class="missing" data-missing-root hidden></div>'


def embedded(site: Path, slug: str) -> dict:
    html = (site / slug / "index.html").read_text(encoding="utf-8")
    return json.loads(DATA_RE.search(html).group(1))


def node_answers(cases: list[dict]) -> list[dict]:
    """Run the page's own answer() under Node on each case."""
    script = ("const m = require(process.argv[1]);"
              "const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
              "process.stdout.write(JSON.stringify(cases.map(c => m.answer(c.data, c.state, c.owned))));")
    out = subprocess.run(["node", "-e", script, str(JS)], input=json.dumps(cases),
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def owned_sets(options: list[str], seed: int) -> list[list[str]]:
    sets = [[]] + [[o] for o in options] + [list(p) for p in itertools.combinations(options, 2)]
    rng = random.Random(seed)
    for _ in range(40):
        sets.append(rng.sample(options, rng.randint(0, len(options))))
    return sets


# -- the page script matches the Python reference -------------------------------

@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("slug", ["miami-heat", "boston-celtics", "los-angeles-lakers",
                                  "charlotte-hornets", "toronto-raptors"])
def test_page_script_matches_the_python_reference(built_site_priced, slug):
    data = embedded(built_site_priced, slug)["data"]
    ids = [o["id"] for o in data["options"]]
    cases = [{"data": data, "state": state, "owned": owned}
             for state in STATES for owned in owned_sets(ids, seed=len(slug))]
    expected = [answer(c["data"], c["state"], set(c["owned"])) for c in cases]
    got = node_answers(cases)
    assert got == expected
    # The comparison is only worth something if the cases hit every branch.
    assert any(e["set"] and e["set"]["complete"] for e in expected)
    assert any(e["single"] for e in expected)
    assert any(not e["missing"] for e in expected)


# -- the matrix comes straight from the coverage engine ---------------------------

def test_matrix_matches_the_coverage_engine(fixture_games):
    services, local = load_services(), load_local_tv()["miami-heat"]
    games = [g for g in fixture_games if g.involves("MIA")]
    covs = {s: build_state_coverage(games, "MIA", services, local, s) for s in STATES}
    data = payload([{"d": g.date_et, "o": g.game_id} for g in games], covs, "Antenna")
    ids = [o["id"] for o in data["options"]]
    assert ANTENNA in ids and "local-miami-heat-0" in ids
    assert "antenna_abc" not in ids                                   # grouped under Antenna
    assert {"youtube_tv", "hulu_live_tv", "sling_tv", "fubo", "fubo_elite", "directv_stream"} <= set(ids)
    for state in STATES:
        everything = answer(data, state, set(ids))
        assert everything["covered"] == len(games) - len(covs[state].uncovered)
        for c in covs[state].per_service:
            if c.service.carries_verified and c.service.kind != "ota":
                assert int(next(o for o in data["options"] if o["id"] == c.service.id)["m"][state], 16) == c.mask


def test_an_add_on_costs_its_own_price_once_you_have_what_it_needs():
    data = {"games": [{"d": "1", "o": "a"}, {"d": "2", "o": "b"}], "options": [
        {"id": "peacock", "name": "Peacock", "price": 12.99, "req": [], "m": {s: "2" for s in STATES}},
        {"id": "addon", "name": "Local add-on", "price": 15.0, "req": ["peacock"], "m": {s: "3" for s in STATES}},
    ]}
    alone = answer(data, IN_MARKET, set())
    assert alone["single"] == {"id": "addon", "added": 2, "price": 27.99}
    with_peacock = answer(data, IN_MARKET, {"peacock"})
    assert with_peacock["single"] == {"id": "addon", "added": 1, "price": 15.0}
    assert with_peacock["set"] == {"ids": ["addon"], "price": 15.0, "covered": 2, "complete": True}


def test_best_possible_when_no_set_reaches_every_game():
    data = {"games": [{"d": str(i), "o": "x"} for i in range(3)], "options": [
        {"id": "a", "name": "A", "price": 5.0, "req": [], "m": {s: "1" for s in STATES}},
        {"id": "b", "name": "B", "price": None, "req": [], "m": {s: "6" for s in STATES}},
    ]}
    result = answer(data, OUT_OF_MARKET, set())
    assert result["set"] == {"ids": ["a"], "price": 5.0, "covered": 1, "complete": False}


# -- commission-blind -------------------------------------------------------------

@pytest.fixture(scope="module")
def built_site_all_affiliate(tmp_path_factory, fixture_games):
    """The priced build again, with an affiliate link on every service."""
    data_dir = _copy_data(tmp_path_factory, "data-affiliate")
    priced = json.loads((data_dir / "services.json").read_text(encoding="utf-8"))
    base = json.loads((ROOT / "data" / "services.json").read_text(encoding="utf-8"))
    prices = {"antenna_abc": 0.0, "antenna_nbc": 0.0, "espn_unlimited": 11.99,
              "nba_tv": 6.99, "nba_league_pass": 16.99}
    for svc in base["services"]:
        if svc["id"] in prices:
            svc.update(monthly_price_usd=prices[svc["id"]], source_url="https://example.test/pricing",
                       last_verified="2027-01-02", verified=True)
        svc["affiliate_url"] = f"https://example.test/{svc['id']}?ref=commission"
    (data_dir / "services.json").write_text(json.dumps(base), encoding="utf-8")
    return _build(tmp_path_factory, fixture_games, "site-affiliate", data_dir=data_dir)


def test_affiliate_links_change_no_recommendation(built_site_priced, built_site_all_affiliate, teams):
    # Same prices, one build with a single affiliate link, one with a link on
    # every service: the embedded data and every answer must be identical.
    for team in teams:
        plain = embedded(built_site_priced, team.slug)
        paid = embedded(built_site_all_affiliate, team.slug)
        assert paid == plain, team.slug
        assert "example.test" not in json.dumps(paid)
        ids = [o["id"] for o in plain["data"]["options"]]
        for state in STATES:
            for owned in owned_sets(ids, seed=7)[:12]:
                assert answer(paid["data"], state, set(owned)) == answer(plain["data"], state, set(owned))


# -- the prerendered page is unchanged ---------------------------------------------

def test_prerendered_html_only_gains_the_inert_data(built_site, tmp_path_factory, fixture_games,
                                                     monkeypatch, teams):
    from watchguide.pages import team as team_page
    monkeypatch.setattr(team_page, "_missing", lambda *a, **k: None)
    without = _build(tmp_path_factory, fixture_games, "site-no-missing")
    for team in teams:
        html = (built_site / team.slug / "index.html").read_text(encoding="utf-8")
        assert html.count(ROOT_DIV) == 1
        # Whitespace between tags is the only thing Jinja's whitespace
        # control can leave behind where the two elements were cut out.
        squash = lambda text: re.sub(r">\s+<", "><", text)
        stripped = squash(DATA_RE.sub("", html.replace(ROOT_DIV, "")))
        before = squash((without / team.slug / "index.html").read_text(encoding="utf-8"))
        assert stripped == before, team.slug
        assert "What am I missing?" not in DATA_RE.sub("", html)     # no visible wording


# -- storage and privacy ----------------------------------------------------------------

def test_one_site_wide_storage_key_and_nothing_sent():
    js = JS.read_text(encoding="utf-8")
    # The market toggle, the owned-services list and "My team" (the saved team).
    keys = set(re.findall(r"var (?:STORE|OWNED|TEAM)_KEY = '([^']+)'", js))
    assert keys == {"hm-watch-market", "hm-watch-owned", "hm-watch-team"}
    assert re.findall(r"localStorage\.(?:get|set)Item\((\w+)", js) and \
        set(re.findall(r"localStorage\.(?:get|set)Item\((\w+)", js)) == {"STORE_KEY", "OWNED_KEY", "TEAM_KEY"}
    section = js[js.index("what am I missing?"):js.index("function init()")]
    for call in ("fetch(", "XMLHttpRequest", "sendBeacon", "sessionStorage", "document.cookie"):
        assert call not in section
