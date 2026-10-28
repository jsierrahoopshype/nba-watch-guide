"""Player headshots for the hub's game cards, copied into the published tree.

Source: jsierrahoopshype/nba-headshots.
  players/metadata/players_all.json lists every player with a headshot
  record whose "filename" is "<nba_id>-<slug>.png"; players/headshots/
  face-fill/<nba_id>-<slug>.webp is the one HoopsMatic headshot look (Oct
  2026): a 160x160 transparent WebP whose face fills the circle, chin
  inside, no neck or jersey line. face-fill/.hashes.json lists the players
  that have one. The file is saved as it comes and sits on the page's own
  light grey circle. (Before: face/ cutouts shrunk here, and before that
  face2-160 with a dark baked-in background.)

Nothing on a page loads from that repo. The build downloads the faces it
needs into assets/faces/ in the published tree, which the restore step
brings back on every run, so each face is fetched once. A player with no
face-fill file, or one that fails to download, gets his initials instead.
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
FACE_DIR = "players/headshots/face-fill"
FILL_LIST = f"{FACE_DIR}/.hashes.json"   # {"files": {stem: ...}}: who has a face-fill file
INDEX_CACHE = "data/headshots-index.json"
FACES = "assets/faces"
# Which source each file in assets/faces came from, kept per file in
# assets/faces/sources.json. The published tree keeps faces between runs, so
# a file without the current mark is fetched again the next time a page
# needs it (same file name, so no page HTML changes). An offline run keeps
# the old file rather than dropping to initials; an online run whose fetch
# fails drops a file without the current mark (initials, never the old look).
SOURCE_MARK = "face-fill-160-v1"
SOURCE_FILE = "sources.json"
MIN_INDEX = 300          # fewer entries than this is treated as a broken index


def base_url() -> str:
    return (os.environ.get("HEADSHOTS_BASE") or DEFAULT_BASE).rstrip("/")


def index_from(payload: Any, fill: Any = None) -> dict[str, str]:
    """{match_key(name): file stem} for every player whose record has a face
    and, when the face-fill list is given, a face-fill file."""
    players = payload.get("players", []) if isinstance(payload, dict) else []
    have = None
    if fill is not None:
        have = set((fill.get("files") or {}) if isinstance(fill, dict) else ())
    out: dict[str, str] = {}
    for p in players:
        shot = p.get("headshot") or {}
        filename = shot.get("filename") or ""
        if not (shot.get("face") and filename and p.get("full_name")):
            continue
        stem = filename.rsplit(".", 1)[0]
        if have is not None and stem not in have:
            continue
        out.setdefault(match_key(p["full_name"]), stem)
    return out


def load_index(out_dir: Path, allow_fetch: bool = True) -> tuple[dict[str, str], str]:
    """(index, note). Never raises: falls back to the last copy, then to {}."""
    cache = out_dir / INDEX_CACHE
    reason = "not fetched on this run"
    if allow_fetch:
        try:
            built = index_from(get(f"{base_url()}/{INDEX_PATH}", expect_json=True),
                               get(f"{base_url()}/{FILL_LIST}", expect_json=True))
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
        return {}, f"headshots: {reason}; no index, initials only"


def is_webp(data: Any) -> bool:
    return isinstance(data, (bytes, bytearray)) and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def ensure_faces(out_dir: Path, names: Iterable[str], index: dict[str, str],
                 allow_fetch: bool = True) -> tuple[dict[str, str], str]:
    """({match_key(name): 'assets/faces/<stem>.webp'}, note) for the names
    whose face is on disk after this call. Downloads only what is missing,
    or one not yet taken from the current source (SOURCE_MARK)."""
    found: dict[str, str] = {}
    fetched = failed = 0
    mark_path = out_dir / FACES / SOURCE_FILE
    try:
        marks = json.loads(mark_path.read_text(encoding="utf-8"))
        if not isinstance(marks, dict):
            marks = {}
    except (OSError, ValueError):
        marks = {}
    changed = False
    for name in names:
        key = match_key(name or "")
        stem = index.get(key)
        if not key or not stem or key in found:
            continue
        rel = f"{FACES}/{stem}.webp"
        target = out_dir / rel
        need = not target.is_file() or marks.get(stem) != SOURCE_MARK
        if need and allow_fetch:
            try:
                data = get(f"{base_url()}/{FACE_DIR}/{stem}.webp")
                if not is_webp(data):
                    raise FetchError("not a WebP file")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bytes(data))
                marks[stem] = SOURCE_MARK
                changed = True
                fetched += 1
            except Exception:
                failed += 1
                if marks.get(stem) != SOURCE_MARK:     # an old-look file: initials instead
                    continue
        if target.is_file():
            found[key] = rel
    if changed:
        try:
            mark_path.write_text(json.dumps(marks, sort_keys=True, indent=0), encoding="utf-8")
        except OSError:
            pass
    note = f"headshots: {len(found)} faces on the game cards, {fetched} downloaded"
    if failed:
        note += f", {failed} failed (initials shown)"
    return found, note
