"""The European country pages: data file, SEO, links and every block on the page.

The schedule here is a made-up fortnight around the European clock change
(Sunday 25 October 2026, a week before the US one on 1 November)."""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from conftest import _copy_data
from watchguide import config
from watchguide.build import full_build, refresh_build
from watchguide.countries import (clock, country_players, load_countries, local_tip,
                                  nationality_matches, price_text, watchable_games)
from watchguide.model import Game
from watchguide.sources import careers

ROOT = Path(__file__).resolve().parent.parent
SLUGS = ("uk", "spain", "france", "germany", "italy")
TODAY = "2026-10-20"
TAGS = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S)


def game(gid: int, home: str, away: str, utc: str) -> Game:
    tip = datetime.fromisoformat(utc).replace(tzinfo=timezone.utc)
    et = tip.astimezone(ZoneInfo(config.EASTERN))
    return Game(game_id=f"00226{gid:05d}", game_code="", date_et=et.date().isoformat(),
                tipoff_et=et.isoformat(), tipoff_utc=tip.isoformat(), status_text="",
                home_tricode=home, away_tricode=away)


# One game a line: (home, away, UTC tip). Madrid times in the comments.
FORTNIGHT = [
    game(1, "DET", "BOS", "2026-10-20T19:00:00"),   # 21:00 CEST, watchable
    game(2, "NYK", "PHI", "2026-10-20T23:00:00"),   # 01:00 CEST, too late
    game(3, "MIA", "ORL", "2026-10-24T19:00:00"),   # Sat 21:00 CEST, before the change
    game(4, "UTA", "LAL", "2026-10-25T19:00:00"),   # Sun 20:00 CET, after the change
    game(5, "SAS", "DAL", "2026-10-26T09:59:00"),   # 10:59 CET, too early
    game(6, "CHA", "BKN", "2026-10-31T11:00:00"),   # 12:00 CET, first watchable minute
    game(7, "IND", "MIL", "2026-10-31T22:59:00"),   # 23:59 CET, last watchable minute
    game(8, "GSW", "DEN", "2026-11-02T23:00:00"),   # 00:00 CET on the 3rd, outside
    game(9, "BOS", "NYK", "2026-11-03T19:00:00"),   # day 15, outside the fortnight
    replace(game(10, "SAC", "LAC", "2026-10-27T19:00:00"),   # no tip-off yet
            tipoff_utc="", tipoff_et=""),
]

ROSTERS = {
    "BOS": [{"player": "Hugo González", "all_star": 0}, {"player": "Someone American", "all_star": 0}],
    "MIA": [{"player": "Simone Fontecchio", "all_star": 0}],
    "ORL": [{"player": "Paolo Banchero", "all_star": 2}],
    "SAS": [{"player": "Victor Wembanyama", "all_star": 2}],
    "MIL": [{"player": "Unlisted Player", "all_star": 0}],
}
NATIONALITIES = {"Hugo González": "Spain", "Someone American": "United States",
                 "Simone Fontecchio": "Italy", "Paolo Banchero": "American / Italian",
                 "Victor Wembanyama": "France"}


def _site(tmp_path_factory, label: str, data_dir=None, today: str = TODAY) -> Path:
    out = tmp_path_factory.mktemp(label)
    (out / "data").mkdir()
    (out / "data" / "schedule.json").write_text(json.dumps({
        "season": "2026-27", "updated_at": today, "count": len(FORTNIGHT),
        "games": [asdict(g) for g in FORTNIGHT]}), encoding="utf-8")
    (out / careers.CACHE).write_text(json.dumps({
        "fetched_at": "t", "teams": ROSTERS, "nationalities": NATIONALITIES}), encoding="utf-8")
    full_build(out, today=today, offline=True, data_dir=data_dir)
    return out


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    return _site(tmp_path_factory, "country-site")


