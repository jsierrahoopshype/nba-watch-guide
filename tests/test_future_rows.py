"""Rows in the availability feed dated more than a day after the build date
are invalid. They must not set a player's status, must not move the feed's
as-of forward (which would hide the out-of-date notice), and the build
summary says how many were dropped and on which dates."""

from __future__ import annotations

import json

from watchguide.build import BuildOutcome, load_injuries
from watchguide.context import load_context
from watchguide.guard import RAW_FILE, snapshot_now, write_raw
from watchguide.sources import injuries as injuries_source
from watchguide.sources.injuries import normalize

from conftest import TODAY  # 2027-01-15, a day with games in the fixture schedule

SEASON_START = "2026-10-20"
TEAMS = {"anthony edwards": "MIN", "nikola jokic": "DEN"}

# Old data (five days before the build) plus one row from months ahead.
OLD_WITH_FUTURE = [
    {"player": "Anthony Edwards", "status": "Out", "injury": "Knee", "date": "2027-01-10"},
    {"player": "Nikola Jokic", "status": "Doubtful", "injury": "Wrist", "date": "2027-01-09"},
    {"player": "Anthony Edwards", "status": "Available", "injury": "", "date": "2027-03-01"},
]


def _patch_feed(monkeypatch, rows):
    monkeypatch.setattr(injuries_source, "fetch_raw", lambda: rows)
    monkeypatch.setattr(injuries_source, "fetch_player_teams", lambda: TEAMS)


def test_future_row_sets_neither_status_nor_as_of():
    result = normalize(OLD_WITH_FUTURE, TEAMS, since=SEASON_START, until="2027-01-16")
    assert result["by_team"]["MIN"][0]["status"] == "Out"          # not the future "Available"
    assert result["as_of"] == "2027-01-10"
    assert result["dropped_future"] == ["2027-03-01"]


def test_one_day_ahead_is_kept_two_days_ahead_is_dropped():
    rows = [{"player": "Anthony Edwards", "status": "Out", "date": "2027-01-16"},
            {"player": "Nikola Jokic", "status": "Out", "date": "2027-01-17"}]
    result = normalize(rows, TEAMS, since=SEASON_START, until="2027-01-16")
    assert result["as_of"] == "2027-01-16"
    assert "DEN" not in result["by_team"]
    assert result["dropped_future"] == ["2027-01-17"]


def test_staleness_warning_still_fires_on_old_data_with_a_future_row(tmp_path, monkeypatch, fixture_games):
    _patch_feed(monkeypatch, OLD_WITH_FUTURE)
    by_team, updated, as_of, note, complaint = load_injuries(
        tmp_path / "site", repo_root=tmp_path, since=SEASON_START, today=TODAY)

    assert complaint == ""
    assert as_of == "2027-01-10"
    ctx = load_context(fixture_games, by_team, updated, as_of, today=TODAY)
    assert ctx.games_today(), "the fixture needs games on the build date"
    assert ctx.availability_is_stale() is True

    # Without the rule the future row would have pushed as-of past the build
    # date and switched the warning off.
    _, _, masked, _, _ = load_injuries(tmp_path / "site2", repo_root=tmp_path / "r2",
                                       since=SEASON_START)
    assert masked == "2027-03-01"
    assert load_context(fixture_games, by_team, updated, masked,
                        today=TODAY).availability_is_stale() is False


def test_the_note_says_how_many_rows_were_dropped_and_when(tmp_path, monkeypatch):
    rows = OLD_WITH_FUTURE + [
        {"player": "Nikola Jokic", "status": "Out", "date": "2027-03-01"},
        {"player": "Nikola Jokic", "status": "Out", "date": "2027-12-13"},
    ]
    _patch_feed(monkeypatch, rows)
    *_, note, _ = load_injuries(tmp_path / "site", repo_root=tmp_path, since=SEASON_START, today=TODAY)
    lines = note.splitlines()
    assert len(lines) == 2
    assert lines[1] == ("injuries: dropped 3 rows dated after 2027-01-16 (more than a day past "
                        "the build date): 2027-03-01 (2), 2027-12-13")


def test_a_clean_feed_adds_no_line(tmp_path, monkeypatch):
    _patch_feed(monkeypatch, OLD_WITH_FUTURE[:2])
    *_, note, _ = load_injuries(tmp_path / "site", repo_root=tmp_path, since=SEASON_START, today=TODAY)
    assert "dropped" not in note and len(note.splitlines()) == 1


def test_the_fallback_copy_is_filtered_too(tmp_path, monkeypatch):
    from watchguide.sources.http import FetchError
    write_raw(tmp_path / RAW_FILE, snapshot_now(OLD_WITH_FUTURE, "test"))

    def boom():
        raise FetchError("upstream is down")

    monkeypatch.setattr(injuries_source, "fetch_raw", boom)
    monkeypatch.setattr(injuries_source, "fetch_player_teams", lambda: TEAMS)
    by_team, _, as_of, note, complaint = load_injuries(
        tmp_path / "site", repo_root=tmp_path, since=SEASON_START, today=TODAY)
    assert complaint and as_of == "2027-01-10"
    assert by_team["MIN"][0]["status"] == "Out"
    assert "dropped 1 row dated after 2027-01-16" in note


def test_the_dropped_line_reaches_the_build_summary(tmp_path, monkeypatch, capsys):
    from watchguide.cli import _report
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    line = "injuries: dropped 1 row dated after 2027-01-16 (more than a day past the build date): 2027-03-01"
    assert _report(BuildOutcome(notes=["injuries: 3 raw rows", line])) == 0
    text = summary.read_text(encoding="utf-8")
    assert "### Watch guide build" in text and f"- {line}" in text
    assert line in capsys.readouterr().out
