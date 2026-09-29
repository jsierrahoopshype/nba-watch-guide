"""The noindex switch in data/copy.json, checked in both states.

While it is on, every page carries a noindex robots tag and sitemap.xml is
still written but lists nothing. Canonicals do not change either way.

Each state is forced by its own fixture (built_site_noindex,
built_site_indexed), so these tests pass whatever data/copy.json ships with.
"""

from __future__ import annotations

import re

from watchguide import config
from watchguide.manifest import read_manifest
from conftest import expected_page_count

ROBOTS = re.compile(r'<meta name="robots" content="([^"]*)"')
CANONICAL = re.compile(r'<link rel="canonical" href="([^"]+)"')
LOC = re.compile(r"<loc>([^<]+)</loc>")
ENTRY = re.compile(r"<url>\s*<loc>([^<]+)</loc>\s*<lastmod>(\d{4}-\d{2}-\d{2})</lastmod>\s*</url>")


def _pages(site):
    return sorted(site.rglob("index.html"))


# -- switched on -------------------------------------------------------------

def test_every_page_carries_the_noindex_tag(built_site_noindex):
    pages = _pages(built_site_noindex)
    assert len(pages) == expected_page_count()
    for page in pages:
        found = ROBOTS.findall(page.read_text(encoding="utf-8"))
        assert found == ["noindex,follow"], f"{page} robots tag is {found}"


def test_sitemap_exists_but_lists_nothing(built_site_noindex):
    sitemap = built_site_noindex / "sitemap.xml"
    assert sitemap.exists()
    xml = sitemap.read_text(encoding="utf-8")
    assert "<urlset" in xml
    assert LOC.findall(xml) == []


def test_robots_txt_does_not_advertise_the_sitemap(built_site_noindex):
    assert "Sitemap:" not in (built_site_noindex / "robots.txt").read_text(encoding="utf-8")


# -- switched off -----------------------------------------------------------

def test_no_robots_tag_when_indexing_is_allowed(built_site_indexed):
    pages = _pages(built_site_indexed)
    assert len(pages) == expected_page_count()
    for page in pages:
        assert ROBOTS.findall(page.read_text(encoding="utf-8")) == [], page


def test_sitemap_lists_every_page_when_indexing_is_allowed(built_site_indexed):
    xml = (built_site_indexed / "sitemap.xml").read_text(encoding="utf-8")
    assert len(LOC.findall(xml)) == expected_page_count()
    # Every manifest page, once, each with a lastmod.
    manifest = read_manifest(built_site_indexed)
    assert len(manifest) == expected_page_count()
    want = sorted(config.public_url(path[:-len("index.html")].rstrip("/")) for path in manifest)
    entries = ENTRY.findall(xml)
    assert sorted(url for url, _ in entries) == want


def test_robots_txt_advertises_the_sitemap_when_indexing_is_allowed(built_site_indexed):
    text = (built_site_indexed / "robots.txt").read_text(encoding="utf-8")
    assert f"Sitemap: {config.public_url('sitemap.xml')}" in text


# -- unchanged either way ---------------------------------------------------

def test_canonicals_are_identical_in_both_states(built_site_noindex, built_site_indexed):
    def canonicals(site):
        return {p.relative_to(site).as_posix(): CANONICAL.findall(p.read_text(encoding="utf-8"))
                for p in _pages(site)}
    assert canonicals(built_site_noindex) == canonicals(built_site_indexed)


def test_the_pages_host_stays_out_in_both_states(built_site_noindex, built_site_indexed):
    for site in (built_site_noindex, built_site_indexed):
        for path in site.rglob("*"):
            if path.is_file() and path.suffix in {".html", ".json", ".xml", ".txt"}:
                assert "github.io" not in path.read_text(encoding="utf-8", errors="ignore")
