"""Player headshots for the hub's game cards, copied into the published tree.

Source: jsierrahoopshype/nba-headshots.
  players/metadata/players_all.json lists every player with a headshot
  record whose "filename" is "<nba_id>-<slug>.png"; the same stem under
  players/headshots/face2-160/ is the 160x160 WebP the pages use.

Nothing on a page loads from that repo. The build downloads the faces it
needs into assets/faces/ in the published tree, which the restore step
brings back on every run, so each face is fetched once. A player with no
headshot, or one that fails to download, gets the silhouette instead.
Set HEADSHOTS_BASE to read a different copy of the repo.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .careers import match_key
from .http import FetchError, get

DEFAULT_BASE = "https://raw.githubusercontent.com/jsierrahoopshype/nba-headshots/main"
INDEX_PATH = "players/metadata/players_all.json"
FACE_DIR = "players/headshots/face2-160"
INDEX_CACHE = "data/headshots-index.json"
FACES = "assets/faces"
MIN_INDEX = 300          # fewer entries than this is treated as a broken index


def base_url() -> str:
    return (os.environ.get("HEADSHOTS_BASE") or DEFAULT_BASE).rstrip("/")


def index_from(payload: Any) -> dict[str, str]:
    """{match_key(name): file stem} for every player whose record has a face."""
    players = payload.get("players", []) if isinstance(payload, dict) else []
    out: dict[str, str] = {}
    for p in players:
        shot = p.get("headshot") or {}
        filename = shot.get("filename") or ""
        if not (shot.get("face") and filename and p.get("full_name")):
            continue
        out.setdefault(match_key(p["full_name"]), filename.rsplit(".", 1)[0])
    return out


def load_index(out_dir: Path, allow_fetch: bool = True) -> tuple[dict[str, str], str]:
    """(index, note). Never raises: falls back to the last copy, then to {}."""
    cache = out_dir / INDEX_CACHE
    reason = "not fetched on this run"
    if allow_fetch:
        try:
            built = index_from(get(f"{base_url()}/{INDEX_PATH}", expect_json=True))
            if len(built) < MIN_INDEX:
                raise FetchError(f"headshot index has only {len(built)} faces")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                         "faces": built}), encoding="utf-8")
            return built, f"headshots: index of {len(built)} faces"
        except Exception as exc:                 # a broken third-party file never fails the build
            reason = f"index did not load ({type(exc).__name__}: {exc})"
    try:
        faces = json.loads(cache.read_text(encoding="utf-8")).get("faces") or {}
        return faces, f"headshots: {reason}; kept the last index ({len(faces)} faces)"
    except (OSError, ValueError, AttributeError):
        return {}, f"headshots: {reason}; no index, silhouettes only"


def ensure_faces(out_dir: Path, names: Iterable[str], index: dict[str, str],
                 allow_fetch: bool = True) -> tuple[dict[str, str], str]:
    """({match_key(name): 'assets/faces/<stem>.webp'}, note) for the names
    whose face is on disk after this call. Downloads only what is missing."""
    found: dict[str, str] = {}
    fetched = failed = 0
    for name in names:
        key = match_key(name or "")
        stem = index.get(key)
        if not key or not stem or key in found:
            continue
        rel = f"{FACES}/{stem}.webp"
        target = out_dir / rel
        if not target.is_file() and allow_fetch:
            try:
                data = get(f"{base_url()}/{FACE_DIR}/{stem}.webp")
                if not isinstance(data, (bytes, bytearray)) or data[:4] != b"RIFF":
                    raise FetchError("not a WebP file")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                fetched += 1
            except Exception:
                failed += 1
        if target.is_file():
            found[key] = rel
    note = f"headshots: {len(found)} faces on the hub, {fetched} downloaded"
    if failed:
        note += f", {failed} failed (silhouette shown)"
    return found, note
