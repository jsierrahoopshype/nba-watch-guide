"""The redesign: team and country cards, the partners footnote,
logos, flags, headshots, and the rule that no image comes from elsewhere."""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from conftest import TODAY, _build, _copy_data
from watchguide import config
from watchguide.context import load_context
from watchguide.pages.hub import country_cards, national_partners, team_summary
from watchguide.sources import headshots

ROOT = Path(__file__).resolve().parent.parent
TAGS = re.compile(r"<[^>]+>")
IMG = re.compile(r"<img\b[^>]*>")


def text(markup: str) -> str:
    return " ".join(html.unescape(TAGS.sub(" ", markup)).split())


def ctx_for(games, today=TODAY, data_dir=None):
    return load_context(games, today=today, data_dir=data_dir)


# -- team cards ------------------------------------------------------------------------

@pytest.fixture(scope="module")
def shipped_ctx(fixture_games):
    return ctx_for(fixture_games)


@pytest.mark.parametrize("slug, line, note", [
    ("miami-heat", "Free over the air on WPLG Local 10", ""),                    # high, every game on an antenna
    ("atlanta-hawks", "Free over the air on WANF (Gray)", "Check before you buy"),  # moderate
    ("san-antonio-spurs", "DAZN from $19.99/mo", ""),                             # shared DAZN price
    ("oklahoma-city-thunder", "Thunder+ (NBA App) from $19.99/mo", ""),          # partial OTA does not count
    ("boston-celtics", "Local games on NBC Sports Boston", ""),                   # price not verified
    ("toronto-raptors", "Local games on TSN and Sportsnet", ""),                  # not for US maths
    ("dallas-mavericks", "Local TV not confirmed yet", ""),                       # low
    ("la-clippers", "Local TV not announced yet", ""),                            # unknown
])
def test_team_summary_follows_the_confidence_rules(shipped_ctx, slug, line, note):
    team = shipped_ctx.by_slug[slug]
    summary = team_summary(shipped_ctx, team)
    assert (summary["text"], summary["note"]) == (line, note)


def test_team_cards_on_the_hub(built_site, teams):
    hub = (built_site / "index.html").read_text(encoding="utf-8")
    grid = hub[hub.index('id="teams"'):hub.index("</section>", hub.index('id="teams"'))]
    assert grid.count('class="tcard"') == 30
    for team in teams:
        assert f'href="{team.path}"' in grid
        assert re.search(rf'src="/how-to-watch/assets/logos/{team.tricode.lower()}\.[0-9a-f]{{10}}\.svg"', grid)
    assert "Free over the air on WPLG Local 10" in text(grid)


# -- countries, partners ---------------------------------------------------------------

def test_country_cards_use_svg_flags_and_partner(built_site, shipped_ctx):
    cards = country_cards(shipped_ctx)
    assert [(c["flag"], c["partner"]) for c in cards] == [
        ("assets/flags/gb.svg", "Sky Sports"), ("assets/flags/es.svg", "DAZN"),
        ("assets/flags/fr.svg", "beIN SPORTS"), ("assets/flags/de.svg", "Sky Deutschland / WOW"),
        ("assets/flags/it.svg", "Sky Italia / NOW")]
    hub = (built_site / "index.html").read_text(encoding="utf-8")
    block = hub[hub.index('id="countries"'):hub.index("</section>", hub.index('id="countries"'))]
    assert len(re.findall(r'<img class="flag" src="/how-to-watch/assets/flags/\w\w\.[0-9a-f]{10}\.svg"', block)) == 5
    for regional in ("\U0001F1EC", "\U0001F1EA", "\U0001F1EB", "\U0001F1E9", "\U0001F1EE"):
        assert regional not in hub                                # no emoji flags


def test_a_country_without_a_flag_file_gets_no_image(fixture_games, tmp_path_factory):
    data_dir = _copy_data(tmp_path_factory, "data-no-flag")
    raw = json.loads((data_dir / "countries.json").read_text(encoding="utf-8"))
    raw["countries"]["spain"]["flag"] = "zz"
    (data_dir / "countries.json").write_text(json.dumps(raw), encoding="utf-8")
    spain = next(c for c in country_cards(ctx_for(fixture_games, data_dir=data_dir)) if c["country"].slug == "spain")
    assert spain["flag"] == ""


