"""Paths, constants and the one place the public site base lives."""

from __future__ import annotations

import os
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

# Regular-season games have game ids starting 002. 001 preseason, 003 all-star,
# 004 playoffs, 005 play-in.
REGULAR_SEASON_PREFIX = "002"

# Data is considered stale after this many minutes during the evening window.
STALE_MINUTES = 90
STALE_WINDOW_START_HOUR = 12  # 12:00 ET
STALE_WINDOW_END_HOUR = 1     # 01:00 ET next day


def public_url(path: str = "") -> str:
    """Absolute public URL. No trailing slash, ever."""
    path = path.strip("/")
    return SITE_BASE if not path else f"{SITE_BASE}/{path}"


def site_path(path: str = "") -> str:
    """Root-relative path used for internal links and assets."""
    path = path.strip("/")
    return PATH_PREFIX if not path else f"{PATH_PREFIX}/{path}"
