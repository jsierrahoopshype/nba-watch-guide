"""With no availability data for the season, pages say so rather than showing
an empty list or an error."""

from __future__ import annotations

import json

import pytest

from watchguide.build import load_injuries
from watchguide.context import load_context
from watchguide.guard import RAW_FILE, snapshot_now, write_raw
from watchguide.render import build_env
from watchguide.pages.common import empty_players_label

FIRST = ["Aaron", "Bradley", "Caris", "Darius", "Evan", "Franz", "Grant", "Herb",
         "Isaiah", "Jalen", "Keegan", "Luke", "Malik", "Naz", "Obi", "Payton",
         "Quentin", "Royce", "Scottie", "Trey"]
LAST = ["Adams", "Brooks", "Carter", "Dunn", "Ellis", "Foster", "Green", "Hart",
        "Ingram", "Jones", "Keller", "Lopez", "Moore", "Nance", "Owens", "Powell"]


def _names(count: int) -> list[str]:
    """Distinct, realistic names. Digits would be stripped by the matcher and
    every name would collapse onto the same key."""
    out = []
    for last in LAST:
        for first in FIRST:
            out.append(f"{first} {last}")
            if len(out) == count:
                return out
    raise ValueError("ran out of names")


@pytest.fixture(scope="session")
def site_no_injuries(built_site):
    """built_site is already built with no availability data at all."""
    return built_site


def test_the_tonight_page_says_there_is_no_report_yet(site_no_injuries):
    html = (site_no_injuries / "tonight" / "index.html").read_text(encoding="utf-8")
    assert "No injury report yet." in html
    assert "Details coming" not in html


def test_the_published_json_is_a_list_not_an_error(site_no_injuries):
    payload = json.loads((site_no_injuries / "data" / "injuries.json").read_text(encoding="utf-8"))
    assert payload["players"] == []
    assert "source_id" in payload and "updated_at" in payload


def test_the_label_switches_once_there_is_data(fixture_games):
    without = load_context(fixture_games, {}, "", "")
    assert empty_players_label(without) == "No injury report yet."
    with_data = load_context(fixture_games, {"BOS": [{"player": "A B", "status": "Out"}]}, "", "")
    assert empty_players_label(with_data) == "Nobody listed."


def test_a_collapsed_feed_keeps_the_last_good_copy_and_complains(tmp_path, monkeypatch):
    from watchguide.sources import injuries as injuries_source

    good = [{"player": name, "status": "Out", "date": "2026-11-02"} for name in _names(200)]
    write_raw(tmp_path / RAW_FILE, snapshot_now(good, "test"))

    monkeypatch.setattr(injuries_source, "fetch_raw", lambda: good[:10])
    monkeypatch.setattr(injuries_source, "fetch_player_teams",
                        lambda: {injuries_source.normalize_name(r["player"]): "BOS" for r in good})

    by_team, _updated, _as_of, note, complaint = load_injuries(
        tmp_path / "site", repo_root=tmp_path, since="2026-10-01")

    assert complaint, "a 95% drop should be reported"
    assert "kept" in note
    assert len(by_team.get("BOS", [])) == 200, "the last good copy should be what renders"


def test_a_clean_fetch_replaces_the_raw_copy(tmp_path, monkeypatch):
    from watchguide.sources import injuries as injuries_source

    rows = [{"player": name, "status": "Out", "date": "2026-11-02"} for name in _names(40)]
    monkeypatch.setattr(injuries_source, "fetch_raw", lambda: rows)
    monkeypatch.setattr(injuries_source, "fetch_player_teams",
                        lambda: {injuries_source.normalize_name(r["player"]): "BOS" for r in rows})

    _by_team, _updated, _as_of, _note, complaint = load_injuries(
        tmp_path / "site", repo_root=tmp_path, since="2026-10-01")

    assert complaint == ""
    saved = json.loads((tmp_path / RAW_FILE).read_text(encoding="utf-8"))
    assert saved["row_count"] == 40


def test_a_failed_fetch_falls_back_and_complains(tmp_path, monkeypatch):
    from watchguide.sources import injuries as injuries_source
    from watchguide.sources.http import FetchError

    good = [{"player": "A B", "status": "Out", "date": "2026-11-02"}]
    write_raw(tmp_path / RAW_FILE, snapshot_now(good, "test"))

    def boom():
        raise FetchError("upstream is down")

    monkeypatch.setattr(injuries_source, "fetch_raw", boom)
    monkeypatch.setattr(injuries_source, "fetch_player_teams", lambda: {"a b": "BOS"})

    by_team, _updated, _as_of, _note, complaint = load_injuries(
        tmp_path / "site", repo_root=tmp_path, since="2026-10-01")

    assert "upstream is down" in complaint
    assert by_team["BOS"][0]["player"] == "A B"


def test_a_degraded_run_marks_the_pages_stale(fixture_games):
    ctx = load_context(fixture_games, {}, "", "", availability_degraded="feed broke")
    assert ctx.availability_is_stale() is True
