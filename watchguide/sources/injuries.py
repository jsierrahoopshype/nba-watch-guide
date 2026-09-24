"""Player availability.

Source, found on 2026-09-24 by reading the page JavaScript of
hoopsmatic.com/depth-charts, which reads it as INJURIES_JSON_URL. It is a
keyless public JSON file.

The file is a change log, not a snapshot: one row per status change, shaped
{"player", "status", "injury", "date", "prevStatus"}. Checked on 2026-09-24 it
held 4906 rows going back over past seasons, so a player's current status is
the latest row carrying their name. Rows dated before the season started are
dropped, otherwise a player left Out at the end of one season would still read
as Out at the start of the next.

Statuses seen in the live file: Available, Doubtful, Left Game, Out, Probable,
Questionable.

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


def latest_per_player(raw: list[dict[str, Any]], since: str = "") -> dict[str, dict[str, Any]]:
    """The most recent row for each player, ignoring anything before `since`."""
    latest: dict[str, dict[str, Any]] = {}
    for row in raw:
        if not isinstance(row, dict):
            continue
        name = (row.get("player") or "").strip()
        if not name:
            continue
        when = (row.get("date") or "")[:10]
        if since and when < since:
            continue
        key = normalize_name(name)
        if not key:
            continue
        current = latest.get(key)
        if current is None or when >= (current.get("date") or "")[:10]:
            latest[key] = row
    return latest


def normalize(raw: list[dict[str, Any]], player_teams: dict[str, str],
              since: str = "") -> dict[str, Any]:
    """Current status per player, grouped by team tricode.

    `since` is normally the first game date of the season, so last season's
    entries never carry over.
    """
    by_team: dict[str, list[dict[str, str]]] = {}
    unmatched: list[str] = []
    skipped_status = 0
    as_of = ""

    for key, row in latest_per_player(raw, since).items():
        name = (row.get("player") or "").strip()
        status = normalize_status(row.get("status") or "")
        if status is None:
            skipped_status += 1
            continue
        tricode = player_teams.get(key)
        if not tricode:
            unmatched.append(name)
            continue
        when = (row.get("date") or "")[:10]
        as_of = max(as_of, when)
        by_team.setdefault(tricode, []).append({
            "player": name,
            "status": status,
            "injury": (row.get("injury") or "").strip(),
            "date": when,
        })

    for players in by_team.values():
        players.sort(key=lambda p: (STATUS_ORDER.get(p["status"], 99), p["player"]))

    return {
        "by_team": by_team,
        "as_of": as_of,
        "unmatched": sorted(set(unmatched)),
        "skipped_status": skipped_status,
    }


def fetch(since: str = "") -> dict[str, Any]:
    return normalize(fetch_raw(), fetch_player_teams(), since=since)
