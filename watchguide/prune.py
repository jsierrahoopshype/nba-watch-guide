"""Delete old content-hashed CSS and JS copies from the published tree.

Every build writes each stylesheet and script under a content-hashed name and
leaves earlier hashed copies in place, so HTML still cached somewhere keeps
finding the files it names. Without pruning they pile up on gh-pages forever.

A file's age cannot be read off gh-pages (the restore step's checkout gives
every file the same modification time), so data/asset-first-seen.json in the
published tree records the date each hashed copy was first seen by a publish.
A copy with no record yet is recorded as first seen today. On each publish,
a hashed CSS or JS copy is deleted once it was first seen more than
KEEP_DAYS days ago, unless it is current: named by any page in the tree, or
the hashed name of a file in the repo's assets/ now. Current copies are never
deleted, however old.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from . import config
from .render import hashed_asset_name

KEEP_DAYS = 7
RECORD = "data/asset-first-seen.json"
HASHED = re.compile(r"^(?P<stem>.+)\.(?P<hash>[0-9a-f]{10})\.(?P<ext>css|js)$")
REFERENCE = re.compile(r'/how-to-watch/(assets/[^"\'\s)?#]+)')


def _today() -> date:
    return datetime.now(timezone.utc).date()


def hashed_copies(site: Path) -> list[str]:
    """Paths (relative to the tree) of every hashed CSS and JS copy."""
    assets = site / "assets"
    if not assets.is_dir():
        return []
    return sorted(p.relative_to(site).as_posix() for p in assets.rglob("*")
                  if p.is_file() and HASHED.match(p.name))


def current(site: Path, asset_dir: Path | None = None) -> set[str]:
    """Copies that must stay: named by any page, or the hashed name of a
    file in the repo's assets/ as it is now."""
    keep: set[str] = set()
    for page in site.rglob("*.html"):
        keep.update(REFERENCE.findall(page.read_text(encoding="utf-8", errors="ignore")))
    source = asset_dir or config.ASSET_DIR
    for item in source.rglob("*"):
        if item.is_file() and item.suffix in (".css", ".js"):
            rel = item.relative_to(source).as_posix()
            keep.add(f"assets/{hashed_asset_name(rel, source)}")
    return keep


def prune(site: Path, today: date | None = None, keep_days: int = KEEP_DAYS,
          asset_dir: Path | None = None) -> list[str]:
    """Delete stale hashed copies; return what was deleted."""
    today = today or _today()
    record_path = site / RECORD
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            record = {}
    except (OSError, ValueError):
        record = {}

    keep = current(site, asset_dir)
    deleted: list[str] = []
    new_record: dict[str, str] = {}
    for rel in hashed_copies(site):
        try:
            first = date.fromisoformat(record.get(rel, ""))
        except ValueError:
            first = today                           # never recorded: its clock starts now
        if rel not in keep and (today - first).days > keep_days:
            (site / rel).unlink()
            deleted.append(rel)
            continue
        new_record[rel] = first.isoformat()
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(new_record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return deleted
