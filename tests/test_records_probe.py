"""The team-records probe: whether the schedule feed carries team records or
final scores. It is printed by verify and lands in every build's summary."""

from __future__ import annotations

from watchguide.sources.schedule import team_records_probe


def raw(sides):
    games = [{"gameId": f"002260000{i}", "homeTeam": h, "awayTeam": a} for i, (h, a) in enumerate(sides)]
    return {"leagueSchedule": {"seasonYear": "2026-27", "gameDates": [{"games": games}]}}


def test_keys_present_but_zero_before_the_season():
    zero = {"teamTricode": "BOS", "wins": 0, "losses": 0, "score": 0}
    line = team_records_probe(raw([(zero, zero), (zero, zero)]))
    assert line == ("team records probe (schedule feed): records: wins/losses present, non-zero on 0 of 2 games; "
                    "scores: score present, non-zero on 0 of 2 games")


def test_keys_absent():
    bare = {"teamTricode": "BOS"}
    assert team_records_probe(raw([(bare, bare)])) == (
        "team records probe (schedule feed): records: not in the feed; scores: not in the feed")


def test_filled_in_season():
    played = {"teamTricode": "BOS", "wins": 3, "losses": 1, "score": 112}
    later = {"teamTricode": "NYK", "wins": 0, "losses": 0, "score": 0}
    line = team_records_probe(raw([(played, played), (later, later)]))
    assert "records: wins/losses present, non-zero on 1 of 2 games" in line
    assert "scores: score present, non-zero on 1 of 2 games" in line


def test_empty_feed():
    assert team_records_probe({}) == "team records probe (schedule feed): no games in the schedule feed"


def test_the_probe_reaches_the_build_summary(tmp_path, monkeypatch, fixture_games):
    """A full (not offline) build, every network source stubbed: the probe line
    is in the build notes, and so in the GitHub job summary."""
    from conftest import TODAY
    from watchguide.build import full_build
    from watchguide.cli import _report
    from watchguide.sources import careers, injuries as injuries_source, schedule as schedule_source

    def side(tricode):
        return {"teamTricode": tricode, "wins": 0, "losses": 0, "score": 0}

    feed = {"leagueSchedule": {"seasonYear": "2026-27", "gameDates": [{"games": [
        {"gameId": g.game_id, "gameCode": g.game_code, "gameDateTimeUTC": g.tipoff_utc,
         "homeTeam": side(g.home_tricode), "awayTeam": side(g.away_tricode),
         "broadcasters": {"nationalBroadcasters": [{"broadcasterAbbreviation": c, "broadcasterMedia": "tv"}
                                                   for c in g.national]}}
        for g in fixture_games]}]}}
    monkeypatch.setattr(schedule_source, "fetch_raw", lambda: feed)
    monkeypatch.setattr(injuries_source, "fetch_raw", lambda: [])
    monkeypatch.setattr(injuries_source, "fetch_player_teams", lambda: {})
    monkeypatch.setattr(careers, "get", lambda *a, **k: [])
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    outcome = full_build(tmp_path / "site", today=TODAY, repo_root=tmp_path)
    expected = (f"team records probe (schedule feed): records: wins/losses present, non-zero on 0 of "
                f"{len(fixture_games)} games; scores: score present, non-zero on 0 of {len(fixture_games)} games")
    assert expected in outcome.notes
    _report(outcome)
    assert f"- {expected}" in summary.read_text(encoding="utf-8")
