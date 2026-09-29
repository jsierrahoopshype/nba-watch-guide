"""Sitemap lastmod moves only when a page's content changes."""

from __future__ import annotations

import json
import re
from dataclasses import asdict

import pytest

from conftest import TODAY, _copy_data, expected_page_count
from watchguide import lastmod
from watchguide.build import full_build

OLD = "2026-01-01"
PAGE = """<!doctype html><html><head>
<link rel="stylesheet" href="/how-to-watch/assets/watch-guide.{css}.css"></head><body>
<h1>How to watch the Boston Celtics</h1>
<p class="updated" data-volatile><span data-updated>Updated {stamp} ET</span></p>
<div class="notice{hidden}" data-stale-notice data-volatile>Status may be out of date.</div>
<div class="game-sides" data-volatile><ul><li data-player="A">A <span class="badge badge-{badge}" data-status-slot>{status}</span></li></ul></div>
<img class="av" src="/how-to-watch/assets/faces/1-a.webp" width="40" height="40" data-volatile>
<p>{body}</p>
</body></html>"""


def page(**over):
    fields = {"css": "0123456789", "stamp": "2027-01-15 10:00", "hidden": " is-hidden",
              "badge": "out", "status": "Out", "body": "Next game: Tue Oct 20 at Detroit."}
    fields.update(over)
    return PAGE.format(**fields)


# -- the hash ----------------------------------------------------------------------

@pytest.mark.parametrize("change", [
    {"stamp": "2027-01-15 22:31"},                    # "Updated X min ago" fallback text
    {"hidden": ""},                                   # out-of-date notice shown
    {"badge": "questionable", "status": "Questionable"},  # badge the script refreshes
    {"css": "abcdef0123"},                            # new stylesheet hash
])
def test_volatile_parts_do_not_change_the_hash(change):
    assert lastmod.content_hash(page(**change)) == lastmod.content_hash(page())


def test_a_real_change_does():
    assert lastmod.content_hash(page(body="Next game: Wed Oct 21 vs Miami.")) != lastmod.content_hash(page())


def test_nested_volatile_markup_is_dropped_whole():
    text = lastmod.normalise('<div data-volatile><div><p>a</p></div><img src=x></div><p>kept</p>')
    assert text == "<p>kept</p>"


# -- the state ---------------------------------------------------------------------

def test_unchanged_keeps_its_date_and_changed_gets_today():
    prev = lastmod.update({}, {"u/a": page(), "u/b": page()}, OLD)
    assert prev == {"u/a": [lastmod.content_hash(page()), OLD], "u/b": [lastmod.content_hash(page()), OLD]}
    new = lastmod.update(prev, {"u/a": page(stamp="later"), "u/b": page(body="changed"), "u/c": page()}, TODAY)
    assert new["u/a"] == prev["u/a"]                 # volatile change only
    assert new["u/b"][1] == TODAY and new["u/b"][0] != prev["u/b"][0]
    assert new["u/c"][1] == TODAY                    # first seen


def test_state_file_is_one_sorted_entry_per_line(tmp_path):
    lastmod.write_state(tmp_path, {"b": ["2", OLD], "a": ["1", TODAY]})
    lines = (tmp_path / lastmod.STATE_FILE).read_text(encoding="utf-8").splitlines()
    assert lines == ["{", f'"a": ["1", "{TODAY}"],', f'"b": ["2", "{OLD}"]', "}"]
    assert lastmod.read_state(tmp_path) == {"a": ["1", TODAY], "b": ["2", OLD]}


# -- builds ------------------------------------------------------------------------

def _site(tmp_path_factory, fixture_games, label, injuries):
    out = tmp_path_factory.mktemp(label)
    (out / "data").mkdir()
    (out / "data" / "schedule.json").write_text(json.dumps({
        "season": "2026-27", "updated_at": TODAY, "count": len(fixture_games),
        "games": [asdict(g) for g in fixture_games]}), encoding="utf-8")
    (out / "data" / "injuries.json").write_text(json.dumps(injuries), encoding="utf-8")
    return out


