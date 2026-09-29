"""Today's games on the hub, the next-game-day fallback on the hub and the
tonight page, and what one mobile row carries."""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone

import pytest

from conftest import TODAY, _build, _copy_data
from watchguide.model import load_teams

TEAMS = {t.tricode: t for t in load_teams()}
TAGS = re.compile(r"<[^>]+>")


def hub_block(site) -> str:
    hub = (site / "index.html").read_text(encoding="utf-8")
    start = hub.index("data-hub-games")
    return hub[start:hub.index("</section>", start)]


def rows(block: str) -> list[str]:
    return block.split('<li class="hg-row" ')[1:]


def text(markup: str) -> str:
    return " ".join(html.unescape(TAGS.sub(" ", markup)).split())


def day_after(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


@pytest.fixture(scope="module")
def game_day_site(tmp_path_factory, fixture_games):
    """Today's first game has a player listed Out on its home side."""
    first = sorted((g for g in fixture_games if g.date_et == TODAY), key=lambda g: g.game_id)[0]
    injuries = {"updated_at": f"{TODAY}T12:00:00-05:00", "as_of": TODAY, "players": [
        {"player": "Home Starter", "status": "Out", "injury": "Knee", "date": TODAY, "team": first.home_tricode},
        {"player": "Home Maybe", "status": "Questionable", "injury": "Back", "date": TODAY,
         "team": first.home_tricode}]}
    return _build(tmp_path_factory, fixture_games, "hub-game-day", injuries=injuries), first


@pytest.fixture(scope="module")
def off_day_site(tmp_path_factory, fixture_games):
    """The same schedule with today's games taken out."""
    games = [g for g in fixture_games if g.date_et != TODAY]
    return _build(tmp_path_factory, games, "hub-off-day")


# -- game day --------------------------------------------------------------------------

def test_hub_lists_every_game_today_above_the_team_grid(game_day_site, fixture_games):
    site, _ = game_day_site
    hub = (site / "index.html").read_text(encoding="utf-8")
    block = hub_block(site)
    today = [g for g in fixture_games if g.date_et == TODAY]
    assert len(rows(block)) == len(today)
    assert {r.split('"')[1] for r in rows(block)} == {g.game_id for g in today}
    assert hub.index("data-hub-games") < hub.index('id="teams"')
    assert "<h2 data-rank-heading>Most star power tonight</h2>" in block
    assert "data-rank-basis" in block and "counting only players in uniform tonight" in block
    assert "data-next-day" not in block


def test_teaser_and_old_link_are_gone_and_tonight_link_stays(game_day_site):
    site, _ = game_day_site
    hub = (site / "index.html").read_text(encoding="utf-8")
    assert "data-top3" not in hub
    assert "See tonight&#39;s games and channels" not in hub
    assert '<a href="/how-to-watch/tonight" data-tonight-link>Tonight&#39;s page</a>' in hub_block(site)


def test_tonight_page_keeps_its_own_url_and_canonical(game_day_site):
    site, _ = game_day_site
    page = (site / "tonight" / "index.html").read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://hoopsmatic.com/how-to-watch/tonight">' in page
    assert '<link rel="canonical" href="https://hoopsmatic.com/how-to-watch">' in \
        (site / "index.html").read_text(encoding="utf-8")


# -- one mobile row --------------------------------------------------------------------

def test_row_carries_time_teams_channels_and_line(game_day_site):
    site, first = game_day_site
    row = next(r for r in rows(hub_block(site)) if r.startswith(f'data-game="{first.game_id}"'))
    # Tip time in ET in the HTML, with the hook the page script uses to show local time.
    assert f'data-utc="{first.tipoff_utc}"' in row and "<span data-local-slot>7:00 pm ET</span>" in row
    away, home = TEAMS[first.away_tricode], TEAMS[first.home_tricode]
    # Away first, then home, each with its logo and a link to its page.
    links = re.findall(r'<a class="hg-team-link" href="([^"]+)"><img class="logo" src="([^"]+)"[^>]*>'
                       r'<span class="hg-name">([^<]+)</span></a>', row)
    assert [(href, name) for href, _, name in links] == [
        (f"/how-to-watch/{away.slug}", away.full_name), (f"/how-to-watch/{home.slug}", home.full_name)]
    for (_, src, _), team in zip(links, (away, home)):
        assert re.fullmatch(rf"/how-to-watch/assets/logos/{team.tricode.lower()}\.[0-9a-f]{{10}}\.svg", src), team.tricode
    assert '<span class="hg-at">at</span>' in row
    assert 'class="hg-channels"><span class="badge badge-' in row
    assert '<div class="hg-line small">' in row


def test_out_players_sit_in_a_collapsed_detail_not_the_row(game_day_site):
    site, first = game_day_site
    row = next(r for r in rows(hub_block(site)) if r.startswith(f'data-game="{first.game_id}"'))
    main, _, detail = row.partition('<details class="hg-out small">')
    assert "Home Starter" not in main
    assert "<details" in row and " open" not in detail.split(">")[0]
    assert "<summary>Out (1)</summary>" in detail
    assert f"{TEAMS[first.home_tricode].full_name}: Home Starter" in text(detail)
    assert "Home Maybe" not in row                 # only Out goes in the detail
    others = [r for r in rows(hub_block(site)) if not r.startswith(f'data-game="{first.game_id}"')]
    assert all("hg-out" not in r for r in others)


def test_hub_makes_no_availability_request(game_day_site):
    """No data-player or data-updated hooks, so the script fetches nothing on the hub."""
    site, _ = game_day_site
    hub = (site / "index.html").read_text(encoding="utf-8")
    assert "data-player" not in hub and "data-updated" not in hub


# -- off day ---------------------------------------------------------------------------

def test_hub_shows_the_next_game_day_on_an_off_day(off_day_site, fixture_games):
    block = hub_block(off_day_site)
    nxt = day_after(TODAY)
    label = f"{date.fromisoformat(nxt):%A, %B} {date.fromisoformat(nxt).day}"
    assert f"<h2 data-rank-heading>Next games: {label}</h2>" in block
    assert "data-next-day" in block and f'data-day="{nxt}"' in block
    assert {r.split('"')[1] for r in rows(block)} == {g.game_id for g in fixture_games if g.date_et == nxt}
    assert "Player availability shows here on game day." in block
    assert "hg-out" not in block
    assert "No NBA games" not in block


def test_tonight_page_shows_the_next_game_day_on_an_off_day(off_day_site, fixture_games):
    page = (off_day_site / "tonight" / "index.html").read_text(encoding="utf-8")
    nxt = day_after(TODAY)
    label = f"{date.fromisoformat(nxt):%A, %B} {date.fromisoformat(nxt).day}"
    assert f"<h2 data-rank-heading>Next games: {label}</h2>" in page
    assert "No NBA games scheduled today." not in page
    assert page.count('<article class="game" id="game-') == sum(1 for g in fixture_games if g.date_et == nxt)
    assert "Player availability shows here on game day." in page
    assert "data-player" not in page
    assert '<link rel="canonical" href="https://hoopsmatic.com/how-to-watch/tonight">' in page


def test_after_the_last_game_day_both_pages_say_so(tmp_path_factory, fixture_games):
    games = [g for g in fixture_games if g.date_et < TODAY]
    site = _build(tmp_path_factory, games, "hub-season-over")
    assert "No more games on the schedule." in hub_block(site)
    tonight = (site / "tonight" / "index.html").read_text(encoding="utf-8")
    assert "No NBA games scheduled today. No more games on the schedule." in tonight


# -- tip-off order with Top pick badges --------------------------------------------------

STARS = ("Star Alpha", "Star Bravo", "Star Charlie")     # letters: names are matched without digits


@pytest.fixture(scope="module")
def staggered_site(tmp_path_factory, fixture_games):
    """Today's games tip off an hour apart, and the stars play in the last
    three, so ranking order is the reverse of tip-off order for them."""
    today = sorted((g for g in fixture_games if g.date_et == TODAY), key=lambda g: g.game_id)
    base = datetime.fromisoformat(today[0].tipoff_utc).astimezone(timezone.utc) - timedelta(hours=len(today))
    staggered = {g.game_id: replace(g, tipoff_utc=(base + timedelta(hours=i)).isoformat())
                 for i, g in enumerate(today)}
    games = [staggered.get(g.game_id, g) for g in fixture_games]
    last_three = today[-3:]                            # latest tips; the last has the biggest star
    data_dir = _copy_data(tmp_path_factory, "data-staggered")
    awards = [{"player": STARS[i], "season": "2025-26", "award": "all_nba_first"}
              for i in range(3) for _ in range(i + 1)]
    (data_dir / "recent_awards.json").write_text(json.dumps({"awards": awards}), encoding="utf-8")
    site = tmp_path_factory.mktemp("hub-staggered")
    (site / "data").mkdir()
    (site / "data" / "star-rosters.json").write_text(json.dumps({"fetched_at": "t", "teams": {
        g.home_tricode: [{"player": STARS[i], "all_star": 0}] for i, g in enumerate(last_three)}}),
        encoding="utf-8")
    (site / "data" / "schedule.json").write_text(json.dumps({
        "season": "2026-27", "updated_at": TODAY, "count": len(games),
        "games": [asdict(g) for g in games]}), encoding="utf-8")
    from watchguide.build import full_build
    full_build(site, today=TODAY, offline=True, data_dir=data_dir)
    return site, [staggered[g.game_id] for g in today], last_three


def test_hub_runs_by_tip_time_earliest_first(staggered_site):
    site, today, _ = staggered_site
    block = hub_block(site)
    assert [r.split('"')[1] for r in rows(block)] == [g.game_id for g in today]
    times = re.findall(r'data-utc="([^"]+)"', block)
    assert times == sorted(times)


def test_top_three_ranked_games_carry_the_badge(staggered_site):
    site, _, last_three = staggered_site
    block = hub_block(site)
    picked = [r.split('"')[1] for r in rows(block) if "data-top-pick" in r]
    assert picked == [g.game_id for g in last_three]          # listed in tip order, not rank order
    assert block.count(">Top pick</span>") == 3
    # The badge sits in the card's top line, next to the tip time.
    top = next(r for r in rows(block) if "data-top-pick" in r).split('<div class="hg-channels">')[0]
    assert '<span class="badge badge-top" data-top-pick>Top pick</span>' in top


def test_tonight_page_keeps_ranking_order(staggered_site):
    site, _, last_three = staggered_site
    page = (site / "tonight" / "index.html").read_text(encoding="utf-8")
    ranked = page[page.index("data-ranked"):page.index("</ol>", page.index("data-ranked"))]
    names = re.findall(r"<strong>([^<]+)</strong>", ranked)
    expected = [f"{TEAMS[g.away_tricode].full_name} at {TEAMS[g.home_tricode].full_name}"
                for g in reversed(last_three)]
    assert names[:3] == expected
    assert "Top pick" not in page


def test_heading_lines_and_basis_unchanged(staggered_site):
    site, _, last_three = staggered_site
    block = hub_block(site)
    assert "<h2 data-rank-heading>Most star power tonight</h2>" in block
    assert "counting only players in uniform tonight" in block
    star_row = next(r for r in rows(block) if r.startswith(f'data-game="{last_three[-1].game_id}"'))
    assert '<div class="hg-line small">Star Charlie</div>' in star_row


def test_off_day_list_is_also_in_tip_order_with_badges(off_day_site, fixture_games):
    block = hub_block(off_day_site)
    times = re.findall(r'data-utc="([^"]+)"', block)
    assert times == sorted(times)
    assert block.count(">Top pick</span>") == 3
