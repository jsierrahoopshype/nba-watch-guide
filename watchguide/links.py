"""Outbound "where to watch" links: which page of a service an option links to.

Every link comes from the data files, never from code:

- data/services.json: each national service has a `links` block with one
  entry per level of the precision ladder it has (LEVELS below). An entry is
  {"url", "verified", "checked", "sample", "confidence", "how"}; `url` may
  hold placeholders filled from the game (PLACEHOLDERS). Only entries with
  verified true are used; a service with none gets no link.
- data/local_tv.json: each team's `links` list, one entry per station or
  stream: {"names", "kind", "level", "url", "verified", ...}. `names` are
  the names the option goes by (the schedule feed's codes, local_broadcasters
  and streaming names), matched exactly.
- data/countries.json: each country's `links`, keyed by the option's name
  on the country page.

The most specific verified level wins: the game's own page, then the
service's schedule for the game's date, then its NBA section, its signup
page and last its homepage. Without a game (a team's services list) only
the section and below apply.

Affiliate links: an `affiliate_url` (on the service in services.json, on the
entry in local_tv.json and countries.json) replaces the href when filled in.
The link then reads "Sign up for ..." and carries rel="sponsored nofollow
noopener", and the page gets the disclosure line (OutLinks below). Every
affiliate_url is empty for now, so none of that shows.

Links never change an answer: they are looked up after the coverage maths,
by name, and the build with WATCH_GUIDE_NO_LINKS=1 is the same page minus
the anchors (tests/test_outbound_links.py).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from markupsafe import Markup, escape

LEVELS = ("game", "date", "section", "signup", "home")
GAME_LEVELS = ("game", "date")          # need a game to fill in
PLACEHOLDERS = ("{away}", "{home}", "{game_id}", "{yyyymmdd}", "{yyyy-mm-dd}")
REL = "noopener"
REL_SPONSORED = "sponsored nofollow noopener"


def enabled() -> bool:
    """False when WATCH_GUIDE_NO_LINKS is set: the same pages, no anchors."""
    return not os.environ.get("WATCH_GUIDE_NO_LINKS")


@dataclass(frozen=True)
class Link:
    href: str
    label: str                  # "Watch on ESPN Unlimited" or "Sign up for ..."
    level: str
    sponsored: bool = False

    @property
    def rel(self) -> str:
        return REL_SPONSORED if self.sponsored else REL


def fill(url: str, game=None) -> str:
    """The template with the game's fields in. "" when it needs a game and
    has none, or names a placeholder this module does not know."""
    if not url:
        return ""
    if game is None:
        return "" if "{" in url else url
    date = game.date_et or ""
    out = (url.replace("{away}", (game.away_tricode or "").lower())
              .replace("{home}", (game.home_tricode or "").lower())
              .replace("{game_id}", game.game_id or "")
              .replace("{yyyymmdd}", date.replace("-", ""))
              .replace("{yyyy-mm-dd}", date))
    return "" if "{" in out or "}" in out else out


def label(name: str, level: str, copy: dict[str, Any], kind: str = "") -> str:
    """"Watch on X" when the link reaches the game, a schedule, the NBA
    section or a station's site; "Sign up for X" for a signup page. A free
    over-the-air station never says sign up."""
    text = copy.get("links", {})
    if level == "signup" and kind not in ("station", "ota"):
        return text.get("signup", "Sign up for {service}").format(service=name)
    return text.get("watch", "Watch on {service}").format(service=name)


def _usable(entry: Any) -> bool:
    return isinstance(entry, dict) and entry.get("verified") is True and bool(entry.get("url"))


def best(levels: dict[str, Any], game=None) -> tuple[str, str]:
    """(level, href) for the most specific verified level, or ("", "")."""
    for level in LEVELS:
        if level in GAME_LEVELS and game is None:
            continue
        entry = (levels or {}).get(level)
        if _usable(entry):
            href = fill(entry["url"], game)
            if href:
                return level, href
    return "", ""


def make(name: str, level: str, href: str, copy: dict[str, Any], kind: str = "",
         affiliate: str = "", game=None) -> Link | None:
    """A Link, with an affiliate_url taking over the href when it is set."""
    affiliate = fill(affiliate, game) if affiliate else ""
    if affiliate:
        return Link(href=affiliate, label=label(name, "signup", copy, kind), level="signup", sponsored=True)
    if not href:
        return None
    return Link(href=href, label=label(name, level, copy, kind), level=level)


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------

def service_link(svc, copy: dict[str, Any], game=None, name: str = "") -> Link | None:
    """A national service's link (data/services.json)."""
    if svc is None or not enabled():
        return None
    level, href = best(getattr(svc, "links", None) or {}, game)
    return make(name or svc.name, level, href, copy, svc.kind, svc.affiliate_url, game)


def local_entry(entries: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """The data/local_tv.json link entry for a channel or option name: an
    exact match first, then the first part of a feed code like "ALT/ALT+"."""
    for candidate in [name] + [p for p in (name or "").split("/") if p and p != name][:1]:
        for entry in entries:
            if candidate in (entry.get("names") or []) and _usable(entry):
                return entry
    return None


def local_link(entries: list[dict[str, Any]], name: str, copy: dict[str, Any],
               display: str = "") -> Link | None:
    """A station's or local stream's link, labelled with `display` or the
    entry's first name (its full name, not a feed code like "NBCSB")."""
    if not enabled():
        return None
    entry = local_entry(entries, name)
    if entry is None:
        return None
    level = entry.get("level") or "home"
    return make(display or (entry.get("names") or [name])[0], level, fill(entry["url"]), copy,
                entry.get("kind", ""), entry.get("affiliate_url", ""))


def country_link(entries: dict[str, Any], key: str, copy: dict[str, Any], display: str = "") -> Link | None:
    """A country page option's link (data/countries.json links[key])."""
    if not enabled():
        return None
    entry = (entries or {}).get(key)
    if not _usable(entry):
        return None
    return make(display or key, entry.get("level") or "section", fill(entry["url"]), copy, "",
                entry.get("affiliate_url", ""))


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

class OutLinks:
    """Writes an outbound anchor's attributes and remembers whether the page
    being rendered has a sponsored one, so base.html can add the disclosure
    after the content. base.html calls reset() first thing on every page."""

    def __init__(self) -> None:
        self.sponsored = False

    def reset(self) -> str:
        self.sponsored = False
        return ""

    def attrs(self, link: Link) -> Markup:
        self.sponsored = self.sponsored or link.sponsored
        name = escape(link.label)
        return Markup(f'class="out" data-out href="{escape(link.href)}" target="_blank" '
                      f'rel="{link.rel}" aria-label="{name}" title="{name}"')
