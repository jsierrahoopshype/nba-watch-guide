"""Current rosters and All-Star selections, for ranking tonight's games.

Source: jsierrahoopshype/nba-career-map, which refreshes daily from Wikipedia's
team roster templates:
  https://raw.githubusercontent.com/jsierrahoopshype/nba-career-map/main/nba_players_careers_READY.json
Checked on 2026-09-27: a list of 5,173 players, 598 with status "nba_active".
Each record has player, status, all_star_count (null for none) and
career_history, plus nationality ("France", "American / Italian", or null),
which the country pages read. This file has no current_team field: the current team is the
career_history entry whose years run to "present" and whose team is one of the
30 in data/teams.json (544 of the 598 active players have one).

Only a slim copy is kept, at data/star-rosters.json in the published tree. The
restore step brings it back on every run, so it is the last good copy when the
fetch fails. Set CAREER_MAP_URL to read a different copy of the same file.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .http import FetchError, get
from .injuries import normalize_name

DEFAULT_URL = ("https://raw.githubusercontent.com/jsierrahoopshype/nba-career-map/"
               "main/nba_players_careers_READY.json")
SOURCE_ID = "hoopsmatic-nba-career-map"
CACHE = "data/star-rosters.json"
# A fetch that places fewer players than this on NBA teams is treated as a
# broken file, and the last good copy is kept instead.
MIN_PLACED = 300


def feed_url() -> str:
    return os.environ.get("CAREER_MAP_URL") or DEFAULT_URL


def match_key(name: str) -> str:
    """injuries.normalize_name (which also applies data/player_aliases.json),
    with runs of single-letter initials joined, so 'V. J. Edgecombe' and
    'VJ Edgecombe' meet as 'vj edgecombe'."""
    parts = normalize_name(name).split()
    out: list[str] = []
    run = ""
    for part in parts:
        if len(part) == 1:
            run += part
            continue
        if run:
            out.append(run)
            run = ""
        out.append(part)
    if run:
        out.append(run)
    return " ".join(out)


def current_team(record: dict[str, Any], full_names: dict[str, str]) -> str:
    """Tricode of the NBA team whose stint runs to 'present', or ''."""
    for stint in reversed(record.get("career_history") or []):
        if re.search(r"present", str(stint.get("years", "")), re.I):
            tricode = full_names.get(stint.get("team", ""))
            if tricode:
                return tricode
    return ""


def rosters_from(records: list[dict[str, Any]], full_names: dict[str, str]) -> dict[str, Any]:
    """{tricode: [{player, all_star}]} plus counts of what was and was not placed,
    and {player: nationality} for the placed players whose record has one."""
    teams: dict[str, list[dict[str, Any]]] = {}
    nationalities: dict[str, str] = {}
    active = placed = 0
    for rec in records:
        if not isinstance(rec, dict) or rec.get("status") != "nba_active":
            continue
        active += 1
        tricode = current_team(rec, full_names)
        if not tricode:
            continue
        placed += 1
        name = rec.get("display_name") or rec.get("player") or ""
        teams.setdefault(tricode, []).append({
            "player": name,
            "all_star": int(rec.get("all_star_count") or 0),
        })
        if name and isinstance(rec.get("nationality"), str) and rec["nationality"].strip():
            nationalities[name] = rec["nationality"].strip()
    for players in teams.values():
        players.sort(key=lambda p: (-p["all_star"], p["player"]))
    return {"teams": teams, "active": active, "placed": placed, "nationalities": nationalities}


def read_cache(out_dir: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((out_dir / CACHE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data.get("teams"), dict) else None


def read_nationalities(out_dir: Path) -> dict[str, str]:
    """{player: nationality} from the slim copy the last load() wrote. Empty
    when there is no copy, or it predates nationalities being kept."""
    cached = read_cache(out_dir)
    found = (cached or {}).get("nationalities")
    return found if isinstance(found, dict) else {}


def load(out_dir: Path, full_names: dict[str, str], allow_fetch: bool = True
         ) -> tuple[dict[str, list[dict[str, Any]]], str]:
    """(rosters by tricode, note). Never raises: a failed or implausible fetch
    keeps the last good copy, and with no copy at all the rosters are empty."""
    cached = read_cache(out_dir)
    if allow_fetch:
        try:
            records = get(feed_url(), expect_json=True)
            if not isinstance(records, list):
                raise FetchError("career map was not a list of players")
            built = rosters_from(records, full_names)
            if built["placed"] < MIN_PLACED:
                raise FetchError(f"career map placed only {built['placed']} players on NBA teams")
            payload = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "source_id": SOURCE_ID, **built}
            target = out_dir / CACHE
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            return built["teams"], (f"rosters: {built['placed']} of {built['active']} active players "
                                    f"placed on NBA teams")
        except (FetchError, ValueError, OSError) as exc:
            reason = f"career map did not load ({exc})"
        except Exception as exc:          # a broken third-party file never fails the build
            reason = f"career map did not load ({type(exc).__name__}: {exc})"
    else:
        reason = "not fetched on this run"
    if cached:
        return cached["teams"], f"rosters: {reason}; kept the copy from {cached.get('fetched_at', 'an earlier run')}"
    return {}, f"rosters: {reason}; no earlier copy, so star power is left out"
