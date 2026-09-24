"""Reading broadcasters out of the schedule feed.

The shape here is copied from the live feed on 2026-09-24 (the Christmas Day
Heat at Celtics game), which is what caught the wrong key name the first time.
"""

from __future__ import annotations

import pytest

from watchguide.sources.schedule import normalize
from watchguide.sources.http import FetchError


def _raw_game(game_id: str, broadcasters: dict) -> dict:
    return {
        "gameId": game_id,
        "gameCode": "20261225/MIABOS",
        "gameStatusText": "2:30 pm ET",
        "gameDateEst": "2026-12-25T00:00:00Z",
        "gameDateTimeUTC": "2026-12-25T19:30:00Z",
        "homeTeam": {"teamTricode": "BOS"},
        "awayTeam": {"teamTricode": "MIA"},
        "arenaName": "TD Garden",
        "weekNumber": 10,
        "postponedStatus": "N",
        "broadcasters": broadcasters,
    }


def _feed(*games: dict, season: str = "2026-27") -> dict:
    return {"leagueSchedule": {"seasonYear": season,
                               "gameDates": [{"gameDate": "12/25/2026 00:00:00", "games": list(games)}]}}


CHRISTMAS = {
    "nationalBroadcasters": [
        {"broadcasterAbbreviation": "ABC", "broadcasterMedia": "tv", "broadcasterScope": "natl"},
        {"broadcasterAbbreviation": "ESPN", "broadcasterMedia": "tv", "broadcasterScope": "natl"},
    ],
    "nationalOttBroadcasters": [],
    "nationalRadioBroadcasters": [
        {"broadcasterAbbreviation": "ESPNR", "broadcasterMedia": "radio", "broadcasterScope": "natl"},
        {"broadcasterAbbreviation": "SiriusXM", "broadcasterMedia": "radio", "broadcasterScope": "natl"},
    ],
    "homeTvBroadcasters": [],
    "awayTvBroadcasters": [],
    "awayRadioBroadcasters": [
        {"broadcasterAbbreviation": "WQAM-FM/WAQI", "broadcasterMedia": "radio", "broadcasterScope": "away"},
    ],
}


def test_national_tv_is_read_from_nationalbroadcasters():
    game = normalize(_feed(_raw_game("0022600011", CHRISTMAS)))[0]
    assert game.national == ["ABC", "ESPN"]
    assert game.is_national


def test_national_radio_never_counts_as_a_way_to_watch():
    game = normalize(_feed(_raw_game("0022600011", CHRISTMAS)))[0]
    assert "SiriusXM" not in game.national_codes
    assert "ESPNR" not in game.national_codes
    assert "WQAM-FM/WAQI" not in game.national_codes


def test_a_radio_only_game_is_not_national():
    """An NBA Cup group game with SiriusXM radio but no national TV."""
    raw = _raw_game("0022600015", {
        "nationalBroadcasters": [],
        "nationalOttBroadcasters": [],
        "nationalRadioBroadcasters": [
            {"broadcasterAbbreviation": "SiriusXM", "broadcasterMedia": "radio", "broadcasterScope": "natl"},
        ],
        "homeTvBroadcasters": [],
        "awayTvBroadcasters": [],
    })
    game = normalize(_feed(raw))[0]
    assert game.national == []
    assert not game.is_national
    assert game.national_codes == []


def test_a_radio_entry_mixed_into_nationalbroadcasters_is_skipped():
    raw = _raw_game("0022600020", {
        "nationalBroadcasters": [
            {"broadcasterAbbreviation": "NBC", "broadcasterMedia": "tv", "broadcasterScope": "natl"},
            {"broadcasterAbbreviation": "SiriusXM", "broadcasterMedia": "radio", "broadcasterScope": "natl"},
        ],
    })
    game = normalize(_feed(raw))[0]
    assert game.national == ["NBC"]


def test_streaming_only_games_come_through_too():
    raw = _raw_game("0022600021", {
        "nationalBroadcasters": [],
        "nationalOttBroadcasters": [
            {"broadcasterAbbreviation": "Peacock", "broadcasterMedia": "ott", "broadcasterScope": "natl"},
        ],
    })
    game = normalize(_feed(raw))[0]
    assert game.national_ott == ["Peacock"]
    assert game.is_national


def test_local_broadcasters_are_kept_apart_from_national():
    raw = _raw_game("0022600022", {
        "nationalBroadcasters": [],
        "homeTvBroadcasters": [{"broadcasterAbbreviation": "NBCSB", "broadcasterMedia": "tv"}],
        "awayTvBroadcasters": [{"broadcasterAbbreviation": "WPLG", "broadcasterMedia": "tv"}],
    })
    game = normalize(_feed(raw))[0]
    assert game.home_tv == ["NBCSB"]
    assert game.away_tv == ["WPLG"]
    assert not game.is_national


def test_a_game_with_no_broadcaster_at_all_stays_empty():
    game = normalize(_feed(_raw_game("0022600023", {})))[0]
    assert game.national_codes == []
    assert game.home_tv == [] and game.away_tv == []


def test_the_wrong_season_stops_the_build():
    with pytest.raises(FetchError):
        normalize(_feed(_raw_game("0022600011", CHRISTMAS), season="2025-26"))
