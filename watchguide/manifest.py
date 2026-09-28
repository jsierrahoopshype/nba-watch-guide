"""The list of pages a build must produce, worked out from the data files.

hub + tonight + one page per team in data/teams.json + one page per country
in data/countries.json. Every build writes it to data/expected-pages.txt in
the published tree, one path per line, and scripts/publish.sh refuses to
publish a tree whose index.html files are not exactly these paths. Adding a
team or a country to the data changes the list with no code change.
"""

from __future__ import annotations

from pathlib import Path

from .countries import load_countries
from .model import load_teams

MANIFEST_FILE = "data/expected-pages.txt"
FIXED_PAGES = ("index.html", "tonight/index.html")


def expected_pages(data_dir: Path | None = None) -> list[str]:
    """Paths relative to the publish root, sorted."""
    pages = list(FIXED_PAGES)
    pages += [f"{t.slug}/index.html" for t in load_teams(data_dir)]
    pages += [f"{c.slug}/index.html" for c in load_countries(data_dir).countries]
    if len(set(pages)) != len(pages):
        dupes = sorted({p for p in pages if pages.count(p) > 1})
        raise ValueError(f"two pages would share a path: {', '.join(dupes)}")
    return sorted(pages)


def write_manifest(out_dir: Path, pages: list[str]) -> None:
    target = out_dir / MANIFEST_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(f"{p}\n" for p in pages), encoding="utf-8")


def read_manifest(out_dir: Path) -> list[str]:
    path = out_dir / MANIFEST_FILE
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def mismatch(expected: list[str], found: list[str]) -> tuple[list[str], list[str]]:
    """(missing, unexpected)."""
    want, have = set(expected), set(found)
    return sorted(want - have), sorted(have - want)
