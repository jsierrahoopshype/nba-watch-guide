"""Every CSS and JS URL in the output carries a content hash, so a publish
that changes a file changes its URL and no browser keeps the old copy."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from watchguide import config
from watchguide.render import asset, hashed_asset_name

ASSET_URL = re.compile(r'(?:href|src)="(/how-to-watch/assets/[^"]+)"')
HASHED = re.compile(r"^/how-to-watch/assets/(?P<stem>[\w-]+)\.(?P<hash>[0-9a-f]{10})\.(?P<ext>css|js)$")


def _pages(site: Path):
    return [p for p in site.rglob("*.html") if p.name == "index.html"]


def test_every_asset_url_is_hashed_and_the_file_exists(built_site):
    pages = _pages(built_site)
    assert len(pages) == 37
    seen = set()
    for page in pages:
        urls = ASSET_URL.findall(page.read_text(encoding="utf-8"))
        assert {u.rsplit(".", 1)[-1] for u in urls} >= {"css", "js"}, page
        for url in urls:
            m = HASHED.match(url)
            assert m, f"{page}: {url} has no content hash"
            served = built_site / url[len("/how-to-watch/"):]
            assert served.is_file(), f"{url} is referenced but not in the output"
            source = config.ASSET_DIR / f"{m['stem']}.{m['ext']}"
            assert served.read_bytes() == source.read_bytes()
            assert hashlib.sha256(source.read_bytes()).hexdigest()[:10] == m["hash"]
            seen.add(url)
    assert seen, "no asset URLs found"


def test_changing_a_file_changes_its_url(tmp_path, monkeypatch):
    (tmp_path / "watch-guide.js").write_text("one", encoding="utf-8")
    monkeypatch.setattr(config, "ASSET_DIR", tmp_path)
    first = asset("assets/watch-guide.js")
    (tmp_path / "watch-guide.js").write_text("two", encoding="utf-8")
    second = asset("assets/watch-guide.js")
    assert first != second
    assert first.startswith("/how-to-watch/assets/watch-guide.") and first.endswith(".js")
    assert hashed_asset_name("watch-guide.js", tmp_path) == second.rsplit("/", 1)[-1]


def test_plain_names_are_still_served_for_old_cached_html(built_site):
    for name in ("watch-guide.js", "watch-guide.css"):
        assert (built_site / "assets" / name).is_file()


def test_a_refresh_ships_the_assets_its_pages_name(tmp_path, monkeypatch, fixture_games):
    # A restored tree from before a code change: pages refreshed now name the
    # new hashes, so the refresh has to write those files as well.
    import json
    from dataclasses import asdict
    from conftest import TODAY
    from watchguide.build import refresh_build
    from watchguide.sources import injuries as injuries_source
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "data" / "schedule.json").write_text(json.dumps({
        "season": "2026-27", "updated_at": TODAY, "count": len(fixture_games),
        "games": [asdict(g) for g in fixture_games]}), encoding="utf-8")
    monkeypatch.setattr(injuries_source, "fetch_raw", lambda: [])
    monkeypatch.setattr(injuries_source, "fetch_player_teams", lambda: {})
    refresh_build(site, today=TODAY, repo_root=tmp_path)
    for page in _pages(site):
        for url in ASSET_URL.findall(page.read_text(encoding="utf-8")):
            assert (site / url[len("/how-to-watch/"):]).is_file(), url
