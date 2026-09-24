"""Command line entry point.

    python -m watchguide build   --out site
    python -m watchguide refresh --out site
    python -m watchguide games-today --out site
    python -m watchguide verify
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config
from .build import (BuildError, full_build, read_schedule_cache, refresh_build)
from .context import today_et


def _out(args) -> Path:
    return Path(args.out).resolve()


# Exit 3 means the pages were written and can be published, but the run had to
# fall back on old availability data. The workflow publishes, then goes red.
DEGRADED_EXIT = 3


def _report(outcome) -> int:
    for line in outcome.notes:
        print(line)
    if outcome.degraded:
        print(f"::warning::{outcome.degraded}")
        print(outcome.degraded, file=sys.stderr)
        return DEGRADED_EXIT
    return 0


def cmd_build(args) -> int:
    return _report(full_build(_out(args), today=args.today, offline=args.offline))


def cmd_refresh(args) -> int:
    return _report(refresh_build(_out(args), today=args.today))


def cmd_games_today(args) -> int:
    """Exit 0 when there are games today, 1 when there are none.

    The refresh workflow calls this first so it stops within seconds on a
    quiet day instead of fetching anything.
    """
    day = args.today or today_et()
    games = read_schedule_cache(_out(args) / "data/schedule.json")
    count = sum(1 for g in games if g.date_et == day)
    print(f"{day}: {count} games")
    return 0 if count else 1


def cmd_verify(args) -> int:
    """Hit the live feeds and print what came back. Useful on its own."""
    from .build import broadcast_report, broadcast_summary
    from .context import today_et
    from .sources import injuries as injuries_source
    from .sources import schedule as schedule_source

    ok = True
    try:
        games = schedule_source.fetch()
        print(f"schedule OK: {len(games)} regular-season games for {config.SEASON}")
        print(f"  first {games[0].date_et}, last {games[-1].date_et}")
        print("  " + broadcast_summary(broadcast_report(games, today_et())))
    except Exception as exc:
        ok = False
        print(f"schedule FAILED: {exc}")
    try:
        result = injuries_source.fetch()
        total = sum(len(v) for v in result["by_team"].values())
        print(f"injuries OK: {total} players across {len(result['by_team'])} teams")
        if result["unmatched"]:
            print(f"  {len(result['unmatched'])} names had no current team")
    except Exception as exc:
        ok = False
        print(f"injuries FAILED: {exc}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="watchguide")
    parser.add_argument("--out", default=str(config.DEFAULT_OUT_DIR),
                        help="publish root (default: ./site)")
    parser.add_argument("--today", default=None, help="override today's Eastern date, YYYY-MM-DD")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="rebuild every page")
    build.add_argument("--offline", action="store_true",
                       help="use the published data files, make no network calls")
    build.set_defaults(func=cmd_build)

    sub.add_parser("refresh", help="refresh availability and the pages it touches").set_defaults(func=cmd_refresh)
    sub.add_parser("games-today", help="exit 0 if there are games today").set_defaults(func=cmd_games_today)
    sub.add_parser("verify", help="check the live feeds").set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BuildError as exc:
        print(f"build failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