@pytest.fixture(scope="module")
def priced_site(tmp_path_factory):
    """Spain with a League Pass price filled in and nothing else changed."""
    data_dir = _copy_data(tmp_path_factory, "data-lp-priced")
    raw = json.loads((data_dir / "countries.json").read_text(encoding="utf-8"))
    raw["countries"]["spain"]["league_pass"]["monthly_price"] = 14.99
    raw["countries"]["italy"]["league_pass"].update(season_price=119.99, price_verified=True)
    (data_dir / "countries.json").write_text(json.dumps(raw), encoding="utf-8")
    return _site(tmp_path_factory, "country-site-priced", data_dir=data_dir)


def page(site: Path, slug: str) -> str:
    return (site / slug / "index.html").read_text(encoding="utf-8")


def text_of(markup: str) -> str:
    """Visible text, with the space a closing tag leaves before punctuation removed."""
    text = " ".join(html.unescape(TAGS.sub(" ", markup)).split())
    return re.sub(r" ([,.:;])", r"\1", text)


def section(markup: str, attr: str) -> str:
    start = markup.index(attr)
    return markup[start:markup.index("</section>", start)]


# -- the data file -------------------------------------------------------------------

def test_data_file_has_the_five_countries():
    data = load_countries()
    assert [c.slug for c in data.countries] == list(SLUGS)
    overrides = {c.slug: c.player_overrides for c in data.countries}
    assert overrides == {"uk": [], "spain": ["Santi Aldama", "Aday Mara", "Sergio de Larrea"],
                         "france": [], "germany": ["Hannes Steinbach"], "italy": []}
    for c in data.countries:
        assert c.league_pass["monthly_price"] is None and c.league_pass["season_price"] is None
        ZoneInfo(c.timezone)


# -- URLs, SEO and links -------------------------------------------------------------

def test_titles_canonicals_and_descriptions(site):
    descriptions = set()
    for slug in SLUGS:
        markup = page(site, slug)
        url = f"https://hoopsmatic.com/how-to-watch/{slug}"
        assert f'<link rel="canonical" href="{url}">' in markup
        assert f'<meta property="og:url" content="{url}">' in markup
        assert "github.io" not in markup
        desc = re.search(r'<meta name="description" content="([^"]+)"', markup).group(1)
        descriptions.add(desc)
    assert len(descriptions) == 5
    assert "<title>How to Watch the NBA in the UK in 2026-27 | HoopsMatic</title>" in page(site, "uk")
    assert "<title>How to Watch the NBA in Spain in 2026-27 | HoopsMatic</title>" in page(site, "spain")
    for slug, service in (("uk", "Sky Sports"), ("spain", "DAZN"), ("france", "beIN SPORTS"),
                          ("germany", "WOW"), ("italy", "Sky Sport")):
        desc = html.unescape(re.search(r'name="description" content="([^"]+)"', page(site, slug)).group(1))
        assert service in desc and "Prime Video" in desc


def test_hub_links_every_country(site):
    hub = page(site, "")
    block = hub[hub.index("data-countries"):]
    assert "Watching from outside the US?" in block
    for slug in SLUGS:
        assert f'href="/how-to-watch/{slug}"' in block


def test_each_country_links_the_hub_and_the_other_four(site):
    for slug in SLUGS:
        markup = page(site, slug)
        others = markup[markup.index("data-other-countries"):]
        assert 'href="/how-to-watch"' in others
        for other in SLUGS:
            assert (f'href="/how-to-watch/{other}"' in others) == (other != slug)


def test_sitemap_lists_countries_only_when_indexed(built_site_noindex, built_site_indexed):
    assert "<loc>" not in (built_site_noindex / "sitemap.xml").read_text(encoding="utf-8")
    xml = (built_site_indexed / "sitemap.xml").read_text(encoding="utf-8")
    for slug in SLUGS:
        assert f"<loc>https://hoopsmatic.com/how-to-watch/{slug}</loc>" in xml