def test_simulcasts_are_a_footnote_not_badges(fixture_games):
    games = [replace(g, national=["NBC", "NBCSN"]) if i == 0 else
             replace(g, national=["NBC", "Telemundo"]) if i == 1 else g
             for i, g in enumerate(fixture_games)]
    ctx = ctx_for(games)
    codes = [p["code"] for p in national_partners(ctx)]
    assert "NBCSN" not in codes and "Telemundo" not in codes and "NBC" in codes


def test_footnote_shows_only_when_those_codes_are_in_the_feed(tmp_path_factory, fixture_games):
    games = [replace(g, national=["NBC", "NBCSN"]) if i == 0 else g for i, g in enumerate(fixture_games)]
    with_codes = (_build(tmp_path_factory, games, "hub-footnote") / "index.html").read_text(encoding="utf-8")
    box = with_codes[with_codes.index('id="national"'):with_codes.index("</section>", with_codes.index('id="national"'))]
    assert ("NBCSN simulcasts Peacock&#39;s Monday games; Telemundo carries NBC games in Spanish." in box)
    assert '<span class="badge badge-national">NBCSN</span>' not in box
    without = (_build(tmp_path_factory, fixture_games, "hub-no-footnote") / "index.html").read_text(encoding="utf-8")
    assert "data-national-footnote" not in without


# -- logos, headshots, images ----------------------------------------------------------

def test_every_team_has_a_logo_file(teams):
    for team in teams:
        assert (config.ASSET_DIR / "logos" / f"{team.tricode.lower()}.svg").is_file(), team.tricode


def test_team_and_country_pages_carry_logo_and_flag_in_the_header(built_site):
    team = (built_site / "boston-celtics" / "index.html").read_text(encoding="utf-8")
    head = team[team.index('class="phead"'):team.index("</h1>")]
    assert re.search(r'<img class="logo logo-lg" src="/how-to-watch/assets/logos/bos\.[0-9a-f]{10}\.svg" width="56" height="56"', head)
    spain = (built_site / "spain" / "index.html").read_text(encoding="utf-8")
    head = spain[spain.index('class="phead"'):spain.index("</h1>")]
    assert re.search(r'<img class="flag flag-lg" src="/how-to-watch/assets/flags/es\.[0-9a-f]{10}\.svg" width="40" height="30"', head)


def test_every_image_is_local_and_sized(built_site):
    for page in built_site.rglob("index.html"):
        for tag in IMG.findall(page.read_text(encoding="utf-8")):
            src = re.search(r'src="([^"]+)"', tag).group(1)
            assert src.startswith("/how-to-watch/assets/"), (page, src)
            assert (built_site / src[len("/how-to-watch/"):]).is_file(), (page, src)
            assert re.search(r'width="\d+"', tag) and re.search(r'height="\d+"', tag), (page, tag)


def test_hub_images_are_lazy(built_site):
    hub = (built_site / "index.html").read_text(encoding="utf-8")
    tags = IMG.findall(hub)
    assert tags and all('loading="lazy"' in t for t in tags)


def test_no_page_asks_another_domain_for_anything(built_site):
    for page in built_site.rglob("index.html"):
        markup = page.read_text(encoding="utf-8")
        assert "fonts.googleapis.com" not in markup and "fonts.gstatic.com" not in markup, page
        for url in re.findall(r'<(?:link|script|img)[^>]+(?:href|src)="([^"]+)"', markup):
            assert url.startswith("/how-to-watch") or url.startswith(config.SITE_BASE), (page, url)
    css = (config.ASSET_DIR / "watch-guide.css").read_text(encoding="utf-8")
    assert "http" not in re.sub(r"/\*.*?\*/", "", css, flags=re.S), "the stylesheet loads something remote"


def test_hub_cards_show_the_named_players_or_a_silhouette(built_site, fixture_games):
    """No headshots on this offline build, so every named player gets the silhouette."""
    hub = (built_site / "index.html").read_text(encoding="utf-8")
    block = hub[hub.index("data-hub-games"):hub.index("</section>", hub.index("data-hub-games"))]
    for row in block.split('<li class="hg-row" ')[1:]:
        assert row.count('<img class="logo"') == 2
        for tag in re.findall(r'<img class="av"[^>]*>', row):
            assert re.search(r'src="/how-to-watch/assets/silhouette\.[0-9a-f]{10}\.svg"', tag)


