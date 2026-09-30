"""Career head-to-head between the two players in a game's "Players to watch".

Source: jsierrahoopshype/nba-matchups, published at hoopsmatic.com/matchups/.
  - sitemap.xml lists every page; a pair page is
    https://hoopsmatic.com/matchups/m/<slug-a>-vs-<slug-b>.html with the two
    player slugs in alphabetical order.
  - data/player_index.json maps each player's name to their slug.
  - data/m/<pair>.json holds the pair's numbers: aGuardedByB and bGuardedByA,
    each with a career block (possessions, points and so on) and ytdLabel,
    the last season loaded ("2025-26").

Read from the repo's raw files at build time and in the refresh; nothing is
requested by a reader's browser. Pair files are kept in the published tree
and fetched again after REFETCH_DAYS, so each is normally downloaded once a
month. Only pairs with a page in the sitemap are ever linked.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .careers import match_key
from .http import get

DEFAULT_BASE = "https://raw.githubusercontent.com/jsierrahoopshype/nba-matchups/main"
PAGE_URL = "https://hoopsmatic.com/matchups/m/{pair}.html"
CACHE_DIR = "data/matchups"
PAGES_CACHE = "data/matchups/pages.json"
INDEX_CACHE = "data/matchups/players.json"
REFETCH_DAYS = 30
MIN_PAGES = 200          # fewer pair pages than this is treated as a broken sitemap
# The line only shows when the two players have guarded each other for at
# least this many possessions in total (both directions, regular season and
# playoffs, 2017-18 on). About 9 in 10 published pairs clear it.
MIN_POSSESSIONS = 300


def base_url() -> str:
    return (os.environ.get("MATCHUPS_BASE") or DEFAULT_BASE).rstrip("/")


def page_url(pair: str) -> str:
    return PAGE_URL.format(pair=pair)


def pair_slug(slug_a: str, slug_b: str) -> str:
    return "-vs-".join(sorted((slug_a, slug_b)))


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def pages_from_sitemap(xml: str) -> set[str]:
    return set(re.findall(r"/matchups/m/([a-z0-9-]+-vs-[a-z0-9-]+)\.html", xml))


class Matchups:
    """Which pair pages exist, each player's slug, and the pairs' numbers."""

    def __init__(self, pages: set[str] | None = None, slugs: dict[str, str] | None = None,
                 pairs: dict[str, dict] | None = None):
        self.pages = pages or set()
        self.slugs = slugs or {}                 # match_key(name) -> slug
        self.pairs = pairs or {}                 # pair slug -> data/m/<pair>.json

    def pair_for(self, name_a: str, name_b: str) -> str:
        """The pair page slug for two player names, or "" without a page."""
        a, b = self.slugs.get(match_key(name_a)), self.slugs.get(match_key(name_b))
        if not a or not b or a == b:
            return ""
        pair = pair_slug(a, b)
        return pair if pair in self.pages else ""

    def headline(self, name_a: str, name_b: str) -> dict | None:
        """{pair, url, possessions, season} for a pair with a page, loaded
        numbers and at least MIN_POSSESSIONS; None otherwise."""
        pair = self.pair_for(name_a, name_b)
        data = self.pairs.get(pair) if pair else None
        if not data:
            return None
        try:
            poss = float(data["aGuardedByB"]["career"]["poss"]) + float(data["bGuardedByA"]["career"]["poss"])
        except (KeyError, TypeError, ValueError):
            return None
        if poss < MIN_POSSESSIONS:
            return None
        return {"pair": pair, "url": page_url(pair), "possessions": int(round(poss)),
                "season": str(data.get("ytdLabel") or "")}


def load(out_dir: Path, wanted: Iterable[tuple[str, str]], allow_fetch: bool = True) -> tuple[Matchups, str]:
    """Matchups for the name pairs in `wanted`. Never raises: anything that
    fails to load keeps its last copy in the published tree, or is left out."""
    notes = []
    pages = set(_read(out_dir / PAGES_CACHE) or [])
    index = _read(out_dir / INDEX_CACHE) or {}
    if allow_fetch:
        try:
            fetched = pages_from_sitemap(get(f"{base_url()}/sitemap.xml").decode("utf-8", "replace"))
            if len(fetched) < MIN_PAGES:
                raise ValueError(f"only {len(fetched)} pair pages in the sitemap")
            pages = fetched
            _write(out_dir / PAGES_CACHE, sorted(pages))
        except Exception as exc:          # a broken third-party file never fails the build
            notes.append(f"sitemap did not load ({type(exc).__name__}: {exc})")
        try:
            players = get(f"{base_url()}/data/player_index.json", expect_json=True)
            fetched_index = {match_key(p["name"]): p["slug"] for p in players
                             if isinstance(p, dict) and p.get("name") and p.get("slug")}
            if len(fetched_index) < MIN_PAGES:
                raise ValueError(f"only {len(fetched_index)} players indexed")
            index = fetched_index
            _write(out_dir / INDEX_CACHE, index)
        except Exception as exc:
            notes.append(f"player index did not load ({type(exc).__name__}: {exc})")

    found = Matchups(pages, index)
    now = datetime.now(timezone.utc)
    fetched_pairs = 0
    for name_a, name_b in wanted:
        pair = found.pair_for(name_a, name_b)
        if not pair or pair in found.pairs:
            continue
        path = out_dir / CACHE_DIR / "m" / f"{pair}.json"
        cached = _read(path)
        fresh = False
        if isinstance(cached, dict) and cached.get("fetched_at"):
            try:
                fresh = now - datetime.fromisoformat(cached["fetched_at"]) < timedelta(days=REFETCH_DAYS)
            except ValueError:
                fresh = False
        if allow_fetch and not fresh:
            try:
                data = get(f"{base_url()}/data/m/{pair}.json", expect_json=True)
                if not isinstance(data, dict) or "aGuardedByB" not in data:
                    raise ValueError("not a matchup file")
                cached = {"fetched_at": now.isoformat(timespec="seconds"), "data": data}
                _write(path, cached)
                fetched_pairs += 1
            except Exception as exc:
                notes.append(f"{pair} did not load ({type(exc).__name__})")
        if isinstance(cached, dict) and isinstance(cached.get("data"), dict):
            found.pairs[pair] = cached["data"]
    note = (f"matchups: {len(pages)} pair pages, {len(found.pairs)} pairs loaded for game cards, "
            f"{fetched_pairs} downloaded")
    return found, "; ".join([note] + notes[:5])