def test_no_new_outside_request(site):
    """Same stylesheet, fonts and script as every other page; no times for the
    script to rewrite and nothing that makes it fetch availability."""
    def loads(markup):
        return sorted(re.findall(r'<(?:script|link)[^>]+(?:src|href)="([^"]+)"', markup))
    hub = [u for u in loads(page(site, "")) if "canonical" not in u]
    for slug in SLUGS:
        markup = page(site, slug)
        assert set(loads(markup)) - {f"https://hoopsmatic.com/how-to-watch/{slug}"} <= set(hub)
        assert "data-utc" not in markup and "data-player" not in markup and "data-updated" not in markup


@pytest.mark.parametrize("slug", SLUGS)
def test_copy_rules(site, slug):
    body = text_of(page(site, slug))
    assert "—" not in body and "–" not in body


# -- 1. the answer -------------------------------------------------------------------

def test_answer_names_partner_and_prime_with_local_prices(site):
    body = text_of(section(page(site, "spain"), "data-country-answer"))
    assert body.startswith("data-country-answer> Where to watch In Spain, NBA games are on DAZN and Prime Video")
    assert "Commentary: Spanish" in body
    assert "DAZN Plan Baloncesto" in body and "€9.99 a month" in body
    uk = text_of(section(page(site, "uk"), "data-country-answer"))
    assert "£34.99 a month" in uk and "£14.99 a day" in uk


def test_unverified_price_carries_the_check_line(site):
    uk = section(page(site, "uk"), "data-country-answer")
    row = uk[uk.index("Sky TV with Sky Sports"):]
    row = row[:row.index("data-country-option") if "data-country-option" in row else len(row)]
    assert "£35 a month" in text_of(row)
    assert "Check the current price before you buy." in text_of(row)
    verified = uk[uk.index("NOW Sports Membership"):uk.index("NOW Sports Day Membership")]
    assert "Check the current price" not in verified


def test_null_price_reads_not_confirmed(site):
    uk = section(page(site, "uk"), "data-country-answer")
    membership = text_of(uk[uk.index("Amazon Prime membership"):])
    assert "Price not confirmed" in membership
    assert "£" not in membership


def test_moderate_country_gets_one_check_note(site):
    for slug in SLUGS:
        markup = page(site, slug)
        assert markup.count("data-confidence-note") == 1
        assert "check before you buy" in text_of(section(markup, "data-country-answer"))


def test_low_confidence_prices_read_not_confirmed(tmp_path_factory):
    data_dir = _copy_data(tmp_path_factory, "data-low")
    raw = json.loads((data_dir / "countries.json").read_text(encoding="utf-8"))
    raw["countries"]["germany"]["confidence"] = "low"
    (data_dir / "countries.json").write_text(json.dumps(raw), encoding="utf-8")
    out = _site(tmp_path_factory, "country-site-low", data_dir=data_dir)
    body = text_of(section(page(out, "germany"), "data-country-answer"))
    assert "Details for Germany in 2026-27 are not confirmed yet." in body
    assert "€" not in body and "Price not confirmed" in body


# -- 2. League Pass ------------------------------------------------------------------

def test_league_pass_null_price(site):
    block = section(page(site, "spain"), "data-league-pass")
    body = text_of(block)
    assert "Every game live, no blackouts in Spain." in body
    assert "2026-27 prices not published yet" in body
    assert "https://support.watch.nba.com/hc/en-us/articles/115002481154-League-Pass-Blackouts" in block
    assert "Every game live, no blackouts in the UK." in text_of(page(site, "uk"))


def test_league_pass_filled_price_renders_with_no_code_change(priced_site):
    spain = text_of(section(page(priced_site, "spain"), "data-league-pass"))
    assert "€14.99 a month" in spain
    assert "not published yet" not in spain
    assert "Check the current price before you buy." in spain       # price_verified still false
    italy = text_of(section(page(priced_site, "italy"), "data-league-pass"))
    assert "€119.99 a season" in italy and "Check the current price" not in italy
    france = text_of(section(page(priced_site, "france"), "data-league-pass"))
    assert "2026-27 prices not published yet" in france


