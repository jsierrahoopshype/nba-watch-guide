"""Guards on the availability feed.

The upstream file is a change log someone else maintains. Two things can go
wrong quietly: it can fail to load, and it can come back much shorter than it
was, which would silently wipe statuses off the pages. Both are caught here.

The raw response is kept in the repo at data/injuries-raw-latest.json so there
is always a copy to compare against and to fall back on, and so a bad upstream
day can be reconstructed afterwards.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# A drop larger than this against the last good copy is treated as the feed
# breaking rather than as players getting healthy.
MAX_SHRINK = 0.50

RAW_FILE = "data/injuries-raw-latest.json"


class FeedGuardError(RuntimeError):
    """The feed looks broken. Keep the last good copy and fail the job."""


@dataclass
class RawSnapshot:
    rows: list[dict[str, Any]]
    fetched_at: str
    source_id: str

    @property
    def count(self) -> int:
        return len(self.rows)

    def to_json(self) -> str:
        return json.dumps({
            "_note": "Raw upstream availability feed, saved on every refresh so there "
                     "is always a copy to fall back on and to compare the next fetch "
                     "against. Not served to readers.",
            "fetched_at": self.fetched_at,
            "source_id": self.source_id,
            "row_count": self.count,
            "rows": self.rows,
        }, ensure_ascii=False, indent=1)


def read_raw(path: Path) -> RawSnapshot | None:
    """The last good copy, or None when there is not one yet."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return None
    return RawSnapshot(rows=rows,
                       fetched_at=payload.get("fetched_at", ""),
                       source_id=payload.get("source_id", ""))


def write_raw(path: Path, snapshot: RawSnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(snapshot.to_json(), encoding="utf-8")


def check_shrink(new_count: int, previous: RawSnapshot | None) -> str:
    """Return a complaint when the feed shrank too far, or '' when it is fine.

    A first run has nothing to compare against, and a previously empty file
    cannot shrink, so both pass.
    """
    if previous is None or previous.count == 0:
        return ""
    if new_count >= previous.count * (1.0 - MAX_SHRINK):
        return ""
    drop = 100.0 * (previous.count - new_count) / previous.count
    return (f"availability feed returned {new_count} rows against "
            f"{previous.count} last time, a drop of {drop:.0f}%. "
            f"Anything over {MAX_SHRINK * 100:.0f}% is treated as the feed "
            "breaking, so the last good copy has been kept.")


def snapshot_now(rows: list[dict[str, Any]], source_id: str) -> RawSnapshot:
    return RawSnapshot(rows=rows,
                       fetched_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                       source_id=source_id)
