"""Player availability.

Source, found on 2026-09-24 by reading the page JavaScript of
hoopsmatic.com/depth-charts, which reads it as INJURIES_JSON_URL. It is a
keyless public JSON file, a flat list of
{"player", "status", "injury", "date"}. Statuses seen in the live file:
Available, Doubtful, Left Game, Out, Probable, Questionable.

The feed carries no team, so players are matched to a team through the NBA's
public player index:

  https://cdn.nba.com/static/json/staticData/playerIndex.json

verified on 2026-09-24: 597 rows with PLAYER_FIRST_NAME, PLAYER_LAST_NAME and
TEAM_ABBREVIATION.

Published JSON carries a short source id rather than this URL, because
generated output must never contain a Pages host name.

Set INJURY_FEED_URL to point this at a different feed with the same shape.
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Any

from .http import FetchError, get

DEFAULT_FEED_URL = "https://aderoa.github.io/Injuries/injuries.json"
SOURCE_ID = "hoopsmatic-depth-charts-injuries"

PLAYER_INDEX_URL = "https://cdn.nba.com/static/json/staticData/playerIndex.json"

# The five statuses this site publishes. Anything else is left out rather than
# translated into one of these.
ALLOWED_STATUSES = ("Out", "Doubtful", "Questionable", "Probable", "Available")
STATUS_ORDER = {s: i for i, s in enumerate(ALLOWED_STATUSES)}

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def feed_url() -> str:
    return os.environ.get("INJURY_FEED_URL") or DEFAULT_FEED_URL


def normalize_name(name: str) -> str:
    """Fold case, accents, punctuation and a trailing Jr/III so names line up."""
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z ]", " ", text).lower()
    parts = [p for p in text.split() if p and p not in _SUFFIXES]
    return " ".join(parts)


def normalize_status(raw: str) -> str | None:
    """Return one of the five published statuses, or None to skip the row."""
    value = (raw or "").strip().title()
    return value if value in ALLOWED_STATUSES else None


def fetch_player_teams() -> dict[str, str]:
    """Normalized player name to team tricode, current rosters only."""
    data = get(PLAYER_INDEX_URL, expect_json=True)
    result_sets = (data or {}).get("resultSets") or []
    if not result_sets:
        raise FetchError("player index held no resultSets")
    headers = result_sets[0].get("headers") or []
    rows = result_sets[0].get("rowSet") or []
    try:
        i_first = headers.index("PLAYER_FIRST_NAME")
        i_last = headers.index("PLAYER_LAST_NAME")
        i_team = headers.index("TEAM_ABBREVIATION")
    except ValueError as exc:
        raise FetchError(f"player index is missing a column: {exc}") from exc
    i_status = headers.index("ROSTER_STATUS") if "ROSTER_STATUS" in headers else None

    out: dict[str, str] = {}
    for row in rows:
        if i_status is not None and not row[i_status]:
            continue
        tricode = (row[i_team] or "").strip().upper()
        if not tricode:
            continue
        key = normalize_name(f"{row[i_first]} {row[i_last]}")
        if key:
            out[key] = tricode
    if not out:
        raise FetchError("player index produced no usable rows")
    return out


def fetch_raw() -> list[dict[str, Any]]:
    data = get(feed_url(), expect_json=True)
    if not isinstance(data, list):
        raise FetchError("injury feed was not a list of players")
    return data


def normalize(raw: list[dict[str, Any]], player_teams: dict[str, str]) -> dict[str, Any]:
    """Group the feed by team tricode, keeping only the five statuses."""
    by_team: dict[str, list[dict[str, str]]] = {}
    unmatched: list[str] = []
    skipped_status = 0

    for row in raw:
        if not isinstance(row, dict):
            continue
        name = (row.get("player") or "").strip()
        status = normalize_status(row.get("status") or "")
        if not name:
            continue
        if status is None:
            skipped_status += 1
            continue
        tricode = player_teams.get(normalize_name(name))
        if not tricode:
            unmatched.append(name)
            continue
        by_team.setdefault(tricode, []).append({
            "player": name,
            "status": status,
            "injury": (row.get("injury") or "").strip(),
        })

    for players in by_team.values():
        players.sort(key=lambda p: (STATUS_ORDER.get(p["status"], 99), p["player"]))

    return {
        "by_team": by_team,
        "unmatched": sorted(set(unmatched)),
        "skipped_status": skipped_status,
    }


def fetch() -> dict[str, Any]:
    return normalize(fetch_raw(), fetch_player_teams())
