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
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import config, seo
from .context import SiteContext, load_context, today_et
from .coverage import channel_names, channels_for_game
from .model import Game
from .pages import BUILDERS
from .pages.links_block import render as render_links_block
from .render import Page, build_env
from .sources import injuries as injuries_source
from .sources import schedule as schedule_source
from .guard import RAW_FILE, FeedGuardError, check_shrink, read_raw, snapshot_now, write_raw
from .sources.http import FetchError

SCHEDULE_CACHE = "data/schedule.json"
BROADCAST_REPORT = "data/broadcast-coverage.json"
LINKS_FILE = "data/how-to-watch-links.html"
INJURIES_FILE = "data/injuries.json"
TONIGHT_FILE = "data/tonight.json"
SITEMAP_FILE = "sitemap.xml"


class BuildError(RuntimeError):
    """Something went wrong badly enough that nothing should be published."""


@dataclass
class BuildOutcome:
    """What a build produced, and whether it had to fall back on old data.

    `degraded` is empty on a healthy run. When it is set the pages were still
    written, from the last good data and carrying the out-of-date notice, and
    the caller makes the job go red. Publishing a stale-but-marked page beats
    publishing nothing.
    """
    notes: list[str]
    degraded: str = ""

    def __iter__(self):
        """So `for line in full_build(...)` keeps working."""
        return iter(self.notes)


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


# Training camp and pre-season sit-outs matter in the days before opening
# night, so the availability cut-off reaches back a month from the first
# regular-season game. The previous season ended months earlier, so nothing
# from it slips through.
AVAILABILITY_LOOKBACK_DAYS = 30


def broadcast_report(games: list[Game], today: str) -> dict[str, Any]:
    """How much of the season has a broadcaster yet.

    The league publishes national assignments in waves, so this is written on
    every build and printed in the job log. Watching national_tv climb is how
    we see the day the rest of the season gets filled in.
    """
    national: Counter[str] = Counter()
    local: Counter[str] = Counter()
    with_national = with_local = with_nothing = 0
    for game in games:
        if game.national_codes:
            with_national += 1
        for code in game.national_codes:
            national[code] += 1
        side_codes = list(game.home_tv) + list(game.away_tv)
        if side_codes:
            with_local += 1
        for code in side_codes:
            local[code] += 1
        if not game.national_codes and not side_codes:
            with_nothing += 1
    return {
        "generated_at": today,
        "source_url": schedule_source.SCHEDULE_URL,
        "season": config.SEASON,
        "regular_season_games": len(games),
        "games_with_national_tv": with_national,
        "games_with_local_tv": with_local,
        "games_with_no_broadcaster": with_nothing,
        "national_codes": dict(national.most_common()),
        "local_codes": dict(local.most_common()),
    }


def broadcast_summary(report: dict[str, Any]) -> str:
    total = report["regular_season_games"] or 1
    pct = 100.0 * report["games_with_national_tv"] / total
    codes = ", ".join(f"{k} {v}" for k, v in report["national_codes"].items()) or "none"
    return (f"broadcasters: {report['games_with_national_tv']} of "
            f"{report['regular_season_games']} games have national TV ({pct:.1f}%), "
            f"{report['games_with_local_tv']} have local TV, "
            f"{report['games_with_no_broadcaster']} have none. National codes: {codes}")


def season_start(games: list[Game]) -> str:
    """The earliest date the availability feed may be read from."""
    first = min((g.date_et for g in games), default="")
    if not first:
        return ""
    return (date.fromisoformat(first) - timedelta(days=AVAILABILITY_LOOKBACK_DAYS)).isoformat()


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


def load_injuries(out_dir: Path, repo_root: Path | None = None, since: str = "",
                  allow_cache: bool = True) -> tuple[dict, str, str, str, str]:
    """(by_team, updated_at, as_of, note, complaint).

    complaint is empty on a healthy run. When it is set, the last good data has
    been kept and the caller must make the job go red, so a broken feed is never
    published quietly.
    """
    path = out_dir / INJURIES_FILE
    raw_path = (repo_root or config.REPO_ROOT) / RAW_FILE
    previous = read_raw(raw_path)

    def fall_back(reason: str) -> tuple[dict, str, str, str, str]:
        """Rebuild from the last raw copy when there is one, else from the last
        published file. Either way nothing new is written over the good copy."""
        if previous is not None and previous.rows:
            try:
                result = injuries_source.normalize(
                    previous.rows, injuries_source.fetch_player_teams(), since=since)
                return (result["by_team"], previous.fetched_at, result["as_of"],
                        f"injuries: kept the last good raw copy ({previous.count} rows)", reason)
            except FetchError:
                pass
        cached, updated, as_of = read_injuries_file(path)
        return cached, updated, as_of, "injuries: kept the last published file", reason

    try:
        rows = injuries_source.fetch_raw()
    except FetchError as exc:
        if not allow_cache:
            raise BuildError(str(exc)) from exc
        return fall_back(f"availability feed did not load: {exc}")

    complaint = check_shrink(len(rows), previous)
    if complaint:
        return fall_back(complaint)

    try:
        result = injuries_source.normalize(rows, injuries_source.fetch_player_teams(), since=since)
    except FetchError as exc:
        if not allow_cache:
            raise BuildError(str(exc)) from exc
        return fall_back(f"could not match players to teams: {exc}")

    # Only a clean fetch replaces the raw copy, so the comparison baseline and
    # the fallback never become the broken version.
    write_raw(raw_path, snapshot_now(rows, injuries_source.SOURCE_ID))

    updated = datetime.now(config_tz()).isoformat(timespec="seconds")
    players = sum(len(v) for v in result["by_team"].values())
    note = (f"injuries: {len(rows)} raw rows, {players} players across "
            f"{len(result['by_team'])} teams, feed as of {result['as_of'] or 'unknown'}")
    if result["unmatched"]:
        note += f"; {len(result['unmatched'])} names had no current team"
    if not players:
        note += "; no player has an entry for this season yet"
    return result["by_team"], updated, result["as_of"], note, ""


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
    # Every page type picks this up, including ones added later, so a new
    # builder cannot forget the robots tag.
    env.globals["noindex"] = ctx.noindex
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