# -- headshot source -------------------------------------------------------------------

INDEX = {"players": [
    {"full_name": "Star Alpha", "headshot": {"face": True, "filename": "1-star-alpha.png"}},
    {"full_name": "Star Bravo", "headshot": {"face": True, "filename": "2-star-bravo.png"}},
    {"full_name": "No Face", "headshot": {"face": False, "filename": "3-no-face.png"}},
]}
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 fake"


def test_index_maps_names_to_face2_files():
    idx = headshots.index_from(INDEX)
    assert idx == {"star alpha": "1-star-alpha", "star bravo": "2-star-bravo"}


def test_faces_are_downloaded_once_and_failures_fall_back(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        if url.endswith("2-star-bravo.webp"):
            raise headshots.FetchError("404")
        return WEBP

    monkeypatch.setattr(headshots, "get", fake_get)
    idx = headshots.index_from(INDEX)
    found, note = headshots.ensure_faces(tmp_path, ["Star Alpha", "Star Bravo", "Nobody"], idx)
    assert found == {"star alpha": "assets/faces/1-star-alpha.webp"}
    assert (tmp_path / "assets/faces/1-star-alpha.webp").read_bytes() == WEBP
    assert "1 failed (silhouette shown)" in note
    assert calls[0].endswith("/players/headshots/face2-160/1-star-alpha.webp")
    calls.clear()
    found, _ = headshots.ensure_faces(tmp_path, ["Star Alpha"], idx)
    assert found and not calls                                     # already on disk, not fetched again


def test_hub_uses_downloaded_faces(tmp_path_factory, fixture_games, monkeypatch):
    """Stars on the first two games of the day, faces served from assets/faces."""
    today = sorted((g for g in fixture_games if g.date_et == TODAY), key=lambda g: g.game_id)
    data_dir = _copy_data(tmp_path_factory, "data-faces")
    awards = [{"player": n, "season": "2025-26", "award": "all_nba_first"} for n in ("Star Alpha", "Star Bravo")]
    (data_dir / "recent_awards.json").write_text(json.dumps({"awards": awards}), encoding="utf-8")
    site = tmp_path_factory.mktemp("hub-faces")
    (site / "data").mkdir()
    (site / "data" / "star-rosters.json").write_text(json.dumps({"fetched_at": "t", "teams": {
        today[0].home_tricode: [{"player": "Star Alpha", "all_star": 0}],
        today[1].away_tricode: [{"player": "Star Bravo", "all_star": 0}]}}), encoding="utf-8")
    (site / "data" / "schedule.json").write_text(json.dumps({
        "season": "2026-27", "updated_at": TODAY, "count": len(fixture_games),
        "games": [asdict(g) for g in fixture_games]}), encoding="utf-8")
    (site / headshots.INDEX_CACHE).write_text(json.dumps({"faces": headshots.index_from(INDEX)}), encoding="utf-8")
    faces = site / headshots.FACES
    faces.mkdir(parents=True)
    (faces / "1-star-alpha.webp").write_bytes(WEBP)      # as restored from the last publish
    from watchguide.build import full_build
    full_build(site, today=TODAY, offline=True, data_dir=data_dir)
    hub = (site / "index.html").read_text(encoding="utf-8")
    row = next(r for r in hub.split('<li class="hg-row" ')[1:] if r.startswith(f'data-game="{today[0].game_id}"'))
    assert ('<img class="av" src="/how-to-watch/assets/faces/1-star-alpha.webp" width="40" height="40" '
            'loading="lazy" decoding="async" alt="Star Alpha" title="Star Alpha">') in row
    other = next(r for r in hub.split('<li class="hg-row" ')[1:] if r.startswith(f'data-game="{today[1].game_id}"'))
    assert "Star Bravo" not in re.findall(r'<img class="av"[^>]*>', other)[0]     # no face on disk: silhouette
    assert "silhouette" in other
