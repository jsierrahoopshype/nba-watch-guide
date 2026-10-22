"""The "Storylines" block under a game: pre-game angles from the editorial bots.

The nba-editorial-bots Pre-Game Brief writes data/storylines.json every
game-day morning (one file, overwritten): {"date": "YYYY-MM-DD", "games":
{game_id: [{"text", "url", "kind"}, ...]}}. Built from the bots' full game
history (1954-55 on): all-time series, last playoff series, team streaks,
players far above their norm against this opponent, active player streaks
with their all-time rank, career milestones in reach, birthdays.

Every line links to its HoopsMatic page (Stat-Streaks player or team page,
Born & Died birthday page), printed underneath it. Lines that "Also worth
knowing" already covers (back-to-backs, revenge games, season series) are
left out by the bots. The block shows at most MAX_LINES, in the order the
file gives (strongest first), and only for games on the file's date.

The file changes once per game day, so the block is stable content (not
data-volatile): it moves a page's lastmod the day it appears, like any other
real content change.
"""

from __future__ import annotations

import json
from pathlib import Path

from .model import Game

MAX_LINES = 4
PATH = Path(__file__).resolve().parent.parent / "data" / "storylines.json"
ALLOWED_HOSTS = ("https://hoopsmatic.com/",)


def load(path: Path = PATH) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def lines(data: dict, game: Game) -> list[dict]:
    """[{"text", "url"}] for this game, or [] (wrong day, no file, no lines)."""
    if not data or data.get("date") != game.date_et:
        return []
    out = []
    for item in (data.get("games") or {}).get(str(game.game_id), [])[:MAX_LINES]:
        text = str(item.get("text", "")).strip()
        url = str(item.get("url", "")).strip()
        if not text:
            continue
        if url and not url.startswith(ALLOWED_HOSTS):
            url = ""      # only HoopsMatic pages, never another domain
        out.append({"text": text, "url": url})
    return out