# -- 3. players ----------------------------------------------------------------------

def test_nationality_matching():
    assert nationality_matches("Spain", ["Spain", "Spanish"])
    assert nationality_matches("American / Italian", ["Italy", "Italian"])
    assert nationality_matches("Great Britain", ["United Kingdom", "Great Britain"])
    assert not nationality_matches("United States", ["Spain", "Spanish"])
    assert not nationality_matches("", ["Spain"])


def test_overrides_add_players_without_a_nationality():
    spain = next(c for c in load_countries().countries if c.slug == "spain")
    assert [p["player"] for p in country_players(spain, ROSTERS, NATIONALITIES)] == ["Hugo González"]
    spain.player_overrides = ["Unlisted player"]
    found = country_players(spain, ROSTERS, NATIONALITIES)
    assert {(p["player"], p["tricode"]) for p in found} == {("Hugo González", "BOS"),
                                                            ("Unlisted Player", "MIL")}


def test_file_overrides_are_listed_with_team_and_next_game(tmp_path_factory):
    """The shipped overrides, placed on the teams the career map has them on."""
    rosters = {**ROSTERS, "DAL": [{"player": "Santi Aldama", "all_star": 0},
                                  {"player": "Sergio de Larrea", "all_star": 0}],
               "OKC": [{"player": "Aday Mara", "all_star": 0}],
               "CHA": [{"player": "Hannes Steinbach", "all_star": 0}]}
    out = tmp_path_factory.mktemp("country-site-overrides")
    (out / "data").mkdir()
    (out / "data" / "schedule.json").write_text(json.dumps({
        "season": "2026-27", "updated_at": TODAY, "count": len(FORTNIGHT),
        "games": [asdict(g) for g in FORTNIGHT]}), encoding="utf-8")
    (out / careers.CACHE).write_text(json.dumps({
        "fetched_at": "t", "teams": rosters, "nationalities": NATIONALITIES}), encoding="utf-8")
    notes = full_build(out, today=TODAY, offline=True).notes
    assert "overrides not on an NBA roster" not in " ".join(notes)
    spain = text_of(section(page(out, "spain"), "data-country-players"))
    for line in ("Aday Mara, Oklahoma City Thunder. Next game: No game scheduled",
                 "Santi Aldama, Dallas Mavericks. Next game: Mon Oct 26, 10:59 CET, at San Antonio Spurs",
                 "Sergio de Larrea, Dallas Mavericks. Next game: Mon Oct 26, 10:59 CET, at San Antonio Spurs",
                 "Hugo González, Boston Celtics."):
        assert line in spain
    germany = text_of(section(page(out, "germany"), "data-country-players"))
    assert "Hannes Steinbach, Charlotte Hornets. Next game: Sat Oct 31, 12:00 CET, vs Brooklyn Nets" in germany


def test_an_override_nobody_matches_is_logged(tmp_path_factory):
    out = _site(tmp_path_factory, "country-site-unplaced")     # rosters without the override players
    notes = full_build(out, today=TODAY, offline=True).notes
    assert any("overrides not on an NBA roster: spain: Santi Aldama, spain: Aday Mara, "
               "spain: Sergio de Larrea, germany: Hannes Steinbach" in n for n in notes)


def test_players_block_has_team_and_local_next_game(site):
    body = text_of(section(page(site, "spain"), "data-country-players"))
    assert body == ("data-country-players> Players from Spain Hugo González, Boston Celtics. "
                    "Next game: Tue Oct 20, 21:00 CEST, at Detroit Pistons")
    italy = text_of(section(page(site, "italy"), "data-country-players"))
    assert italy.index("Paolo Banchero") < italy.index("Simone Fontecchio")   # same game, so by name
    assert "Paolo Banchero, Orlando Magic. Next game: Sat Oct 24, 21:00 CEST, at Miami Heat" in italy


