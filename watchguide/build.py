"""Turn the feeds and data files into the published tree.

Output layout, which the Worker maps onto /how-to-watch:

    index.html
    <team-slug>/index.html
    tonight/index.html
    assets/
    data/injuries.json, data/tonight.json, data/schedule.json
    sitemap.xml

data/schedule.json is the normalized schedule. The workflows restore it from
the last publish before a run, so a failed fetch falls back to the last good
data instead of publishing an empty site.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config, seo
from .context import SiteContext, load_context, today_et
from .coverage import channel_names, channels_for_game
from .model import Game
from .pages import BUILDERS
from .render import Page, build_env
from .sources import injuries as injuries_source
from .sources import schedule as schedule_source
from .sources.http import FetchError

SCHEDULE_CACHE = "data/schedule.json"
INJURIES_FILE = "data/injuries.json"
TONIGHT_FILE = "data/tonight.json"
SITEMAP_FILE = "sitemap.xml"


class BuildError(RuntimeError):
    """Something went wrong badly enough that the job must go red."""


# --------------------------------------------------------------------------
# Schedule, with a cache so one bad fetch does not empty the site
# --------------------------------------------------------------------------

def read_schedule_cache(path: Path) -> list[Game]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [Game.from_dict(g) for g in payload.get("games", [])]


def write_schedule_cache(path: Path, games: list[Game], season: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "season": season,
        "updated_at": datetime.now(config_tz()).isoformat(timespec="seconds"),
        "count": len(games),
        "games": [asdict(g) for g in games],
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def season_start(games: list[Game]) -> str:
    """First game date of the season. Anything the availability feed recorded
    before this belongs to a season that is over."""
    return min((g.date_et for g in games), default="")


def config_tz():
    from zoneinfo import ZoneInfo
    return ZoneInfo(config.EASTERN)


def load_schedule(out_dir: Path, allow_cache: bool = True) -> tuple[list[Game], str]:
    """(games, note). Falls back to the cache and reports what happened."""
    cache_path = out_dir / SCHEDULE_CACHE
    try:
        games = schedule_source.fetch()
        write_schedule_cache(cache_path, games, config.SEASON)
        return games, f"schedule: fetched {len(games)} regular-season games"
    except FetchError as exc:
        if not allow_cache:
            raise BuildError(str(exc)) from exc
        cached = read_schedule_cache(cache_path)
        if not cached:
            raise BuildError(f"{exc}; no cached schedule to fall back on") from exc
        return cached, f"schedule: fetch failed ({exc}); kept {len(cached)} cached games"


# --------------------------------------------------------------------------
# Injuries
# --------------------------------------------------------------------------

def read_injuries_file(path: Path) -> tuple[dict[str, list[dict[str, str]]], str, str]:
    """(by_team, updated_at, as_of) from a previously published file."""
    if not path.exists():
        return {}, "", ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, "", ""
    by_team: dict[str, list[dict[str, str]]] = {}
    for row in payload.get("players", []):
        by_team.setdefault(row.get("team", ""), []).append(
            {"player": row.get("player", ""), "status": row.get("status", ""),
             "injury": row.get("injury", ""), "date": row.get("date", "")})
    return by_team, payload.get("updated_at", ""), payload.get("as_of", "")


def load_injuries(out_dir: Path, since: str = "", allow_cache: bool = True) -> tuple[dict, str, str, str]:
    """(by_team, updated_at, as_of, note)."""
    path = out_dir / INJURIES_FILE
    try:
        result = injuries_source.fetch(since=since)
        updated = datetime.now(config_tz()).isoformat(timespec="seconds")
        note = (f"injuries: {sum(len(v) for v in result['by_team'].values())} players "
                f"across {len(result['by_team'])} teams, feed as of {result['as_of'] or 'unknown'}")
        if result["unmatched"]:
            note += f"; {len(result['unmatched'])} names had no current team"
        return result["by_team"], updated, result["as_of"], note
    except FetchError as exc:
        if not allow_cache:
            raise BuildError(str(exc)) from exc
        cached, updated, as_of = read_injuries_file(path)
        return cached, updated, as_of, f"injuries: fetch failed ({exc}); kept last good data"


# --------------------------------------------------------------------------
# Published JSON
# --------------------------------------------------------------------------

def _player_rows(ctx: SiteContext, tricodes: list[str]) -> list[dict[str, str]]:
    rows = []
    for tricode in tricodes:
        for player in ctx.players_for(tricode):
            rows.append({"player": player["player"], "status": player["status"],
                         "injury": player.get("injury", ""),
                         "date": player.get("date", ""), "team": tricode})
    return rows


def injuries_payload(ctx: SiteContext) -> dict[str, Any]:
    """Only teams playing today, as the brief requires."""
    today = ctx.games_today()
    playing = sorted({g.home_tricode for g in today} | {g.away_tricode for g in today})
    return {
        "updated_at": ctx.injuries_updated_at,
        "as_of": ctx.injuries_as_of,
        "source_id": injuries_source.SOURCE_ID,
        "date_et": ctx.today,
        "has_games_today": bool(today),
        "players": _player_rows(ctx, playing),
    }


def tonight_payload(ctx: SiteContext) -> dict[str, Any]:
    labels = ctx.labels()
    tba = labels.get("tba", "TBA")
    games = []
    for game in ctx.games_today():
        home = ctx.by_tricode.get(game.home_tricode)
        games.append({
            "game_id": game.game_id,
            "home": game.home_tricode,
            "away": game.away_tricode,
            "tipoff_utc": game.tipoff_utc,
            "tipoff_et": game.tipoff_et,
            "channels": channel_names(channels_for_game(
                game, game.home_tricode, ctx.local(home.slug) if home else None, tba)),
            "players": _player_rows(ctx, [game.away_tricode, game.home_tricode]),
        })
    return {
        "updated_at": ctx.injuries_updated_at,
        "as_of": ctx.injuries_as_of,
        "source_id": injuries_source.SOURCE_ID,
        "date_et": ctx.today,
        "has_games_today": bool(games),
        "games": games,
    }


# --------------------------------------------------------------------------
# Rendering and writing
# --------------------------------------------------------------------------

def render_pages(ctx: SiteContext, env=None) -> list[Page]:
    env = env or build_env()
    pages: list[Page] = []
    for builder in BUILDERS:
        pages.extend(builder(ctx, env))
    return pages


def write_pages(out_dir: Path, pages: list[Page]) -> None:
    for page in pages:
        target = out_dir / page.out_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page.html, encoding="utf-8")


def write_json(out_dir: Path, rel: str, payload: dict) -> None:
    target = out_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def write_sitemap(out_dir: Path, pages: list[Page]) -> None:
    entries = [(p.url, p.lastmod) for p in pages if p.in_sitemap]
    (out_dir / SITEMAP_FILE).write_text(seo.sitemap(entries), encoding="utf-8")


def copy_assets(out_dir: Path) -> None:
    target = out_dir / "assets"
    target.mkdir(parents=True, exist_ok=True)
    for item in config.ASSET_DIR.iterdir():
        if item.is_file():
            shutil.copy2(item, target / item.name)


def write_extras(out_dir: Path) -> None:
    """A no-index robots file and a .nojekyll so Pages serves the tree as is."""
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    (out_dir / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {config.public_url('sitemap.xml')}\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def full_build(out_dir: Path, today: str | None = None, offline: bool = False) -> list[str]:
    """Rebuild everything. Returns log lines. Raises BuildError on real failure."""
    notes: list[str] = []
    out_dir.mkdir(parents=True, exist_ok=True)

    if offline:
        games = read_schedule_cache(out_dir / SCHEDULE_CACHE)
        if not games:
            raise BuildError("offline build needs a cached data/schedule.json")
        notes.append(f"schedule: offline, {len(games)} cached games")
        injuries, updated_at, as_of = read_injuries_file(out_dir / INJURIES_FILE)
        notes.append("injuries: offline, using last published file")
    else:
        games, note = load_schedule(out_dir)
        notes.append(note)
        injuries, updated_at, as_of, inote = load_injuries(out_dir, since=season_start(games))
        notes.append(inote)

    ctx = load_context(games, injuries, updated_at, as_of, today=today)
    if len(ctx.teams) != 30:
        raise BuildError("expected 30 teams in data/teams.json")

    pages = render_pages(ctx)
    if len(pages) != 32:
        raise BuildError(f"expected 32 pages (hub, tonight, 30 teams), built {len(pages)}")

    write_pages(out_dir, pages)
    write_json(out_dir, INJURIES_FILE, injuries_payload(ctx))
    write_json(out_dir, TONIGHT_FILE, tonight_payload(ctx))
    write_sitemap(out_dir, pages)
    copy_assets(out_dir)
    write_extras(out_dir)
    notes.append(f"wrote {len(pages)} pages to {out_dir}")
    return notes


def refresh_build(out_dir: Path, today: str | None = None) -> list[str]:
    """Availability-only refresh: the data files, the tonight page and the team
    pages whose next game is today. Everything else on disk is left alone."""
    notes: list[str] = []
    games = read_schedule_cache(out_dir / SCHEDULE_CACHE)
    if not games:
        raise BuildError("refresh needs a published data/schedule.json; run a full build first")

    day = today or today_et()
    playing = {g.home_tricode for g in games if g.date_et == day} | \
              {g.away_tricode for g in games if g.date_et == day}
    if not playing:
        return ["no games today, nothing to refresh"]

    injuries, updated_at, as_of, inote = load_injuries(out_dir, since=season_start(games))
    notes.append(inote)

    ctx = load_context(games, injuries, updated_at, as_of, today=day)
    pages = render_pages(ctx)
    slugs_today = {ctx.by_tricode[t].slug for t in playing if t in ctx.by_tricode}
    wanted = [p for p in pages
              if p.out_path == "tonight/index.html" or p.meta.get("slug") in slugs_today]

    write_pages(out_dir, wanted)
    write_json(out_dir, INJURIES_FILE, injuries_payload(ctx))
    write_json(out_dir, TONIGHT_FILE, tonight_payload(ctx))
    write_sitemap(out_dir, pages)
    notes.append(f"refreshed {len(wanted)} pages for {len(playing)} teams playing on {day}")
    return notes
