"""Antenna (virtual) channel numbers for over-the-air stations: stored with
two sources and a check date in data/local_tv.json, shown on chips and the
team page only when confirmed, never a cable or satellite number, and one
"channel numbers vary" line per block that shows one."""

from __future__ import annotations

import json
import re

import pytest

from conftest import TODAY, _build, _copy_data
from watchguide.context import load_context
from watchguide.model import AntennaChannel, load_local_tv, load_teams
from watchguide.pages.common import chips, watch_view

CABLE = "Cable and satellite channel numbers vary by provider; check your guide."
BY_TRICODE = {t.tricode: t for t in load_teams()}
TWO_SOURCES = [{"url": "https://www.rabbitears.info/market.php?request=station_search&callsign=WPLG"},
               {"url": "https://www.local10.com/about-us/"}]


def entry(**kw):
    base = dict(station="WPLG", names=["WPLG Local 10", "WPLG"], virtual="10.1", status="confirmed",
                sources=TWO_SOURCES, checked="2026-09-30")
    base.update(kw)
    return AntennaChannel(**base)


# -- the confirmation rule --------------------------------------------------------------------

def test_confirmed_needs_status_number_date_and_two_sites():
    assert entry().confirmed
    assert not entry(status="unset").confirmed
    assert not entry(virtual="10").confirmed                   # needs the subchannel
    assert not entry(virtual="Channel 10").confirmed
    assert not entry(checked="").confirmed
    assert not entry(sources=TWO_SOURCES[:1]).confirmed        # one source
    assert not entry(sources=[{"url": "https://www.local10.com/a"}, {"url": "https://local10.com/b"}]).confirmed


def test_shipped_file_never_shows_an_unconfirmed_number():
    for slug, local in load_local_tv().items():
        for a in local.antenna_channels:
            assert a.status in ("confirmed", "unset", "not_applicable"), (slug, a.station)
            assert a.names and all(n in local.local_broadcasters or n == n.upper() for n in a.names), \
                (slug, a.names)
            if a.status != "confirmed":
                assert a.reason and not local.antenna_channel(a.names[0]), (slug, a.station)
            else:
                assert a.confirmed, f"{slug} {a.station} is marked confirmed but fails the two-source rule"


def test_no_entry_for_streaming_apps_or_regional_networks():
    raw = json.loads((_copy_path() / "local_tv.json").read_text(encoding="utf-8"))["teams"]
    for slug, t in raw.items():
        names = {n for a in t.get("antenna_channels") or [] for n in a["names"]}
        streaming = {o.get("name") for o in t.get("streaming") or []}
        assert not names & streaming, slug
        if (t.get("ota") or {}).get("status") == "none":
            assert not t.get("antenna_channels"), slug          # RSN-only markets


def _copy_path():
    from watchguide import config
    return config.DATA_DIR


# -- rendering ------------------------------------------------------------------------------

def confirmed_data(tmp_path_factory, label="data-antenna"):
    """A copy of data/ with WPLG confirmed as 10.1."""
    data_dir = _copy_data(tmp_path_factory, label)
    raw = json.loads((data_dir / "local_tv.json").read_text(encoding="utf-8"))
    for a in raw["teams"]["miami-heat"]["antenna_channels"]:
        a.update(virtual="10.1", status="confirmed", sources=TWO_SOURCES, checked="2026-09-30", reason="")
    (data_dir / "local_tv.json").write_text(json.dumps(raw), encoding="utf-8")
    return data_dir


@pytest.fixture(scope="module")
def antenna_site(tmp_path_factory, fixture_games):
    return _build(tmp_path_factory, fixture_games, "site-antenna", data_dir=confirmed_data(tmp_path_factory))


def heat_game(fixture_games):
    return next(g for g in fixture_games if g.date_et >= TODAY and g.involves("MIA") and not g.national)


def test_chip_reads_station_antenna_channel_then_market(tmp_path_factory, fixture_games):
    ctx = load_context(fixture_games, today=TODAY, data_dir=confirmed_data(tmp_path_factory, "data-antenna-ctx"))
    game = heat_game(fixture_games)
    watch = watch_view(ctx, game)
    heat = [c for c in watch["chips"] if c["name"] == "WPLG Local 10"]
    assert heat and heat[0]["antenna"] == "antenna ch. 10.1" and heat[0]["how"] == "Heat market"
    assert all(not c["antenna"] for c in watch["chips"] if c["name"] != "WPLG Local 10")
    assert watch["cable_note"] == CABLE
    # National channels and streaming names never get a number.
    national = chips(ctx, [{"name": "ESPN", "kind": "national"}, {"name": "WPLG Local 10", "kind": "national"}],
                     priced=True)
    assert not any(c["antenna"] for c in national)
    assert not chips(ctx, [{"name": "Local 10+ Platinum", "kind": "local", "team": "Heat"}])[0]["antenna"]


def test_game_block_shows_it_once_with_the_cable_line(antenna_site, fixture_games):
    game = heat_game(fixture_games)
    team = BY_TRICODE["MIA"]
    page = (antenna_site / team.slug / "index.html").read_text(encoding="utf-8")
    block = page[page.index("data-game-block"):page.index("</article>")]
    assert ('<span class="chip-name">WPLG Local 10</span><span class="chip-how" data-antenna>· antenna ch. 10.1</span>'
            '<span class="chip-how">· Heat market</span>') in block
    assert block.count(CABLE) == 1
    assert block.index("data-cable-numbers") < block.index('data-part="when"')     # still in where to watch
    assert game.game_id in page


def test_team_page_row_and_schedule_note(antenna_site):
    page = (antenna_site / "miami-heat" / "index.html").read_text(encoding="utf-8")
    watching = page[page.index('id="watching"'):]
    watching = watching[:watching.index("</section>")]
    assert "WPLG Local 10 · antenna ch. 10.1" in watching and watching.count(CABLE) == 1
    table = page[page.index("<table"):page.index("</table>") + 200]
    assert "· antenna ch. 10.1" in table and table.count(CABLE) == 1


def test_no_cable_or_satellite_numbers_anywhere(antenna_site):
    for p in antenna_site.rglob("index.html"):
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r"antenna ch\. ([\d.]+)", text):
            assert m.group(1) == "10.1", (p, m.group(0))
        assert not re.search(r"(?i)\b(cable|satellite|dish|directv) ch(annel)?\.? ?\d", text), p


def test_seo_fields_do_not_move(antenna_site, built_site):
    def fields(site):
        out = {}
        for p in site.rglob("index.html"):
            h = p.read_text(encoding="utf-8")
            out[str(p.relative_to(site))] = [re.search(pat, h).group(1) if re.search(pat, h) else None for pat in (
                r"<title>(.*?)</title>", r'<meta name="description" content="([^"]*)"',
                r'<link rel="canonical" href="([^"]*)"', r'<meta property="og:url" content="([^"]*)"')]
        return out
    assert fields(antenna_site) == fields(built_site)


def test_nothing_shows_without_a_confirmed_number(built_site):
    for p in built_site.rglob("index.html"):
        text = p.read_text(encoding="utf-8")
        assert "data-antenna" not in text and "data-cable-numbers" not in text and CABLE not in text, p
