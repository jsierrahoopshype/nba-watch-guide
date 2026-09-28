"""The expected-pages manifest and the publish check that reads it."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

from conftest import TODAY, _copy_data
from watchguide.build import BuildError, check_pages, full_build
from watchguide.manifest import MANIFEST_FILE, expected_pages, read_manifest
from watchguide.model import load_teams
from watchguide.render import Page

ROOT = Path(__file__).resolve().parent.parent
PUBLISH = ROOT / "scripts" / "publish.sh"


def publish_check(site: Path) -> subprocess.CompletedProcess:
    """publish.sh with PUBLISH_CHECK_ONLY=1, so it never reaches git."""
    env = {**os.environ, "PUBLISH_CHECK_ONLY": "1", "GITHUB_TOKEN": "", "GITHUB_REPOSITORY": ""}
    return subprocess.run(["bash", str(PUBLISH), str(site), "gh-pages-test"],
                          capture_output=True, text=True, env=env, timeout=60)


def _with_extra_country(data_dir: Path) -> None:
    raw = json.loads((data_dir / "countries.json").read_text(encoding="utf-8"))
    extra = json.loads(json.dumps(raw["countries"]["spain"]))
    extra.update(name="Portugal", slug="portugal", timezone="Europe/Lisbon",
                 nationality_aliases=["Portugal", "Portuguese"], player_overrides=[])
    raw["countries"]["portugal"] = extra
    (data_dir / "countries.json").write_text(json.dumps(raw), encoding="utf-8")


# -- the manifest ----------------------------------------------------------------------

def test_manifest_comes_from_the_data():
    pages = expected_pages()
    teams = load_teams()
    assert len(pages) == 2 + len(teams) + 5
    assert "index.html" in pages and "tonight/index.html" in pages
    assert all(f"{t.slug}/index.html" in pages for t in teams)
    assert all(f"{s}/index.html" in pages for s in ("uk", "spain", "france", "germany", "italy"))


def test_build_writes_the_manifest(built_site):
    assert read_manifest(built_site) == expected_pages()
    found = sorted(str(p.relative_to(built_site)) for p in built_site.rglob("index.html"))
    assert found == read_manifest(built_site)


def test_a_new_country_raises_the_count_with_no_other_change(tmp_path_factory, fixture_games):
    """Only countries.json changes: no copy.json entry, no code, no test number."""
    data_dir = _copy_data(tmp_path_factory, "data-extra-country")
    before = expected_pages(data_dir)
    _with_extra_country(data_dir)
    after = expected_pages(data_dir)
    assert len(after) == len(before) + 1
    assert set(after) - set(before) == {"portugal/index.html"}

    out = tmp_path_factory.mktemp("site-extra-country")
    (out / "data").mkdir()
    (out / "data" / "schedule.json").write_text(json.dumps({
        "season": "2026-27", "updated_at": TODAY, "count": len(fixture_games),
        "games": [asdict(g) for g in fixture_games]}), encoding="utf-8")
    full_build(out, today=TODAY, offline=True, data_dir=data_dir)
    assert read_manifest(out) == after
    page = (out / "portugal" / "index.html").read_text(encoding="utf-8")
    assert "<title>How to Watch the NBA in Portugal in 2026-27</title>" in page
    assert publish_check(out).returncode == 0


def test_build_refuses_pages_that_do_not_match():
    expected = expected_pages()
    pages = [Page(out_path=p, url="", html="", lastmod="") for p in expected if p != "spain/index.html"]
    pages.append(Page(out_path="narnia/index.html", url="", html="", lastmod=""))
    with pytest.raises(BuildError) as err:
        check_pages(pages)
    assert "missing: spain/index.html" in str(err.value)
    assert "unexpected: narnia/index.html" in str(err.value)


# -- publish.sh ------------------------------------------------------------------------

@pytest.fixture
def site_copy(built_site, tmp_path):
    target = tmp_path / "site"
    shutil.copytree(built_site, target)
    return target


def test_publish_check_passes_on_a_full_build(site_copy):
    result = publish_check(site_copy)
    assert result.returncode == 0, result.stderr
    assert f"{len(expected_pages())} pages match" in result.stdout


def test_publish_refuses_a_missing_page_and_names_it(site_copy):
    (site_copy / "spain" / "index.html").unlink()
    result = publish_check(site_copy)
    assert result.returncode == 1
    n = len(expected_pages())
    assert f"expected {n} pages, found {n - 1}, refusing to publish" in result.stderr
    assert "missing pages:\n  spain/index.html" in result.stderr


def test_publish_refuses_an_unexpected_page_and_names_it(site_copy):
    (site_copy / "narnia").mkdir()
    (site_copy / "narnia" / "index.html").write_text("stale", encoding="utf-8")
    result = publish_check(site_copy)
    assert result.returncode == 1
    assert "unexpected pages:\n  narnia/index.html" in result.stderr


def test_publish_refuses_a_swap_with_the_same_count(site_copy):
    """Same number of pages, wrong paths: the count alone would have let it through."""
    (site_copy / "italy" / "index.html").unlink()
    (site_copy / "portugal").mkdir()
    (site_copy / "portugal" / "index.html").write_text("x", encoding="utf-8")
    result = publish_check(site_copy)
    assert result.returncode == 1
    assert "  italy/index.html" in result.stderr and "  portugal/index.html" in result.stderr


def test_publish_refuses_without_a_manifest(site_copy):
    (site_copy / MANIFEST_FILE).unlink()
    result = publish_check(site_copy)
    assert result.returncode == 1
    assert "expected-pages.txt is missing" in result.stderr


def test_no_script_or_workflow_hard_codes_a_page_count():
    paths = list((ROOT / "scripts").glob("*.sh")) + list((ROOT / ".github" / "workflows").glob("*.yml"))
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for number in ("32", "37"):
            assert f"-ne {number}" not in text and f"-eq {number}" not in text, path.name
            assert f"expected {number}" not in text, path.name


def test_refresh_writes_the_manifest_into_a_restored_tree(site_copy):
    """A tree restored from an older publish has no manifest; the refresh adds
    one, so publish.sh checks the refreshed tree against the current data."""
    from watchguide.build import refresh_build
    (site_copy / MANIFEST_FILE).unlink()
    refresh_build(site_copy, today=TODAY)
    assert read_manifest(site_copy) == expected_pages()
    assert publish_check(site_copy).returncode == 0
