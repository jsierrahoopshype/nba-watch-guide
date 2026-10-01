"""Share images: every page names its own 1200x630 PNG on hoopsmatic.com,
the file is in the build, the Event markup reuses it, and a card is drawn
again only when what it shows changes."""

from __future__ import annotations

import json
import re
import struct
from itertools import permutations

import pytest

from conftest import TODAY, fixture_schedule
from watchguide import config, share
from watchguide.model import load_teams
from watchguide.pairs import SEPARATOR

OG = {k: re.compile(rf'<meta property="og:image{k}" content="([^"]*)">')
      for k in ("", ":width", ":height", ":alt")}
CARD = re.compile(r'<meta name="twitter:card" content="([^"]*)">')
BLOCK = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def test_every_page_has_a_share_image(built_site):
    pages = sorted(built_site.rglob("index.html"))
    assert pages
    for page in pages:
        html = page.read_text(encoding="utf-8")
        found = {k: rx.findall(html) for k, rx in OG.items()}
        assert all(len(v) == 1 for v in found.values()), (page, found)
        url = found[""][0]
        assert url.startswith(config.SITE_BASE + "/share/") and url.endswith(".png"), url
        assert (found[":width"][0], found[":height"][0]) == ("1200", "630"), page
        assert found[":alt"][0].strip(), page
        assert CARD.findall(html) == ["summary_large_image"], page
        image = built_site / url[len(config.SITE_BASE) + 1:]
        assert image.is_file(), image
        assert _png_size(image.read_bytes()) == (1200, 630), image


def test_events_carry_the_pages_og_image(built_site):
    seen = 0
    for page in sorted(built_site.rglob("index.html")):
        html = page.read_text(encoding="utf-8")
        og = OG[""].findall(html)[0]
        data = json.loads(BLOCK.findall(html)[0])
        for node in data.get("@graph") or [data]:
            if node.get("@type") == "SportsEvent":
                assert node["image"] == [og], page
                seen += 1
    assert seen


def test_pair_card_follows_the_page_title_and_names_the_next_meeting(built_site):
    """The card's team order is the title's; its line is the next meeting's
    date, time and channels, as the page's next-game block shows them."""
    checked = 0
    for page in sorted(built_site.glob(f"*{SEPARATOR}*/index.html")):
        html = page.read_text(encoding="utf-8")
        a, b = re.search(r"<title>(.+?) vs\. (.+?):", html).groups()
        alt = OG[":alt"].findall(html)[0]
        assert alt.startswith(f"{a} vs. {b}. "), (page, alt)
        if "Next meeting: " in alt:
            date, time = alt.split("Next meeting: ")[1].split(" · ")[:2]
            assert re.fullmatch(r"[A-Z][a-z]{2} [A-Z][a-z]{2} \d{1,2}", date), alt
            assert time.endswith(" ET"), alt
        checked += 1
    assert checked


def test_team_card_names_the_next_game(built_site):
    games = fixture_schedule()
    for team in load_teams():
        upcoming = [g for g in games if g.involves(team.tricode) and g.date_et >= TODAY]
        alt = OG[":alt"].findall((built_site / team.slug / "index.html").read_text(encoding="utf-8"))[0]
        assert alt.startswith(f"How to watch the {team.full_name}. "), alt
        nxt = upcoming[0]
        where = "vs" if nxt.is_home_for(team.tricode) else "at"
        opponent = next(t for t in load_teams() if t.tricode == nxt.opponent_of(team.tricode))
        assert f"Next game · {where} {opponent.short_name}: " in alt, alt


