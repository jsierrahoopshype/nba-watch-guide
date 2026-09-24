"""The sitemap lists the hub, tonight and all 30 teams, with no trailing slashes."""

from __future__ import annotations

import re

from watchguide import config

LOC = re.compile(r"<loc>([^<]+)</loc>")
LASTMOD = re.compile(r"<lastmod>([^<]+)</lastmod>")


def test_sitemap_lists_exactly_32_urls(built_site_indexed):
    xml = (built_site_indexed / "sitemap.xml").read_text(encoding="utf-8")
    urls = LOC.findall(xml)
    assert len(urls) == 32
    assert len(set(urls)) == 32
    assert len(LASTMOD.findall(xml)) == 32


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