def _backdate(site):
    state = lastmod.read_state(site)
    lastmod.write_state(site, {u: [h, OLD] for u, (h, _) in state.items()})


def test_a_rebuild_with_only_volatile_changes_moves_no_date(tmp_path_factory, fixture_games):
    first = sorted((g for g in fixture_games if g.date_et == TODAY), key=lambda g: g.game_id)[0]
    site = _site(tmp_path_factory, fixture_games, "lastmod-stable",
                 {"updated_at": f"{TODAY}T10:00:00-05:00", "as_of": "2027-01-14", "players": []})
    full_build(site, today=TODAY, offline=True)
    _backdate(site)                                  # as if everything was last built on OLD
    # A new injury report and a new "Updated" stamp: nothing a reader would call a change.
    (site / "data" / "injuries.json").write_text(json.dumps({
        "updated_at": f"{TODAY}T22:31:00-05:00", "as_of": TODAY, "players": [
            {"player": "Some Player", "status": "Out", "injury": "Knee", "date": TODAY,
             "team": first.home_tricode}]}), encoding="utf-8")
    full_build(site, today=TODAY, offline=True)
    state = lastmod.read_state(site)
    assert len(state) == expected_page_count()
    assert {d for _, d in state.values()} == {OLD}, [u for u, (_, d) in state.items() if d != OLD]


def test_a_content_change_moves_only_that_page(tmp_path_factory, fixture_games):
    site = _site(tmp_path_factory, fixture_games, "lastmod-change",
                 {"updated_at": "x", "as_of": "", "players": []})
    full_build(site, today=TODAY, offline=True)
    _backdate(site)
    data_dir = _copy_data(tmp_path_factory, "data-lastmod-change")
    copy = json.loads((data_dir / "copy.json").read_text(encoding="utf-8"))
    copy["country"]["h1"] = "Where to watch the NBA in {place} in {season}"
    (data_dir / "copy.json").write_text(json.dumps(copy), encoding="utf-8")
    full_build(site, today=TODAY, offline=True, data_dir=data_dir)
    moved = {u for u, (_, d) in lastmod.read_state(site).items() if d == TODAY}
    assert moved == {f"https://hoopsmatic.com/how-to-watch/{s}" for s in ("uk", "spain", "france", "germany", "italy")}


def test_state_is_kept_while_noindex_is_on(built_site_noindex):
    assert "<loc>" not in (built_site_noindex / "sitemap.xml").read_text(encoding="utf-8")
    assert len(lastmod.read_state(built_site_noindex)) == expected_page_count()


def test_sitemap_uses_the_stored_dates(built_site_indexed):
    state = lastmod.read_state(built_site_indexed)
    xml = (built_site_indexed / "sitemap.xml").read_text(encoding="utf-8")
    pairs = re.findall(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>", xml)
    assert len(pairs) == expected_page_count()
    assert all(state[u][1] == d for u, d in pairs)


def test_refresh_leaves_pages_it_does_not_write_alone(tmp_path_factory, fixture_games, monkeypatch):
    from watchguide.build import refresh_build
    from watchguide.sources import injuries as injuries_source
    site = _site(tmp_path_factory, fixture_games, "lastmod-refresh",
                 {"updated_at": "x", "as_of": "", "players": []})
    full_build(site, today=TODAY, offline=True)
    _backdate(site)
    before = lastmod.read_state(site)
    monkeypatch.setattr(injuries_source, "fetch_raw", lambda: [])
    monkeypatch.setattr(injuries_source, "fetch_player_teams", lambda: {})
    refresh_build(site, today=TODAY, repo_root=tmp_path_factory.mktemp("repo"))
    assert lastmod.read_state(site) == before        # same content, so no date moved
