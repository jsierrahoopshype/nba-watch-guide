"""Both market states must be in the HTML so a crawler reads both."""

from __future__ import annotations


def _team_page(built_site, slug="boston-celtics"):
    return (built_site / slug / "index.html").read_text(encoding="utf-8")


def test_both_state_panels_are_prerendered(built_site):
    html = _team_page(built_site)
    assert 'data-state-panel="out_of_market"' in html
    assert 'data-state-panel="in_market"' in html


def test_out_of_market_is_the_default_view(built_site):
    html = _team_page(built_site)
    out_panel = html.split('data-state-panel="out_of_market"')[1].split(">")[0]
    in_panel = html.split('data-state-panel="in_market"')[1].split(">")[0]
    assert "hidden" not in out_panel
    assert "hidden" in in_panel
    assert 'data-state-btn="out_of_market" aria-selected="true"' in html


def test_toggle_buttons_exist_for_both_states(built_site):
    html = _team_page(built_site)
    assert 'data-state-btn="out_of_market"' in html
    assert 'data-state-btn="in_market"' in html


def test_every_team_page_has_both_states(built_site):
    from watchguide.model import load_teams
    for team in load_teams():
        html = _team_page(built_site, team.slug)
        assert 'data-state-panel="out_of_market"' in html
        assert 'data-state-panel="in_market"' in html
