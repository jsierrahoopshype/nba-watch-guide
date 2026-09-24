"""The cheapest-combination block, the price lines and the affiliate
disclosure, checked in the rendered HTML rather than only in the maths."""

from __future__ import annotations

import re

PAGE = "boston-celtics/index.html"
TOTAL = re.compile(r'<span class="combo-total">\$([0-9,.]+)')


def _html(site):
    return (site / PAGE).read_text(encoding="utf-8")


def test_cheapest_block_renders_with_a_total(built_site_priced):
    html = _html(built_site_priced)
    assert "Cheapest way to watch" in html
    assert "Cheapest combination" not in html          # the placeholder is gone
    totals = TOTAL.findall(html)
    assert totals, "no cheapest-combination total rendered"
    assert all(float(t.replace(",", "")) >= 0 for t in totals)


def test_confirmed_prices_replace_the_not_confirmed_line(built_site_priced):
    html = _html(built_site_priced)
    assert "$11.99" in html
    assert "Prices checked January 2027" in html


def test_affiliate_link_and_disclosure_appear_together(built_site_priced):
    html = _html(built_site_priced)
    assert 'rel="sponsored nofollow"' in html
    assert "earn HoopsMatic a commission" in html


def test_disclosure_stays_off_when_no_affiliate_link_is_set(built_site):
    html = _html(built_site)
    assert "earn HoopsMatic a commission" not in html
    assert 'rel="sponsored nofollow"' not in html


def test_the_priced_build_still_keeps_the_pages_host_out(built_site_priced):
    for path in built_site_priced.rglob("*"):
        if path.is_file() and path.suffix in {".html", ".json", ".xml"}:
            assert "github.io" not in path.read_text(encoding="utf-8", errors="ignore")