def test_alternatives_join_with_or_and_long_lines_are_shortened():
    assert share.join_or(["ABC"]) == "ABC"
    assert share.join_or(["ABC", "ESPN"]) == "ABC or ESPN"
    assert share.join_or(["ABC", "ESPN", "NBA TV"]) == "ABC, ESPN or NBA TV"
    # Chip labels (short names), as the cards use: some channels dropped.
    chips = share.game_line("Fri Dec 25", "8:00 pm ET", ["NBCS Philly on Peacock", "NBCS Bay Area on Peacock",
                                                         "Monumental+", "Peacock"])
    size, line = share.fit_line(chips, 674)          # a team card's line width
    assert line.endswith(" more") and share.text_width(line, size, 600) <= 674, line
    # Nothing fits even one channel name: the channels are only counted.
    long = share.game_line("Fri Dec 25", "8:00 pm ET", ["NBC Sports Philadelphia on Peacock " * 2, "ESPN"])
    assert share.fit_line(long, 674)[1] == "Fri Dec 25 · 8:00 pm ET · 2 channels"


def test_every_real_card_fits_and_the_font_has_every_letter():
    """Every team, every ordered pair and every country: the text wraps
    inside the card and Poppins covers it (share.svg raises otherwise)."""
    teams = load_teams()
    line = share.game_line("Wed Oct 21", "10:30 pm ET", ["NBCSBA", "Peacock"])
    for team in teams:
        share.svg(share.Card(team.slug, f"How to watch the {team.full_name}", "Next game · vs Trail Blazers",
                             line, images=(f"logos/{team.tricode.lower()}.svg",), kind="team"))
    for a, b in permutations(teams, 2):
        share.svg(share.Card("x", f"{a.short_name} vs. {b.short_name}", "Next meeting", line,
                             images=(f"logos/{a.tricode.lower()}.svg", f"logos/{b.tricode.lower()}.svg"),
                             names=(a.short_name, b.short_name), kind="pair"))
    copy = json.loads((config.DATA_DIR / "copy.json").read_text(encoding="utf-8"))
    raw = json.loads((config.DATA_DIR / "countries.json").read_text(encoding="utf-8"))
    for slug, country in raw["countries"].items():
        place = copy["country"].get("places", {}).get(slug, country["name"])
        flag = country.get("flag")
        share.svg(share.Card(slug, f"How to watch the NBA in {place}", "2026-27 season", "TV and streaming",
                             images=(f"flags/{flag}.svg",) if flag else (), kind="flag" if flag else "plain"))
    with pytest.raises(ValueError):
        share.text_width("Ωmega", 40)


def test_a_card_is_drawn_again_only_when_its_inputs_change(tmp_path):
    a = share.Card("a", "How to watch the NBA", "2026-27 season", "TV and streaming for all 30 teams")
    b = share.Card("b", "How to watch tonight's NBA games", "Tonight", "Every game ranked")
    assert share.write_images(tmp_path, [a, b], full=True).startswith("share images: 2 drawn, 0 unchanged")
    first = (tmp_path / a.path).read_bytes()
    assert share.write_images(tmp_path, [a, b], full=True).startswith("share images: 0 drawn, 2 unchanged")
    assert (tmp_path / a.path).read_bytes() == first

    # A team card's next-game line changes after each game: it is drawn again.
    changed = share.Card("a", "How to watch the NBA", "2027-28 season", "TV and streaming for all 30 teams")
    assert share.write_images(tmp_path, [changed], full=False).startswith("share images: 1 drawn, 0 unchanged")
    assert (tmp_path / b.path).is_file()          # the refresh leaves other cards alone

    note = share.write_images(tmp_path, [changed], full=True)
    assert note.endswith("1 removed") and not (tmp_path / b.path).exists()
    state = json.loads((tmp_path / share.STATE_FILE).read_text(encoding="utf-8"))
    assert set(state) == {changed.path}


def test_cards_use_only_local_files():
    """Logos and flags are embedded from assets/, so the SVG names no URL."""
    team = load_teams()[0]
    markup = share.svg(share.Card(team.slug, "How to watch", "2026-27 season", "TV",
                                  images=(f"logos/{team.tricode.lower()}.svg",), kind="team"))
    hrefs = re.findall(r'href="([^"]+)"', markup)
    assert hrefs and all(h.startswith("data:image/svg+xml;base64,") for h in hrefs)