def write_sitemap(out_dir: Path, pages: list[Page], noindex: bool = False) -> None:
    """The file is always written. While noindex is on it lists nothing, so a
    stale sitemap cannot keep pointing crawlers at pages we asked them to skip."""
    entries = [] if noindex else [(p.url, p.lastmod) for p in pages if p.in_sitemap]
    (out_dir / SITEMAP_FILE).write_text(seo.sitemap(entries), encoding="utf-8")


def write_links_block(out_dir: Path, ctx: SiteContext) -> None:
    """A bare HTML block of links to the hub and all 30 team pages.

    Meant to be pasted into the Worker on a page that is already crawled, so
    the guide has an internal path in. Absolute URLs, class names only, no
    styling, no scripts.
    """
    (out_dir / LINKS_FILE).parent.mkdir(parents=True, exist_ok=True)
    (out_dir / LINKS_FILE).write_text(render_links_block(ctx), encoding="utf-8")


def copy_assets(out_dir: Path) -> None:
    target = out_dir / "assets"
    target.mkdir(parents=True, exist_ok=True)
    for item in config.ASSET_DIR.iterdir():
        if item.is_file():
            shutil.copy2(item, target / item.name)


def write_extras(out_dir: Path, noindex: bool = False) -> None:
    """A .nojekyll so Pages serves the tree as is, plus robots.txt."""
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    lines = ["User-agent: *", "Allow: /"]
    if not noindex:
        lines.append(f"Sitemap: {config.public_url('sitemap.xml')}")
    (out_dir / "robots.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def full_build(out_dir: Path, today: str | None = None, offline: bool = False,
               data_dir: Path | None = None, repo_root: Path | None = None) -> BuildOutcome:
    """Rebuild everything. Raises BuildError when nothing should be published."""
    notes: list[str] = []
    complaint = ""
    out_dir.mkdir(parents=True, exist_ok=True)

    if offline:
        games = read_schedule_cache(out_dir / SCHEDULE_CACHE)
        if not games:
            raise BuildError("offline build needs a cached data/schedule.json")
        notes.append(f"schedule: offline, {len(games)} cached games")
        injuries, updated_at, as_of = read_injuries_file(out_dir / INJURIES_FILE)
        notes.append("injuries: offline, using last published file")
        complaint = ""
    else:
        games, note = load_schedule(out_dir)
        notes.append(note)
        injuries, updated_at, as_of, inote, complaint = load_injuries(
            out_dir, repo_root=repo_root, since=season_start(games))
        notes.append(inote)

    if complaint:
        notes.append(f"WARNING {complaint}")

    ctx = load_context(games, injuries, updated_at, as_of, availability_degraded=complaint,
                       data_dir=data_dir, today=today)
    if len(ctx.teams) != 30:
        raise BuildError("expected 30 teams in data/teams.json")

    pages = render_pages(ctx)
    if len(pages) != 32:
        raise BuildError(f"expected 32 pages (hub, tonight, 30 teams), built {len(pages)}")

    report = broadcast_report(games, ctx.today)
    notes.append(broadcast_summary(report))

    write_pages(out_dir, pages)
    write_json(out_dir, BROADCAST_REPORT, report)
    write_json(out_dir, INJURIES_FILE, injuries_payload(ctx))
    write_json(out_dir, TONIGHT_FILE, tonight_payload(ctx))
    write_sitemap(out_dir, pages, noindex=ctx.noindex)
    copy_assets(out_dir)
    write_extras(out_dir, noindex=ctx.noindex)
    write_links_block(out_dir, ctx)
    notes.append(f"wrote {len(pages)} pages to {out_dir}")
    return BuildOutcome(notes=notes, degraded=complaint)


def refresh_build(out_dir: Path, today: str | None = None,
                  repo_root: Path | None = None) -> BuildOutcome:
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
        return BuildOutcome(notes=["no games today, nothing to refresh"])

    injuries, updated_at, as_of, inote, complaint = load_injuries(
        out_dir, repo_root=repo_root, since=season_start(games))
    notes.append(inote)
    if complaint:
        notes.append(f"WARNING {complaint}")

    ctx = load_context(games, injuries, updated_at, as_of,
                       availability_degraded=complaint, today=day)
    pages = render_pages(ctx)
    slugs_today = {ctx.by_tricode[t].slug for t in playing if t in ctx.by_tricode}
    wanted = [p for p in pages
              if p.out_path == "tonight/index.html" or p.meta.get("slug") in slugs_today]

    write_pages(out_dir, wanted)
    write_json(out_dir, INJURIES_FILE, injuries_payload(ctx))
    write_json(out_dir, TONIGHT_FILE, tonight_payload(ctx))
    write_sitemap(out_dir, pages, noindex=ctx.noindex)
    notes.append(f"refreshed {len(wanted)} pages for {len(playing)} teams playing on {day}")
    return BuildOutcome(notes=notes, degraded=complaint)
