"""The sitemap lists the hub, tonight, all 30 teams and the 5 country pages, with no trailing slashes."""

from __future__ import annotations

import re

from watchguide import config
from conftest import expected_page_count

LOC = re.compile(r"<loc>([^<]+)</loc>")
LASTMOD = re.compile(r"<lastmod>([^<]+)</lastmod>")


def test_sitemap_lists_one_url_per_expected_page(built_site_indexed):
    xml = (built_site_indexed / "sitemap.xml").read_text(encoding="utf-8")
    urls = LOC.findall(xml)
    assert len(urls) == expected_page_count()
    assert len(set(urls)) == expected_page_count()
    assert len(LASTMOD.findall(xml)) == expected_page_count()


def test_sitemap_urls_are_public_and_clean(built_site_indexed):
    xml = (built_site_indexed / "sitemap.xml").read_text(encoding="utf-8")
    for url in LOC.findall(xml):
        assert url.startswith(config.SITE_BASE), url
        assert not url.endswith("/"), url


def test_sitemap_covers_hub_tonight_and_every_team(built_site_indexed):
    from watchguide.model import load_teams
    xml = (built_site_indexed / "sitemap.xml").read_text(encoding="utf-8")
    urls = set(LOC.findall(xml))
    assert config.public_url() in urls
    assert config.public_url("tonight") in urls
    for team in load_teams():
        assert config.public_url(team.slug) in urls


def test_sitemap_covers_every_country_page(built_site_indexed):
    xml = (built_site_indexed / "sitemap.xml").read_text(encoding="utf-8")
    urls = set(LOC.findall(xml))
    for slug in ("uk", "spain", "france", "germany", "italy"):
        assert f"https://hoopsmatic.com/how-to-watch/{slug}" in urls
