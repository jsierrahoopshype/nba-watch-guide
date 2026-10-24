"""Player headshots for the hub's game cards, copied into the published tree.

Source: jsierrahoopshype/nba-headshots.
  players/metadata/players_all.json lists every player with a headshot
  record whose "filename" is "<nba_id>-<slug>.png"; the same file under
  players/headshots/face/ is a 256x256 transparent cutout (head and
  shoulders, no background). The build shrinks it to a 160x160 WebP that
  keeps the transparency, so the face sits on the page's own light circle.
  (face2-160, used before Oct 2026, had a dark baked-in background and,
  on some players, a black band across the bottom.)

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
FACE_DIR = "players/headshots/face"
FACE_SIZE = 160
INDEX_CACHE = "data/headshots-index.json"
FACES = "assets/faces"
# Which source each file in assets/faces came from, kept per file in
# assets/faces/sources.json. The published tree keeps faces between runs, so
# a file without the current mark is fetched again the next time a page
# needs it (same file name, so no page HTML changes). An offline run keeps
# the old file rather than dropping to a silhouette.
SOURCE_MARK = "face-cutout-160-v1"
SOURCE_FILE = "sources.json"
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


def cutout_webp(png: bytes) -> bytes:
    """A transparent PNG cutout as a FACE_SIZE square WebP that keeps its alpha."""
    import io

    from PIL import Image

    with Image.open(io.BytesIO(png)) as im:
        im = im.convert("RGBA")
        if im.size != (FACE_SIZE, FACE_SIZE):
            im = im.resize((FACE_SIZE, FACE_SIZE), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=82, method=6, exact=False)
    return buf.getvalue()


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
                data = get(f"{base_url()}/{FACE_DIR}/{stem}.png")
                if not isinstance(data, (bytes, bytearray)) or data[:8] != b"\x89PNG\r\n\x1a\n":
                    raise FetchError("not a PNG file")
                webp = cutout_webp(bytes(data))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(webp)
                marks[stem] = SOURCE_MARK
                changed = True
                fetched += 1
            except Exception:
                failed += 1
        if target.is_file():
            found[key] = rel
    if changed:
        try:
            mark_path.write_text(json.dumps(marks, sort_keys=True, indent=0), encoding="utf-8")
        except OSError:
            pass
    note = f"headshots: {len(found)} faces on the game cards, {fetched} downloaded"
    if failed:
        note += f", {failed} failed (silhouette shown)"
    return found, note