def test_country_with_no_players_omits_the_block(site):
    for slug in ("uk", "germany"):
        markup = page(site, slug)
        assert "data-country-players" not in markup
        assert "Players from" not in markup


# -- 4. watchable hours and the clock change -----------------------------------------

def test_clock_change_week():
    madrid, london, eastern = ZoneInfo("Europe/Madrid"), ZoneInfo("Europe/London"), ZoneInfo(config.EASTERN)
    before, after = FORTNIGHT[2], FORTNIGHT[3]          # same 19:00 UTC, either side of the change
    assert clock(local_tip(before, madrid)) == "21:00 CEST"
    assert clock(local_tip(after, madrid)) == "20:00 CET"
    assert clock(local_tip(before, london)) == "20:00 BST"
    assert clock(local_tip(after, london)) == "19:00 GMT"
    # The US has not changed yet, so the Eastern time stays put and the gap shrinks to five hours.
    assert local_tip(before, eastern).hour == local_tip(after, eastern).hour == 15
    nov = game(99, "BOS", "NYK", "2026-11-01T20:00:00")
    assert local_tip(nov, eastern).hour == 15 and clock(local_tip(nov, madrid)) == "21:00 CET"


def test_watchable_window_edges():
    rows = watchable_games(FORTNIGHT, ZoneInfo("Europe/Madrid"), TODAY)
    assert [g.game_id[-2:] for g, _ in rows] == ["01", "03", "04", "06", "07"]
    assert [clock(t) for _, t in rows] == ["21:00 CEST", "21:00 CEST", "20:00 CET", "12:00 CET", "23:59 CET"]


def test_watchable_block_on_the_page(site):
    body = text_of(section(page(site, "spain"), "data-watchable"))
    assert "Every game is on League Pass. DAZN and Prime Video carry a selection." in body
    assert re.findall(r"(\w{3} \w{3} \d+) ([A-Za-z. ]+ at [A-Za-z0-9. ]+?) (\d\d:\d\d \w+)", body) == [
        ("Tue Oct 20", "Boston Celtics at Detroit Pistons", "21:00 CEST"),
        ("Sat Oct 24", "Orlando Magic at Miami Heat", "21:00 CEST"),
        ("Sun Oct 25", "Los Angeles Lakers at Utah Jazz", "20:00 CET"),
        ("Sat Oct 31", "Brooklyn Nets at Charlotte Hornets", "12:00 CET"),
        ("Sat Oct 31", "Milwaukee Bucks at Indiana Pacers", "23:59 CET"),
    ]
    uk = text_of(section(page(site, "uk"), "data-watchable"))
    assert "Sky Sports and Prime Video carry a selection." in uk
    assert "Tue Oct 20 Boston Celtics at Detroit Pistons 20:00 BST" in uk
    assert "Sun Oct 25 Los Angeles Lakers at Utah Jazz 19:00 GMT" in uk
    assert "Oct 26" not in uk


def test_empty_watchable_block(tmp_path_factory):
    out = _site(tmp_path_factory, "country-site-late", today="2026-12-01")
    body = text_of(section(page(out, "spain"), "data-watchable"))
    assert "No games in the next 14 days tip off between 12:00 and 23:59 local time." in body


# -- 5. games in Europe --------------------------------------------------------------

def test_europe_games_on_every_page(site):
    for slug in SLUGS:
        body = text_of(section(page(site, slug), "data-europe-games"))
        assert "Thu Jan 14, 2027: San Antonio Spurs vs. New Orleans Pelicans, Accor Arena, Paris. On Prime Video." in body
        assert "Reported for about 8pm CET; not officially confirmed" in body
        assert "Sun Jan 17, 2027: San Antonio Spurs vs. New Orleans Pelicans, Co-op Live, Manchester." in body
        assert "Reported for about 3:30pm GMT; not officially confirmed" in body


