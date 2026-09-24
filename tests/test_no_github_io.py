"""Rule: the Pages host must never appear in anything we publish."""

from __future__ import annotations

BANNED = "github.io"


def test_no_pages_host_anywhere(built_site):
    offenders = []
    for path in sorted(built_site.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".html", ".json", ".xml", ".txt", ".css", ".js"}:
            continue
        if BANNED in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(str(path.relative_to(built_site)))
    assert offenders == [], f"{BANNED} found in: {offenders}"
