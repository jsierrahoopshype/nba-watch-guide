"""Every title carries the HoopsMatic brand; the generated site never says HoopsHype."""

from __future__ import annotations

import html
import re

import pytest

from watchguide import seo

TITLE = re.compile(r"<title>([^<]*)</title>")
OG_TITLE = re.compile(r'<meta property="og:title" content="([^"]*)">')


@pytest.mark.parametrize("fixture", ["built_site", "built_site_indexed"])
def test_every_title_and_og_title_ends_with_the_brand(fixture, request):
    site = request.getfixturevalue(fixture)
    pages = sorted(site.rglob("index.html"))
    assert pages
    for page in pages:
        markup = page.read_text(encoding="utf-8")
        for pattern in (TITLE, OG_TITLE):
            found = [html.unescape(t) for t in pattern.findall(markup)]
            assert len(found) == 1, (page, pattern.pattern)
            assert found[0].endswith(" | HoopsMatic"), (page, found[0])
            assert len(found[0]) <= seo.TITLE_MAX, (page, found[0])
            assert len(found[0]) > len(" | HoopsMatic") + 10, (page, found[0])


def test_the_suffix_is_kept_and_the_title_part_shortened():
    assert seo.branded("How to Watch Heat Games 2026-27: TV & Streaming") == \
        "How to Watch Heat Games 2026-27: TV & Streaming | HoopsMatic"          # exactly 60
    assert seo.branded("How to Watch Timberwolves Games 2026-27: TV & Streaming") == \
        "How to Watch Timberwolves Games 2026-27 | HoopsMatic"                 # subtitle dropped
    long = seo.branded("A very long title with no subtitle that keeps going and going on")
    assert long.endswith(" | HoopsMatic") and len(long) <= 60 and not long.startswith(" ")


def test_hoopshype_never_appears_in_the_generated_site(built_site):
    """Any file, any case: pages, JSON, CSS, JS, SVG, the sitemap and robots.txt."""
    offenders = []
    for path in sorted(built_site.rglob("*")):
        if path.is_file() and b"hoopshype" in path.read_bytes().lower():
            offenders.append(str(path.relative_to(built_site)))
    assert offenders == [], f"HoopsHype found in: {offenders}"
