"""The link block the Worker pastes into the homepage."""

from __future__ import annotations

import re

from watchguide import config
from watchguide.model import load_teams
from conftest import expected_page_count

HREF = re.compile(r'href="([^"]+)"')
BLOCK = "data/how-to-watch-links.html"


def _block(site):
    return (site / BLOCK).read_text(encoding="utf-8")


def test_the_block_is_generated(built_site):
    assert (built_site / BLOCK).exists()


def test_it_links_the_hub_tonight_all_thirty_teams_and_five_countries(built_site):
    links = HREF.findall(_block(built_site))
    assert len(links) == expected_page_count()
    assert config.public_url() in links
    assert config.public_url("tonight") in links
    for team in load_teams():
        assert team.url in links
    for slug in ("uk", "spain", "france", "germany", "italy"):
        assert f"https://hoopsmatic.com/how-to-watch/{slug}" in links


def test_country_links_read_as_sentences(built_site):
    html = _block(built_site)
    assert '<a href="https://hoopsmatic.com/how-to-watch/uk">How to watch the NBA in the UK</a>' in html
    assert '<a href="https://hoopsmatic.com/how-to-watch/spain">How to watch the NBA in Spain</a>' in html


def test_every_url_is_absolute_and_public(built_site):
    for url in HREF.findall(_block(built_site)):
        assert url.startswith(config.SITE_BASE), url
        assert not url.endswith("/"), url


def test_it_carries_class_names_but_no_styling_or_script(built_site):
    html = _block(built_site)
    assert 'class="hm-watch-links"' in html
    assert "<style" not in html
    assert "<script" not in html
    assert "style=" not in html


def test_it_keeps_the_pages_host_out(built_site):
    assert "github.io" not in _block(built_site)


def test_team_names_are_escaped_not_raw(built_site):
    html = _block(built_site)
    assert "How to watch the Philadelphia 76ers" in html
    assert "<li" in html
