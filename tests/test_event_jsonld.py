"""Event structured data: one SportsEvent per dated game a page lists, each
with a full start time, an arena and its street address, or none at all.

Google Search Console flagged the old markup: Events without startDate or
location (the nested BroadcastEvents) and Places without an address."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from types import SimpleNamespace

from conftest import TODAY, fixture_schedule

from watchguide import config, seo
from watchguide.model import load_arenas, load_teams
from watchguide.pairs import SEPARATOR

BLOCK = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
ARENAS = json.loads((config.DATA_DIR / "arenas.json").read_text(encoding="utf-8"))["arenas"]


def _jsonld(path) -> dict:
    return json.loads(BLOCK.findall(path.read_text(encoding="utf-8"))[0])


def _typed(node, out=None) -> list[dict]:
    """Every node with an @type, nested ones included."""
    out = [] if out is None else out
    if isinstance(node, dict):
        if "@type" in node:
            out.append(node)
        for value in node.values():
            _typed(value, out)
    elif isinstance(node, list):
        for value in node:
            _typed(value, out)
    return out


def _events(path) -> list[dict]:
    return [n for n in _typed(_jsonld(path)) if str(n["@type"]).endswith("Event")]


def _kind(built_site, page) -> str:
    rel = page.parent.relative_to(built_site).as_posix()
    team_slugs = {t.slug for t in load_teams()}
    if rel == "tonight":
        return "tonight"
    if rel in team_slugs:
        return "team"
    if SEPARATOR in rel:
        return "pair"
    return "other"


def _start(event) -> datetime:
    start = datetime.fromisoformat(event["startDate"])
    assert start.utcoffset() is not None, f"startDate without an offset: {event['startDate']}"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d", event["startDate"]), event["startDate"]
    return start


def test_every_event_is_complete(built_site):
    """Every Event anywhere in the JSON-LD, nested ones included, has a full
    start time with its offset, an arena and a street address."""
    total = 0
    for page in sorted(built_site.rglob("index.html")):
        for event in _events(page):
            total += 1
            where = f"{page}: {event.get('name')}"
            assert event["@type"] == "SportsEvent", where
            start = _start(event)
            assert datetime.fromisoformat(event["endDate"]) - start == timedelta(hours=2, minutes=30), where
            location = event["location"]
            assert location["@type"] == "Place" and location["name"], where
            address = location["address"]
            assert address["@type"] == "PostalAddress", where
            for key in ("streetAddress", "addressLocality", "postalCode", "addressCountry"):
                assert address.get(key), f"{where} has no {key}"
            assert event["eventStatus"] == "https://schema.org/EventScheduled", where
            assert event["organizer"] == {"@type": "Organization", "name": "NBA", "url": "https://www.nba.com"}
            assert {t["name"] for t in event["performer"]} == {event["homeTeam"]["name"], event["awayTeam"]["name"]}
            assert event["name"] == f"{event['awayTeam']['name']} at {event['homeTeam']['name']}", where
            assert event["description"].startswith(event["name"] + " on ") and location["name"] in event["description"]
            assert event["url"].startswith(config.SITE_BASE + "/"), where
            assert "offers" not in event and "subEvent" not in event, where
    assert total > 0, "the fixture site should carry Events"


def test_events_only_for_the_dated_games_a_page_lists(built_site):
    """Team and pair pages: one Event per upcoming game, at most ten, each
    matching a real fixture game by its own tipoff. Tonight: one per card.
    Every other page (hub, countries) lists no single dated game: no Event."""
    games = fixture_schedule()
    by_slug = {t.slug: t for t in load_teams()}
    verified = load_arenas()
    tipoffs = {(g.tipoff_et, g.home_tricode, g.away_tricode) for g in games}
    seen = {"tonight": 0, "team": 0, "pair": 0}
    for page in sorted(built_site.rglob("index.html")):
        kind = _kind(built_site, page)
        events = _events(page)
        if kind == "other":
            assert events == [], f"{page} lists no dated game and must carry no Event"
            continue
        rel = page.parent.relative_to(built_site).as_posix()
        if kind == "team":
            tricode = by_slug[rel].tricode
            listed = [g for g in games if g.involves(tricode) and g.date_et >= TODAY]
        elif kind == "pair":
            first, second = (by_slug[s] for s in rel.split(SEPARATOR))
            listed = [g for g in games if {g.home_tricode, g.away_tricode} == {first.tricode, second.tricode}
                      and g.date_et >= TODAY]
        else:
            listed = [g for g in games if g.date_et == TODAY]
        expected = [g for g in listed if g.arena in verified]
        if kind != "tonight":
            expected = [g for g in listed[:10] if g.arena in verified]
        assert len(events) == len(expected), f"{page}: {len(events)} Events for {len(expected)} games"
        for event in events:
            start = _start(event)
            assert start.date().isoformat() >= TODAY, f"{page} marks up a past game"
            home = next(t.tricode for t in by_slug.values() if t.full_name == event["homeTeam"]["name"])
            away = next(t.tricode for t in by_slug.values() if t.full_name == event["awayTeam"]["name"])
            assert (event["startDate"], home, away) in tipoffs, f"{page}: no such game {event['name']}"
        seen[kind] += len(events)
    assert all(seen.values()), seen


def test_no_event_at_an_arena_without_a_verified_address(built_site):
    """Scotiabank Arena's postal code is in dispute, so Raptors home games
    carry no Event; their road games still do."""
    assert ARENAS["Scotiabank Arena"]["verified"] is False
    events = _events(built_site / "toronto-raptors" / "index.html")
    assert events, "Raptors road games should still carry Events"
    assert all(e["location"]["name"] != "Scotiabank Arena" for e in events)
    assert all(e["homeTeam"]["name"] != "Toronto Raptors" for e in events)


def test_two_pages_parse_to_the_expected_markup(built_site):
    """Parse the JSON-LD of a team page and the tonight page end to end."""
    data = _jsonld(built_site / "miami-heat" / "index.html")
    graph = data["@graph"]
    assert data["@context"] == "https://schema.org"
    assert graph[0]["@type"] == "BreadcrumbList"
    heat = [n for n in graph if n["@type"] == "SportsEvent"]
    assert heat and all("Miami Heat" in (e["homeTeam"]["name"], e["awayTeam"]["name"]) for e in heat)
    home = next(e for e in heat if e["homeTeam"]["name"] == "Miami Heat")
    assert home["location"]["name"] == "Kaseya Center"
    assert home["location"]["address"] == {
        "@type": "PostalAddress", "streetAddress": "601 Biscayne Boulevard", "addressLocality": "Miami",
        "addressRegion": "FL", "postalCode": "33132", "addressCountry": "US"}
    assert home["url"] == "https://hoopsmatic.com/how-to-watch/miami-heat"

    tonight = _jsonld(built_site / "tonight" / "index.html")["@graph"]
    events = [n for n in tonight if n["@type"] == "SportsEvent"]
    assert events and all(_start(e).date().isoformat() == TODAY for e in events)
    assert all(e["url"] == "https://hoopsmatic.com/how-to-watch/tonight" for e in events)


def test_no_jsonld_url_leaves_hoopsmatic(built_site):
    for page in sorted(built_site.rglob("index.html")):
        text = BLOCK.findall(page.read_text(encoding="utf-8"))[0]
        assert "github.io" not in text, page
        for url in re.findall(r'"(?:url|item|@id)":"([^"]+)"', text):
            assert url.startswith("https://hoopsmatic.com") or url == "https://www.nba.com", (page, url)


# -- seo.sports_event on its own -------------------------------------------

ADDRESS = {"streetAddress": "1 Test Way", "addressLocality": "Testville", "addressRegion": "TX",
           "postalCode": "00000", "addressCountry": "US"}


def _game(**over):
    base = dict(tipoff_et="2026-11-07T17:00:00-05:00", status_text="5:00 pm ET",
                arena="Arena CDMX", home_tricode="IND", away_tricode="DEN")
    base.update(over)
    return SimpleNamespace(**base)


def _event(game, address=ADDRESS):
    return seo.sports_event(game, "Indiana Pacers", "Denver Nuggets", config.public_url("indiana-pacers"), address)


def test_event_fields_from_one_game():
    event = _event(_game())
    assert event["startDate"] == "2026-11-07T17:00:00-05:00"
    assert event["endDate"] == "2026-11-07T19:30:00-05:00"
    assert event["description"] == "Denver Nuggets at Indiana Pacers on November 7, 2026, at Arena CDMX."
    assert event["location"]["address"] == {"@type": "PostalAddress", **ADDRESS}


def test_no_event_without_a_real_dated_game():
    assert _event(_game(tipoff_et="")) is None                                   # no tipoff
    assert _event(_game(tipoff_et="2026-11-07T17:00:00")) is None                # no offset
    assert _event(_game(tipoff_et="2026-12-04T00:00:00-05:00", status_text="TBD")) is None  # Cup placeholder
    assert _event(_game(home_tricode="", away_tricode="")) is None               # teams not known yet
    assert _event(_game(), address=None) is None                                 # address not verified
    assert _event(_game(arena="")) is None


# -- data/arenas.json --------------------------------------------------------

def test_arenas_file_covers_every_team_and_records_its_sources():
    tricodes = {t.tricode for t in load_teams()}
    homes = [e["home"] for e in ARENAS.values() if e["kind"] == "home"]
    assert sorted(homes) == sorted(tricodes), "one regular arena per team"
    for name, entry in ARENAS.items():
        assert entry["kind"] in {"home", "alternate", "neutral"}, name
        assert entry["home"] in tricodes, name
        assert len(entry["sources"]) >= 2 and all(u.startswith("https://") for u in entry["sources"]), name
        if entry["verified"]:
            address = entry["address"]
            for key in ("streetAddress", "addressLocality", "postalCode", "addressCountry"):
                assert address.get(key), f"{name} is verified without {key}"
            if address["addressCountry"] in {"US", "CA"}:
                assert re.fullmatch(r"[A-Z]{2}", address.get("addressRegion", "")), name
    verified = load_arenas()
    assert set(verified) == {n for n, e in ARENAS.items() if e["verified"]}
