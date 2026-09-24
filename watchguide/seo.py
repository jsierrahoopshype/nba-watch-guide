"""Titles, descriptions, canonical URLs, JSON-LD and the sitemap.

Every public URL comes from config.public_url, so the site base lives in one
place and nothing can leak the Pages host into the output.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from xml.sax.saxutils import escape

from markupsafe import Markup

from . import config

TITLE_MAX = 60
DESCRIPTION_MAX = 155


def _cut(text: str, limit: int) -> str:
    """Trim to a whole word inside the limit. No ellipsis, it wastes characters."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    clipped = text[:limit]
    if " " in clipped:
        clipped = clipped[: clipped.rindex(" ")]
    return clipped.rstrip(" ,.:;-")


def title(template: str, **fields: str) -> str:
    return _cut(template.format(**fields), TITLE_MAX)


def description(template: str, **fields: str) -> str:
    return _cut(template.format(**fields), DESCRIPTION_MAX)


# --------------------------------------------------------------------------
# JSON-LD
# --------------------------------------------------------------------------

def jsonld(blocks: list[dict[str, Any]]) -> Markup:
    """One script body per page. Returns '' when there is nothing to say.

    The result goes inside a script element, so it is marked safe and the three
    characters that could close that element early are written as escapes. HTML
    entities would not survive a JSON parser, so they must not be used here.
    """
    blocks = [b for b in blocks if b]
    if not blocks:
        return Markup("")
    payload = blocks[0] if len(blocks) == 1 else {"@context": "https://schema.org", "@graph": blocks}
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    text = text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return Markup(text)


def breadcrumbs(trail: list[tuple[str, str]]) -> dict[str, Any]:
    """trail is [(name, absolute url)] from the hub down to this page."""
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": name, "item": url}
            for i, (name, url) in enumerate(trail, start=1)
        ],
    }


def sports_event(game, home_name: str, away_name: str,
                 channels: list[dict[str, str]], page_url: str) -> dict[str, Any] | None:
    """A single game. Broadcast info is only added when the feed has a channel."""
    if not game.tipoff_utc:
        return None
    event: dict[str, Any] = {
        "@type": "SportsEvent",
        "name": f"{away_name} at {home_name}",
        "startDate": game.tipoff_utc,
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "url": page_url,
        "homeTeam": {"@type": "SportsTeam", "name": home_name},
        "awayTeam": {"@type": "SportsTeam", "name": away_name},
    }
    if game.arena:
        event["location"] = {"@type": "Place", "name": game.arena}
    real = [c["name"] for c in channels if c.get("kind") != "tba" and c.get("name")]
    if real:
        event["subEvent"] = [
            {
                "@type": "BroadcastEvent",
                "isLiveBroadcast": True,
                "broadcastOfEvent": {"@type": "SportsEvent", "name": f"{away_name} at {home_name}"},
                "publishedOn": {"@type": "BroadcastService", "name": channel},
            }
            for channel in real
        ]
    return event


def faq_page(entries: list[tuple[str, str]]) -> dict[str, Any] | None:
    """Only call this when the same questions are visible on the page."""
    entries = [(q, a) for q, a in entries if q and a]
    if not entries:
        return None
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in entries
        ],
    }


# --------------------------------------------------------------------------
# Sitemap
# --------------------------------------------------------------------------

def sitemap(entries: list[tuple[str, str]]) -> str:
    """entries is [(absolute url, lastmod YYYY-MM-DD)]. No trailing slashes."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url, lastmod in entries:
        if url.endswith("/"):
            raise ValueError(f"sitemap URL must not end with a slash: {url}")
        if not url.startswith(config.SITE_BASE):
            raise ValueError(f"sitemap URL must sit under {config.SITE_BASE}: {url}")
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(url)}</loc>")
        lines.append(f"    <lastmod>{escape(lastmod or date.today().isoformat())}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"
