"""Paths, constants and the one place the public site base lives."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Rule: every canonical, og:url, JSON-LD url and sitemap entry uses this base.
# Nothing else may build a public URL. Never point this at a github.io host.
SITE_BASE = "https://hoopsmatic.com/how-to-watch"

# Root-relative prefix for internal links and assets. The Cloudflare Worker
# serves the gh-pages root at this path.
PATH_PREFIX = "/how-to-watch"

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
TEMPLATE_DIR = REPO_ROOT / "templates"
ASSET_DIR = REPO_ROOT / "assets"
DEFAULT_OUT_DIR = REPO_ROOT / "site"

EASTERN = "America/New_York"

# Season the generator expects in the schedule feed. Bump this each summer.
SEASON = os.environ.get("WATCH_GUIDE_SEASON", "2026-27")

# Service id in data/services.json that the League Pass blackout rules apply to,
# used when the rules block does not name one itself.
LEAGUE_PASS_SERVICE_ID = "nba_league_pass"

# National codes whose games the team's local broadcaster also carries when
# the feed lists that team's own local code on the game. In the 2026-27 feed
# every NBA TV game for a team with local codes also carries that team's local
# broadcaster; other national partners are not treated this way.
LOCAL_SIMULCAST_NATIONAL_CODES = ("NBA TV",)

# Tonight's ranking: players listed with these statuses do not count toward
# star power. Every scoring number is in data/star_power_weights.json.
RANK_UNAVAILABLE_STATUSES = ("Out", "Doubtful")

# Regular-season games have game ids starting 002. 001 preseason, 003 all-star,
# 004 playoffs, 005 play-in.
REGULAR_SEASON_PREFIX = "002"

# Data is considered stale after this many minutes during the evening window.
STALE_MINUTES = 90
STALE_WINDOW_START_HOUR = 12  # 12:00 ET
STALE_WINDOW_END_HOUR = 1     # 01:00 ET next day


# From this hour ET until midnight on a game day, a day with no injury
# listing for any team playing and no report dated today reads "Injury report
# not available yet" (see SiteContext.injury_report_missing).
INJURY_GUARD_START_HOUR = 15


def build_id() -> str:
    """The short commit this build ran from, for the <meta name="build">
    marker the live check compares: WATCH_GUIDE_BUILD, else the Actions
    GITHUB_SHA, else the checkout's HEAD; "local" when none is known."""
    sha = os.environ.get("WATCH_GUIDE_BUILD") or os.environ.get("GITHUB_SHA") or ""
    if not sha:
        try:
            sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True,
                                 text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            sha = ""
    return sha[:7] or "local"


def public_url(path: str = "") -> str:
    """Absolute public URL. No trailing slash, ever."""
    path = path.strip("/")
    return SITE_BASE if not path else f"{SITE_BASE}/{path}"


def site_path(path: str = "") -> str:
    """Root-relative path used for internal links and assets."""
    path = path.strip("/")
    return PATH_PREFIX if not path else f"{PATH_PREFIX}/{path}"
