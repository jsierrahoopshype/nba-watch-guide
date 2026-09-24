"""Test fixtures.

The schedule here is made up on purpose. It never reaches the published site:
it exists so the page builders, the coverage maths and the SEO output can be
checked without touching the network.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watchguide.build import full_build  # noqa: E402
from watchguide.model import BlackoutRule, Game, Service, ServiceData, load_teams  # noqa: E402

TODAY = "2027-01-15"
NATIONAL_CYCLE = [[], ["ESPN"], ["ABC"], [], ["NBC"], [], ["NBA TV"], []]
LOCAL_BY_TRICODE = {"BOS": "TESTLOCAL1", "LAL": "TESTLOCAL2"}


def _game(index: int, home: str, away: str, day: date) -> Game:
    tip = datetime(day.year, day.month, day.day, 0, 0, tzinfo=timezone.utc) + timedelta(hours=24)
    national = NATIONAL_CYCLE[index % len(NATIONAL_CYCLE)]
    return Game(
        game_id=f"00226{index:05d}",
        game_code=f"{day:%Y%m%d}/{away}{home}",
        date_et=day.isoformat(),
        tipoff_et=(tip - timedelta(hours=5)).replace(tzinfo=None).isoformat() + "-05:00",
        tipoff_utc=tip.isoformat().replace("+00:00", "+00:00"),
        status_text="7:00 pm ET",
        home_tricode=home,
        away_tricode=away,
        national=national,
        home_tv=[LOCAL_BY_TRICODE[home]] if home in LOCAL_BY_TRICODE else [],
        away_tv=[LOCAL_BY_TRICODE[away]] if away in LOCAL_BY_TRICODE else [],
        arena="Test Arena",
        week=1,
    )


@pytest.fixture(scope="session")
def teams():
    return load_teams()


@pytest.fixture(scope="session")
def fixture_games(teams):
    """Every team plays, some games today, some later, some already gone."""
    tricodes = [t.tricode for t in teams]
    start = date.fromisoformat(TODAY)
    games: list[Game] = []
    index = 0
    for offset in range(-2, 8):
        day = start + timedelta(days=offset)
        rotated = tricodes[offset % len(tricodes):] + tricodes[:offset % len(tricodes)]
        for pair in range(0, len(rotated), 2):
            games.append(_game(index, rotated[pair], rotated[pair + 1], day))
            index += 1
    games.sort(key=lambda g: (g.date_et, g.game_id))
    return games


@pytest.fixture(scope="session")
def built_site(tmp_path_factory, fixture_games):
    """The whole site, rendered offline from the fixture schedule."""
    out = tmp_path_factory.mktemp("site")
    cache = out / "data" / "schedule.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({
        "season": "2026-27", "updated_at": TODAY,
        "count": len(fixture_games), "games": [asdict(g) for g in fixture_games],
    }), encoding="utf-8")
    full_build(out, today=TODAY, offline=True)
    return out


@pytest.fixture
def priced_services():
    """A small, made-up price list for the cheapest-combination test."""
    def svc(sid, name, price, carries, kind="streaming"):
        return Service(id=sid, name=name, kind=kind, monthly_price_usd=price,
                       billing_note="", carries=carries, carries_note="",
                       signup_url="", affiliate_url="", source_url="x",
                       last_verified="2027-01-01", verified=True)
    return ServiceData(
        services=[
            svc("free-air", "Free Air", 0.0, ["ABC", "NBC"], kind="ota"),
            svc("sportsnet", "Sports Net", 10.0, ["ESPN"]),
            svc("bundle", "Big Bundle", 40.0, ["ESPN", "ABC", "NBC", "NBA TV"], kind="live_tv"),
            svc("league-pass", "League Pass", 15.0, []),
            svc("pricey", "Pricey Extra", 99.0, ["NBA TV"]),
        ],
        blackouts=[
            BlackoutRule(id="national-broadcast", applies_to="national_broadcast", active=True,
                         label="National games are blacked out.", source_url="x",
                         last_verified="2027-01-01", verified=True),
            BlackoutRule(id="in-market-local", applies_to="in_market_local", active=True,
                         label="Local games are blacked out in market.", source_url="x",
                         last_verified="2027-01-01", verified=True),
        ],
        league_pass_service_id="league-pass",
    )
