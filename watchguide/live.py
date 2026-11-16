"""data/live-base.json: what the how-to-watch-live Worker needs between builds.

The Worker (worker/, a separate Cloudflare Worker on the route
hoopsmatic.com/how-to-watch/live/*) refreshes availability every 30 minutes
on game evenings. It has no token and calls nothing at the NBA: everything
that is not the public availability feed comes from this file, which every
full build publishes next to the pages:

- player_teams: the NBA player index, folded the same way as
  injuries.normalize_name (cdn.nba.com refuses plain server requests, so the
  Worker never asks it);
- aliases: data/player_aliases.json, folded on both sides;
- since: the earliest feed date that counts (build.season_start);
- games: the next few days of games with the fields tonight.json carries,
  channels included, so the Worker's tonight.json matches the build's;
- raw_count: rows in the last good raw copy, the Worker's first baseline for
  the shrink guard (guard.MAX_SHRINK).

The file is only written when this build fetched the player index; otherwise
the copy restored from the last publish stays, as with every other data file.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import config
from .coverage import channel_names, channels_for_game
from .guard import MAX_SHRINK
from .sources import injuries as injuries_source

LIVE_BASE_FILE = "data/live-base.json"
# Enough days that a missed morning build still leaves the Worker today's games.
DAYS_AHEAD = 4


def live_base_payload(ctx, player_teams: dict[str, str], since: str, raw_count: int) -> dict[str, Any]:
    labels = ctx.labels()
    tba = labels.get("tba", "TBA")
    try:
        last = (date.fromisoformat(ctx.today) + timedelta(days=DAYS_AHEAD)).isoformat()
    except ValueError:
        last = ""
    games = []
    for game in ctx.games:
        if game.date_et < ctx.today or (last and game.date_et > last):
            continue
        home = ctx.by_tricode.get(game.home_tricode)
        games.append({
            "date_et": game.date_et,
            "game_id": game.game_id,
            "home": game.home_tricode,
            "away": game.away_tricode,
            "tipoff_utc": game.tipoff_utc,
            "tipoff_et": game.tipoff_et,
            "channels": channel_names(channels_for_game(
                game, game.home_tricode, ctx.local(home.slug) if home else None, tba)),
        })
    return {
        "_note": "Input for the how-to-watch-live Worker (worker/). Written by every full build.",
        "built_for": ctx.today,
        "source_id": injuries_source.SOURCE_ID,
        "since": since,
        "eastern": config.EASTERN,
        "max_shrink": MAX_SHRINK,
        "raw_count": raw_count,
        "aliases": injuries_source.folded_aliases(),
        "player_teams": dict(sorted(player_teams.items())),
        "games": games,
    }
