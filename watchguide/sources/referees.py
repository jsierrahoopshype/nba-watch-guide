"""Tonight's referee crews, for the "Also worth knowing" line under a game.

Source: jsierrahoopshype/nbareferees, which publishes
  https://jsierrahoopshype.github.io/nbareferees/data/tonights-crews.json
  {date, games: [{away, home, game_id, crew: [{name, slug}]}]}
from official.nba.com's game-officials endpoint (its
scripts/fetch_tonights_crews.py). crew holds officials 1-3; the alternate is
left out, as on that site. A name its matcher could not place has no slug.

Referee pages live at https://hoopsmatic.com/referees/referee/<slug>/index.html
(that repo's sitemap and canonicals). A name is linked only when its slug is
in the published data/referees.json, the list those pages are built from.

Everything is read at build time and in the 30-minute refresh; nothing is
requested by a reader's browser. The crews file is kept in the published tree
so a failed fetch later the same day still has the morning's copy; a file
dated any other day than the game's is never used.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .http import get

CREWS_URL = "https://jsierrahoopshype.github.io/nbareferees/data/tonights-crews.json"
REFEREES_URL = "https://jsierrahoopshype.github.io/nbareferees/data/referees.json"
PAGE_URL = "https://hoopsmatic.com/referees/referee/{slug}/index.html"
CREWS_CACHE = "data/tonights-crews.json"
PAGES_CACHE = "data/referee-pages.json"
MIN_PAGES = 50           # fewer referee pages than this is treated as a broken list


def crews_url() -> str:
    return os.environ.get("REFEREE_CREWS_URL") or CREWS_URL


def referees_url() -> str:
    return os.environ.get("REFEREES_URL") or REFEREES_URL


def page_url(slug: str) -> str:
    return PAGE_URL.format(slug=slug)


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def valid_crews(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("date"), str) and isinstance(data.get("games"), list)


def load(out_dir: Path, allow_fetch: bool = True) -> tuple[dict, set[str], str]:
    """(crews, slugs with a page, note). Never raises: a failed fetch keeps
    the last copy in the published tree; with none, no referee line shows."""
    notes = []
    crews = _read(out_dir / CREWS_CACHE)
    if allow_fetch:
        try:
            fetched = get(crews_url(), expect_json=True)
            if not valid_crews(fetched):
                raise ValueError("not a crews file")
            crews = fetched
            _write(out_dir / CREWS_CACHE, crews)
        except Exception as exc:          # a broken third-party file never fails the build
            notes.append(f"crews did not load ({type(exc).__name__}: {exc}); kept the last copy")
    crews = crews if valid_crews(crews) else {"date": "", "games": []}

    slugs = set(_read(out_dir / PAGES_CACHE) or [])
    if allow_fetch:
        try:
            listed = get(referees_url(), expect_json=True)
            fetched_slugs = {r["slug"] for r in listed if isinstance(r, dict) and r.get("slug")}
            if len(fetched_slugs) < MIN_PAGES:
                raise ValueError(f"only {len(fetched_slugs)} referees listed")
            slugs = fetched_slugs
            _write(out_dir / PAGES_CACHE, sorted(slugs))
        except Exception as exc:
            notes.append(f"referee list did not load ({type(exc).__name__}: {exc}); kept the last copy")
    note = (f"referees: crews dated {crews['date'] or 'none'} for {len(crews['games'])} games, "
            f"{len(slugs)} referee pages")
    return crews, slugs, "; ".join([note] + notes)


def crew_for(crews: dict, game) -> list[dict[str, str]]:
    """The crew for this game when the file is dated the game's Eastern date,
    matched on game id, else on away and home tricodes; [] otherwise."""
    if not crews or crews.get("date") != game.date_et:
        return []
    for entry in crews.get("games") or []:
        same_id = entry.get("game_id") and entry.get("game_id") == game.game_id
        same_teams = entry.get("away") == game.away_tricode and entry.get("home") == game.home_tricode
        if same_id or same_teams:
            return [m for m in entry.get("crew") or [] if isinstance(m, dict) and m.get("name")]
    return []
