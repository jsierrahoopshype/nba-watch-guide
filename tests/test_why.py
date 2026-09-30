"""'Why can't I watch this game?' under each schedule row."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from conftest import _build, _copy_data
from watchguide.coverage import IN_MARKET, OUT_OF_MARKET, with_local_options
from watchguide.model import Game, load_copy, load_local_tv, load_services
from watchguide.why import explain

ROOT = Path(__file__).resolve().parent.parent
RULES = json.loads((ROOT / "data" / "services.json").read_text(encoding="utf-8"))["rules"]["league_pass_blackouts"]
TEXT = load_copy()["why"]


def game(national=(), home_tv=()) -> Game:
    day = date(2027, 1, 15).isoformat()
    return Game(game_id="0022600001", game_code="x", date_et=day, tipoff_et=f"{day}T19:00:00-05:00",
                tipoff_utc=f"{day}T00:00:00+00:00", status_text="", home_tricode="MIA",
                away_tricode="NYK", national=list(national), home_tv=list(home_tv))


@pytest.fixture(scope="module")
def heat():
    services, local = load_services(), load_local_tv()["miami-heat"]
    return {state: (with_local_options(services, local, state), local) for state in (OUT_OF_MARKET, IN_MARKET)}


def lines(heat, g, state):
    sd, local = heat[state]
    return explain(g, "MIA", sd, local, state, TEXT)


def test_national_game_names_the_carrier_and_the_national_rule(heat):
    out = lines(heat, game(national=["ESPN"]), OUT_OF_MARKET)
    assert out[0] == ("Watch it on ESPN Unlimited, or on live TV with YouTube TV, Hulu + Live TV, Sling, Fubo "
                      "or DirecTV.")
    assert out[1] == f"NBA League Pass: {RULES['national']}"
    assert len(out) == 2


def test_national_game_in_market_gives_one_reason_not_both(heat):
    inside = lines(heat, game(national=["ESPN"], home_tv=["WPLG"]), IN_MARKET)
    assert f"NBA League Pass: {RULES['national']}" in inside
    assert f"NBA League Pass: {RULES['local']}" not in inside


def test_local_game_in_market_is_on_local_tv_and_blacked_out_on_league_pass(heat):
    inside = lines(heat, game(home_tv=["WPLG"]), IN_MARKET)
    assert inside[0] == "Watch it on Local TV over the air or Local 10+ Platinum."
    assert inside[1] == f"NBA League Pass: {RULES['local']}"


def test_local_game_out_of_market_is_on_league_pass(heat):
    out = lines(heat, game(home_tv=["WPLG"]), OUT_OF_MARKET)
    assert out[0] == "Watch it on NBA League Pass."
    assert not any(l.startswith("NBA League Pass:") for l in out)


def test_a_game_nobody_carries(heat):
    out = lines(heat, game(national=["Telemundo"]), OUT_OF_MARKET)
    assert out[0] == TEXT["none"]


def test_unconfirmed_services_are_never_named(tmp_path_factory):
    """A live TV package whose lineup has the channel unchecked or not
    carried is never named, even though the service exists."""
    data_dir = _copy_data(tmp_path_factory, "data-why-unchecked")
    raw = json.loads((data_dir / "services.json").read_text(encoding="utf-8"))
    for svc in raw["services"]:
        for pkg in (svc.get("lineup") or {}).get("packages", []):
            for ch in pkg["channels"]:
                if ch["channel"] == "ESPN":
                    ch.update({"status": "not_carried" if svc["id"] == "hulu_live_tv" else "unchecked"})
    (data_dir / "services.json").write_text(json.dumps(raw), encoding="utf-8")
    services, local = load_services(data_dir), load_local_tv(data_dir)["miami-heat"]
    for state in (OUT_OF_MARKET, IN_MARKET):
        text = " ".join(explain(game(national=["ESPN"]), "MIA", with_local_options(services, local, state),
                                local, state, TEXT))
        for name in ("YouTube TV", "Hulu + Live TV", "Sling TV", "Fubo", "DirecTV"):
            assert name not in text


def test_every_schedule_row_explains_both_markets(built_site, teams):
    for team in teams:
        html = (built_site / team.slug / "index.html").read_text(encoding="utf-8")
        body = html[html.index("<tbody>"):html.index("</tbody>")]
        rows = re.findall(r"<tr>(.*?)</tr>", body, re.S)
        assert rows
        for row in rows:
            assert row.count('<details class="why">') == 1
            assert re.search(r'data-state-panel="out_of_market">', row)
            assert re.search(r'data-state-panel="in_market" hidden>', row)


def test_rule_wording_comes_from_services_json(tmp_path_factory, fixture_games):
    data_dir = _copy_data(tmp_path_factory, "data-why-rules")
    services = json.loads((data_dir / "services.json").read_text(encoding="utf-8"))
    services["rules"]["league_pass_blackouts"]["national"] = "TEST NATIONAL RULE WORDING."
    services["rules"]["league_pass_blackouts"]["local"] = "TEST LOCAL RULE WORDING."
    (data_dir / "services.json").write_text(json.dumps(services), encoding="utf-8")
    site = _build(tmp_path_factory, fixture_games, "site-why-rules", data_dir=data_dir)
    html = (site / "miami-heat" / "index.html").read_text(encoding="utf-8")
    sched = html[html.index("<tbody>"):]
    assert "NBA League Pass: TEST NATIONAL RULE WORDING." in sched
    assert "NBA League Pass: TEST LOCAL RULE WORDING." in sched
    assert RULES["national"] not in sched


def test_no_rule_text_in_the_code():
    for path in (ROOT / "watchguide" / "why.py", ROOT / "templates" / "team.html"):
        text = path.read_text(encoding="utf-8")
        for phrase in ("6am", "three days", "blacked out", "Nationally broadcast"):
            assert phrase not in text, (path.name, phrase)


def test_no_not_carried_lists(built_site, teams):
    for team in teams:
        html = (built_site / team.slug / "index.html").read_text(encoding="utf-8")
        body = html[html.index("<tbody>"):html.index("</tbody>")]
        assert "Not on " not in body
        for block in re.findall(r'class="why-body"[^>]*>(.*?)</div>', body, re.S):
            assert 1 <= block.count("<p>") <= 2
