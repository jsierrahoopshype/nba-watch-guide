"""The availability feed is a change log, so only the latest row per player
counts and last season's rows must not carry over."""

from __future__ import annotations

from watchguide.sources.injuries import (ALLOWED_STATUSES, latest_per_player,
                                         normalize, normalize_name, normalize_status)

TEAMS = {"anthony edwards": "MIN", "nikola jokic": "DEN", "old timer": "BOS"}

LOG = [
    {"player": "Anthony Edwards", "status": "Out", "injury": "Knee", "date": "2026-11-02"},
    {"player": "Anthony Edwards", "status": "Questionable", "injury": "Knee", "date": "2026-11-09"},
    {"player": "Anthony Edwards", "status": "Available", "injury": "Knee", "date": "2026-11-12"},
    {"player": "Nikola Jokic", "status": "Doubtful", "injury": "Wrist", "date": "2026-11-11"},
    {"player": "Old Timer", "status": "Out", "injury": "Achilles", "date": "2026-05-08"},
]

SEASON_START = "2026-10-20"


def test_only_the_latest_row_per_player_survives():
    latest = latest_per_player(LOG, since=SEASON_START)
    assert latest["anthony edwards"]["status"] == "Available"
    assert latest["anthony edwards"]["date"] == "2026-11-12"


def test_rows_from_before_the_season_are_dropped():
    latest = latest_per_player(LOG, since=SEASON_START)
    assert "old timer" not in latest
    assert "old timer" in latest_per_player(LOG, since="")


def test_normalize_groups_by_team_and_reports_as_of():
    result = normalize(LOG, TEAMS, since=SEASON_START)
    assert sorted(result["by_team"]) == ["DEN", "MIN"]
    assert result["by_team"]["MIN"] == [
        {"player": "Anthony Edwards", "status": "Available", "injury": "Knee", "date": "2026-11-12"}]
    assert result["as_of"] == "2026-11-12"
    assert result["unmatched"] == []


def test_players_are_sorted_worst_status_first():
    log = [
        {"player": "Anthony Edwards", "status": "Probable", "date": "2026-11-12"},
        {"player": "Nikola Jokic", "status": "Out", "date": "2026-11-12"},
    ]
    result = normalize(log, {"anthony edwards": "MIN", "nikola jokic": "MIN"}, since=SEASON_START)
    assert [p["status"] for p in result["by_team"]["MIN"]] == ["Out", "Probable"]


def test_unknown_statuses_are_left_out_rather_than_reinterpreted():
    log = [{"player": "Anthony Edwards", "status": "Left Game", "date": "2026-11-12"}]
    result = normalize(log, TEAMS, since=SEASON_START)
    assert result["by_team"] == {}
    assert result["skipped_status"] == 1
    assert normalize_status("Left Game") is None
    for status in ALLOWED_STATUSES:
        assert normalize_status(status.lower()) == status


def test_players_with_no_current_team_are_reported_not_guessed():
    log = [{"player": "Nobody Here", "status": "Out", "date": "2026-11-12"}]
    result = normalize(log, TEAMS, since=SEASON_START)
    assert result["by_team"] == {}
    assert result["unmatched"] == ["Nobody Here"]


def test_name_matching_folds_accents_and_suffixes():
    assert normalize_name("Nikola Jokić") == "nikola jokic"
    assert normalize_name("Gary Payton II") == "gary payton"
    assert normalize_name("Jaren Jackson Jr.") == "jaren jackson"
