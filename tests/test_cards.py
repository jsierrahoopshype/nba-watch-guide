"""Every card on the hub is one full tap target: game cards through a
stretched link to their game on the tonight page (team links inside stay
their own), team and country cards as a single link."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from conftest import TODAY, _build
from watchguide import config


class Cards(HTMLParser):
    """Collects every link inside each card: hub game cards (li.hg-row) and
    team and country cards (li > a.tcard), with the classes of each link."""

    def __init__(self):
        super().__init__()
        self.cards: list[dict] = []
        self._stack: list[tuple[str, dict | None]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        card = None
        if tag == "li" and "hg-row" in classes:
            card = {"kind": "game", "id": a.get("data-game"), "links": []}
        elif tag == "li" and self._stack and self._stack[-1][0] == "ul" and \
                any(c in (self._ul_classes or []) for c in ("tcards", "ccards")):
            card = {"kind": "tcards" if "tcards" in self._ul_classes else "ccards", "links": []}
        if tag == "ul":
            self._ul_classes = classes
        if card:
            self.cards.append(card)
        if tag == "a":
            current = next((c for _, c in reversed(self._stack) if c), None)
            if current is not None:
                current["links"].append({"href": a.get("href", ""), "classes": classes})
        if tag not in ("img", "br", "meta", "link", "input", "hr", "source"):
            self._stack.append((tag, card))

    _ul_classes: list[str] | None = None

    def handle_endtag(self, tag):
        while self._stack:
            name, _ = self._stack.pop()
            if name == tag:
                break


def cards_of(page: Path) -> list[dict]:
    parser = Cards()
    parser.feed(page.read_text(encoding="utf-8"))
    return parser.cards


def ids_on(page: Path) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', page.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def off_day_site(tmp_path_factory, fixture_games):
    return _build(tmp_path_factory, [g for g in fixture_games if g.date_et != TODAY], "cards-off-day")


@pytest.mark.parametrize("which", ["game_day", "off_day"])
def test_every_game_card_has_one_primary_link_to_an_anchor_that_exists(which, built_site, off_day_site):
    site = built_site if which == "game_day" else off_day_site
    games = [c for c in cards_of(site / "index.html") if c["kind"] == "game"]
    assert games
    tonight_ids = ids_on(site / "tonight" / "index.html")
    for card in games:
        primary = [l for l in card["links"] if "card-link" in l["classes"]]
        assert len(primary) == 1, card
        assert primary[0]["href"] == f"/how-to-watch/tonight#game-{card['id']}"
        assert f"game-{card['id']}" in tonight_ids, f"no #game-{card['id']} on the tonight page"


def test_game_card_team_links_stay_separate_and_work(built_site, teams):
    paths = {t.path for t in teams}
    for card in (c for c in cards_of(built_site / "index.html") if c["kind"] == "game"):
        team_links = [l for l in card["links"] if "hg-team-link" in l["classes"]]
        assert len(team_links) == 2, card
        assert len(card["links"]) == 3                  # the primary link plus the two teams
        for link in team_links:
            assert link["href"] in paths
            assert (built_site / link["href"][len("/how-to-watch/"):] / "index.html").is_file()


@pytest.mark.parametrize("kind, count", [("tcards", 30), ("ccards", 5)])
def test_team_and_country_cards_are_one_link_each(built_site, kind, count):
    cards = [c for c in cards_of(built_site / "index.html") if c["kind"] == kind]
    assert len(cards) == count
    for card in cards:
        assert len(card["links"]) == 1 and "tcard" in card["links"][0]["classes"], card
        target = built_site / card["links"][0]["href"][len("/how-to-watch/"):] / "index.html"
        assert target.is_file(), card


def test_card_link_accessible_name_describes_the_game(built_site):
    hub = (built_site / "index.html").read_text(encoding="utf-8")
    link = re.search(r'<a class="card-link"[^>]*>.*?</a>', hub, re.S).group(0)
    assert re.search(r'<span class="sr-only">: [^<]+ at [^<]+, channels and player availability</span>', link)


def test_styles_stretch_the_link_keep_team_links_on_top_and_show_focus():
    css = (config.ASSET_DIR / "watch-guide.css").read_text(encoding="utf-8")
    assert re.search(r"\.hg-row \{ position: relative;", css)
    assert re.search(r'\.card-link::after \{ content: ""; position: absolute; inset: 0;[^}]*z-index: 1;', css)
    assert re.search(r"\.hg-team-link, \.hg-out \{ position: relative; z-index: 2; \}", css)
    assert ".card-link:focus-visible::after { outline: 3px solid" in css
    assert "a:focus-visible, summary:focus-visible, button:focus-visible { outline: 3px solid" in css
    assert re.search(r"\.hg-team-link \{[^}]*min-height: var\(--tap\)", css)
    assert re.search(r"\.game:target \{", css) and "prefers-reduced-motion" in css
