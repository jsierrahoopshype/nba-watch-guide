"""The link block the Worker pastes into the HoopsMatic homepage.

Not a page of its own: it is a fragment written to data/how-to-watch-links.html
so the guide has an internal crawl path from a page search engines already
visit. Absolute URLs, class names only, nothing else. It links the hub, every
team, the tonight page and every country page in data/countries.json.
"""

from __future__ import annotations

from html import escape

from .. import config
from ..context import SiteContext


def render(ctx: SiteContext) -> str:
    season = escape(ctx.season)
    lines = [
        '<nav class="hm-watch-links" aria-label="How to watch the NBA">',
        f'  <h2 class="hm-watch-links__title">How to watch the NBA in {season}</h2>',
        f'  <p class="hm-watch-links__intro">'
        f'<a class="hm-watch-links__hub" href="{config.public_url()}">'
        f'Every team, channel by channel</a></p>',
        '  <ul class="hm-watch-links__list">',
    ]
    for team in ctx.teams:
        lines.append(
            f'    <li class="hm-watch-links__item">'
            f'<a href="{team.url}">How to watch the {escape(team.full_name)}</a></li>'
        )
    lines += [
        '  </ul>',
        f'  <p class="hm-watch-links__tonight">'
        f'<a href="{config.public_url("tonight")}">NBA games today and where to watch them</a></p>',
    ]
    countries = ctx.countries.countries
    if countries:
        places = ctx.copy.get("country", {}).get("places", {})
        lines.append('  <ul class="hm-watch-links__countries">')
        for country in countries:
            place = escape(places.get(country.slug, country.name))
            lines.append(
                f'    <li class="hm-watch-links__item">'
                f'<a href="{country.url}">How to watch the NBA in {place}</a></li>'
            )
        lines.append('  </ul>')
    lines.append('</nav>')
    return "\n".join(lines) + "\n"