# -- 6. checked and sources ----------------------------------------------------------

def test_checked_and_sources(site):
    markup = page(site, "france")
    assert "Checked September 2026" in text_of(markup)
    sources = markup[markup.index('<details class="sources small">'):]
    sources = sources[:sources.index("</details>")]
    for url in ("https://sabonner.beinsports.com/faq",
                "https://www.sportcal.com/media/bein-renews-long-running-nba-broadcast-agreement-in-france/",
                "https://www.nba.com/news/spurs-pelicans-nba-paris-nba-manchester-2027"):
        assert url in sources


# -- builds --------------------------------------------------------------------------

def test_refresh_leaves_country_pages_alone(tmp_path_factory, site):
    before = {slug: (site / slug / "index.html").stat().st_mtime_ns for slug in SLUGS}
    refresh_build(site, today=TODAY)
    assert {slug: (site / slug / "index.html").stat().st_mtime_ns for slug in SLUGS} == before


def test_nationalities_ride_along_in_the_roster_copy():
    records = [{"player": "A One", "status": "nba_active", "nationality": "France",
                "career_history": [{"years": "2020–present", "team": "Miami Heat"}]},
               {"player": "B Two", "status": "nba_active", "nationality": None,
                "career_history": [{"years": "2020–present", "team": "Miami Heat"}]}]
    built = careers.rosters_from(records, {"Miami Heat": "MIA"})
    assert built["nationalities"] == {"A One": "France"}


def test_price_text():
    assert price_text(34.99, "GBP", "month") == "£34.99 a month"
    assert price_text(15.00, "EUR", "month") == "€15 a month"
    assert price_text(None, "EUR", "month") == ""


def test_players_sorted_by_next_game_then_name(tmp_path_factory):
    """Soonest game first whatever the All-Star count, teammates by name,
    a game with no time after the timed ones, no game at all last."""
    rosters = {
        "SAS": [{"player": "Victor Wembanyama", "all_star": 5}],           # Mon Oct 26
        "BKN": [{"player": "Zed Early", "all_star": 0}],                    # Sat Oct 31 12:00
        "MIL": [{"player": "Bob Later", "all_star": 0}],                    # Sat Oct 31 23:59
        "BOS": [{"player": "Yann Soonest", "all_star": 0},                  # Tue Oct 20
                {"player": "Adam Soonest", "all_star": 0}],
        "LAC": [{"player": "Tim Untimed", "all_star": 0}],                  # Tue Oct 27, no time
        "PHX": [{"player": "Al Idle", "all_star": 0}],                      # no game
    }
    nationalities = {name: "France" for players in rosters.values() for name in
                     (p["player"] for p in players)}
    out = tmp_path_factory.mktemp("country-site-sort")
    (out / "data").mkdir()
    (out / "data" / "schedule.json").write_text(json.dumps({
        "season": "2026-27", "updated_at": TODAY, "count": len(FORTNIGHT),
        "games": [asdict(g) for g in FORTNIGHT]}), encoding="utf-8")
    (out / careers.CACHE).write_text(json.dumps({
        "fetched_at": "t", "teams": rosters, "nationalities": nationalities}), encoding="utf-8")
    full_build(out, today=TODAY, offline=True)
    block = section(page(out, "france"), "data-country-players")
    names = re.findall(r"<strong>([^<]+)</strong>", block)
    assert names == ["Adam Soonest", "Yann Soonest", "Victor Wembanyama", "Tim Untimed",
                     "Zed Early", "Bob Later", "Al Idle"]
    assert "Tim Untimed, LA Clippers. Next game: Tue Oct 27, time TBA" in text_of(block)
    assert "Al Idle, Phoenix Suns. Next game: No game scheduled" in text_of(block)
