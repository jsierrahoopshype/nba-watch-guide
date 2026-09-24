"""Every page carries exactly one canonical, pointing at the public site."""

from __future__ import annotations

import re

from watchguide import config

CANONICAL = re.compile(r'<link rel="canonical" href="([^"]+)"')
OG_URL = re.compile(r'<meta property="og:url" content="([^"]+)"')


def _pages(built_site):
    return sorted(built_site.rglob("index.html"))


def test_one_canonical_per_page(built_site):
    pages = _pages(built_site)
    assert len(pages) == 32
    for page in pages:
        html = page.read_text(encoding="utf-8")
        found = CANONICAL.findall(html)
        assert len(found) == 1, f"{page} has {len(found)} canonical tags"
        assert found[0].startswith(config.SITE_BASE), found[0]
        assert not found[0].endswith("/"), found[0]


def test_og_url_matches_canonical(built_site):
    for page in _pages(built_site):
        html = page.read_text(encoding="utf-8")
        assert CANONICAL.findall(html) == OG_URL.findall(html)


def test_one_h1_per_page(built_site):
    for page in _pages(built_site):
        html = page.read_text(encoding="utf-8")
        assert html.count("<h1>") == 1, f"{page} does not have exactly one H1"


def test_titles_and_descriptions_within_limits(built_site):
    title = __import__("re").compile(r"<title>([^<]*)</title>")
    desc = __import__("re").compile(r'<meta name="description" content="([^"]*)"')
    for page in _pages(built_site):
        html = page.read_text(encoding="utf-8")
        assert len(title.findall(html)[0]) <= 60
        assert len(desc.findall(html)[0]) <= 155


def test_jsonld_parses_and_is_not_html_escaped(built_site):
    import json
    import re
    block = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
    for page in _pages(built_site):
        html = page.read_text(encoding="utf-8")
        found = block.findall(html)
        assert len(found) == 1, f"{page} should carry one JSON-LD block"
        assert "&#34;" not in found[0], f"{page} has HTML-escaped JSON-LD"
        data = json.loads(found[0])
        types = [n.get("@type") for n in (data.get("@graph") or [data])]
        assert "BreadcrumbList" in types, f"{page} is missing BreadcrumbList"


def test_faq_jsonld_only_where_the_faq_is_visible(built_site):
    import json
    import re
    block = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
    for page in _pages(built_site):
        html = page.read_text(encoding="utf-8")
        data = json.loads(block.findall(html)[0])
        types = [n.get("@type") for n in (data.get("@graph") or [data])]
        assert ("FAQPage" in types) == ('class="faq"' in html), page
