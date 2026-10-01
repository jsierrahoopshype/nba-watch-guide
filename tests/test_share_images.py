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


def test_pair_card_names_the_next_games_away_and_home_teams(built_site):
    games = fixture_schedule()
    by_slug = {t.slug: t for t in load_teams()}
    checked = 0
    for page in sorted(built_site.glob(f"*{SEPARATOR}*/index.html")):
        slug = page.parent.name
        first, second = (by_slug[s].tricode for s in slug.split(SEPARATOR))
        meetings = [g for g in games if {g.home_tricode, g.away_tricode} == {first, second}]
        shown = next((g for g in meetings if g.date_et >= TODAY), meetings[-1])
        away = next(t for t in by_slug.values() if t.tricode == shown.away_tricode)
        home = next(t for t in by_slug.values() if t.tricode == shown.home_tricode)
        alt = OG[":alt"].findall(page.read_text(encoding="utf-8"))[0]
        assert alt.startswith(f"{away.short_name} vs. {home.short_name}: how to watch"), (slug, alt)
        checked += 1
    assert checked


def test_every_real_card_fits_and_the_font_has_every_letter():
    """Every team, every ordered pair and every country: the text wraps
    inside the card and DM Sans covers it (share.svg raises otherwise)."""
    teams = load_teams()
    for team in teams:
        share.svg(share.Card(team.slug, f"How to watch the {team.full_name}", "2026-27 · HoopsMatic",
                             images=(f"logos/{team.tricode.lower()}.svg",), accents=("#000000",), kind="team"))
    for away, home in permutations(teams, 2):
        share.svg(share.Card("x", f"{away.short_name} vs. {home.short_name}: how to watch",
                             "2026-27 · HoopsMatic", images=(f"logos/{away.tricode.lower()}.svg",
                                                             f"logos/{home.tricode.lower()}.svg"),
                             accents=("#000000", "#000000"), kind="pair"))
    copy = json.loads((config.DATA_DIR / "copy.json").read_text(encoding="utf-8"))
    raw = json.loads((config.DATA_DIR / "countries.json").read_text(encoding="utf-8"))
    for slug, country in raw["countries"].items():
        place = copy["country"].get("places", {}).get(slug, country["name"])
        flag = country.get("flag")
        share.svg(share.Card(slug, f"How to watch the NBA in {place}", "2026-27 · HoopsMatic",
                             images=(f"flags/{flag}.svg",) if flag else (), accents=("#000000",),
                             kind="flag" if flag else "plain"))
    with pytest.raises(ValueError):
        share.text_width("Ωmega", 40)


def test_a_card_is_drawn_again_only_when_its_inputs_change(tmp_path):
    a = share.Card("a", "How to watch the NBA", "2026-27 · HoopsMatic", accents=("#e8531a",))
    b = share.Card("b", "How to watch tonight's NBA games", "2026-27 · HoopsMatic", accents=("#e8531a",))
    assert share.write_images(tmp_path, [a, b], full=True).startswith("share images: 2 drawn, 0 unchanged")
    first = (tmp_path / a.path).read_bytes()
    assert share.write_images(tmp_path, [a, b], full=True).startswith("share images: 0 drawn, 2 unchanged")
    assert (tmp_path / a.path).read_bytes() == first

    changed = share.Card("a", "How to watch the NBA", "2027-28 · HoopsMatic", accents=("#e8531a",))
    assert share.write_images(tmp_path, [changed], full=False).startswith("share images: 1 drawn, 0 unchanged")
    assert (tmp_path / b.path).is_file()          # the refresh leaves other cards alone

    note = share.write_images(tmp_path, [changed], full=True)
    assert note.endswith("1 removed") and not (tmp_path / b.path).exists()
    state = json.loads((tmp_path / share.STATE_FILE).read_text(encoding="utf-8"))
    assert set(state) == {changed.path}


def test_cards_use_only_local_files():
    """Logos and flags are embedded from assets/, so the SVG names no URL."""
    team = load_teams()[0]
    markup = share.svg(share.Card(team.slug, "How to watch", "2026-27", images=(f"logos/{team.tricode.lower()}.svg",),
                                  accents=("#000000",), kind="team"))
    hrefs = re.findall(r'href="([^"]+)"', markup)
    assert hrefs and all(h.startswith("data:image/svg+xml;base64,") for h in hrefs)
